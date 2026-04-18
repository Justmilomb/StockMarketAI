"""ScraperBase — rate-limited HTTP, UA rotation, safe-fail plumbing.

Every concrete scraper in this package should inherit from
``ScraperBase`` and implement the ``fetch`` method. The base class
handles the boring-but-important stuff:

* Per-domain rate limiting with exponential backoff on 429/503.
* User-Agent rotation across a pool of real browser strings.
* A health record (last success / last failure / consecutive errors)
  so the tool bus can report degraded sources without the agent
  retrying a dead endpoint on every iteration.
* **Never raises.** ``safe_fetch`` wraps ``fetch`` in a try/except so a
  broken scraper returns an empty list instead of crashing the worker.

The rate-limiter + UA pool are lifted verbatim from the old
``core.news_agent`` helpers so we match behaviour that's already been
proven on the existing subscription tier.
"""
from __future__ import annotations

import logging
import random
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)


class _StdlibSSLAdapter(HTTPAdapter):
    """HTTPAdapter that plumbs ``ssl.create_default_context()`` into urllib3.

    Python 3.14 + urllib3 on Windows has a quirk: the pool manager's
    default SSL context doesn't load the Windows system trust store, so
    every HTTPS request explodes with ``CERTIFICATE_VERIFY_FAILED`` on a
    dev box that hasn't installed certifi manually. Stdlib's
    ``ssl.create_default_context()`` *does* pick up the Windows certs,
    so we hand urllib3 one of those instead of letting it build its own.

    Production ``.exe`` builds bundle certifi and are unaffected, but
    the adapter is harmless there — certifi-loaded contexts are still
    the stdlib default.
    """

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        kwargs["ssl_context"] = ssl.create_default_context()
        return super().proxy_manager_for(*args, **kwargs)


#: Pool of real browser UAs. The scrapers rotate across these on every
#: request so any one source doesn't see a stable fingerprint.
USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


ItemKind = Literal["news", "social"]


@dataclass
class ScrapedItem:
    """One normalised entry from any scraper — news headline or social post.

    ``meta`` is a free-form dict for source-specific extras (upvote
    counts, view counts, sentiment hints, channel names, etc.) that
    downstream consumers can pluck out as needed.
    """
    source: str
    kind: ItemKind
    title: str
    url: str
    ticker: Optional[str] = None
    ts: Optional[datetime] = None
    summary: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "kind": self.kind,
            "title": self.title,
            "url": self.url,
            "ticker": self.ticker,
            "ts": self.ts.isoformat() if self.ts else None,
            "summary": self.summary,
            "meta": self.meta,
        }


@dataclass
class ScraperHealth:
    """Rolling health snapshot for a single scraper."""
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_errors: int = 0
    total_calls: int = 0
    total_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        """Return True if the scraper isn't currently wedged."""
        # Three strikes == unhealthy. The worker still retries later but
        # tools can flag it to the agent.
        return self.consecutive_errors < 3


class ScraperBase:
    """Base class every scraper inherits from.

    Subclasses implement ``fetch(tickers, since_minutes)`` and return a
    list of ``ScrapedItem``. They use ``self.rate_limited_get`` (or
    ``fetch_rss`` / ``fetch_json``) so the base class can enforce the
    rate budget.
    """

    #: Source identifier, also used as DB key and in health reports.
    name: str = "base"

    #: What kind of items this scraper produces.
    kind: ItemKind = "news"

    #: Minimum seconds between hits on any one host. 2s matches the
    #: legacy news_agent default and has never tripped rate limits.
    rate_limit_seconds: float = 2.0

    def __init__(self) -> None:
        self._session: requests.Session = requests.Session()
        self._session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        # See _StdlibSSLAdapter docstring — required on Windows dev boxes
        # running Python 3.14 so urllib3 picks up the system trust store.
        adapter = _StdlibSSLAdapter()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._domain_last_hit: Dict[str, float] = {}
        self._lock: Lock = Lock()
        self.health: ScraperHealth = ScraperHealth()

    # ── Public entry points ──────────────────────────────────────────

    def safe_fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        """Run ``fetch`` inside a try/except and update health stats.

        Never raises. On failure returns ``[]`` and logs at DEBUG — the
        worker logs aggregate counts, so per-source noise stays off the
        main log. On success, resets the consecutive-error counter.
        """
        self.health.total_calls += 1
        try:
            items = list(self.fetch(tickers=tickers, since_minutes=since_minutes))
        except Exception as exc:
            self.health.last_failure = datetime.utcnow()
            self.health.consecutive_errors += 1
            self.health.total_failures += 1
            logger.debug("[%s] fetch failed: %s", self.name, exc)
            return []

        self.health.last_success = datetime.utcnow()
        self.health.consecutive_errors = 0
        return items

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        """Override in subclasses. Must return a list (possibly empty)."""
        raise NotImplementedError

    # ── Rate-limited HTTP helpers ────────────────────────────────────

    def rate_limited_get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> Optional[requests.Response]:
        """GET with per-domain rate limiting + exponential backoff.

        Returns ``None`` if every attempt failed. The caller is expected
        to handle ``None`` gracefully (return an empty list).
        """
        domain = urlparse(url).netloc
        with self._lock:
            now = time.time()
            wait = self.rate_limit_seconds - (now - self._domain_last_hit.get(domain, 0.0))
            if wait > 0:
                time.sleep(wait)
            # Reserve the slot before we fire the request so parallel
            # threads in a ThreadPoolExecutor don't stampede the host.
            self._domain_last_hit[domain] = time.time()

        self._session.headers["User-Agent"] = random.choice(USER_AGENTS)
        for attempt in range(max_retries):
            try:
                resp = self._session.get(url, params=params, timeout=timeout)
                if resp.status_code in (429, 503):
                    time.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                logger.debug(
                    "[%s] HTTP GET %s attempt %d failed: %s",
                    self.name, url, attempt + 1, exc,
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def fetch_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Fetch and decode JSON. Returns ``None`` on any failure."""
        resp = self.rate_limited_get(url, params=params)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def fetch_rss(self, url: str) -> List[Dict[str, Any]]:
        """Parse an RSS/Atom feed with feedparser. Returns entries as dicts.

        feedparser is intentionally imported lazily so a missing
        dependency doesn't break the import of ``core.scrapers``.
        """
        try:
            import feedparser  # type: ignore
        except ImportError:
            logger.warning(
                "[%s] feedparser not installed — RSS fetch skipped", self.name,
            )
            return []

        resp = self.rate_limited_get(url)
        if resp is None:
            return []
        try:
            parsed = feedparser.parse(resp.text)
        except Exception as exc:
            logger.debug("[%s] RSS parse failed: %s", self.name, exc)
            return []
        return list(parsed.entries or [])

    # ── Utility helpers ──────────────────────────────────────────────

    @staticmethod
    def parse_rss_date(entry: Dict[str, Any]) -> Optional[datetime]:
        """Best-effort RSS entry timestamp extraction."""
        # feedparser sets ``published_parsed`` to a time.struct_time.
        for key in ("published_parsed", "updated_parsed"):
            val = entry.get(key)
            if val is not None:
                try:
                    return datetime(*val[:6])
                except Exception:
                    continue
        return None

    @staticmethod
    def clean_ticker(ticker: str) -> str:
        """Strip broker-suffixes (``TSLA_US_EQ`` → ``TSLA``)."""
        return (ticker or "").split("_")[0].upper()

    def get_health(self) -> Dict[str, Any]:
        """Return a JSON-safe snapshot of the health record."""
        h = self.health
        return {
            "source": self.name,
            "kind": self.kind,
            "is_healthy": h.is_healthy,
            "last_success": h.last_success.isoformat() if h.last_success else None,
            "last_failure": h.last_failure.isoformat() if h.last_failure else None,
            "consecutive_errors": h.consecutive_errors,
            "total_calls": h.total_calls,
            "total_failures": h.total_failures,
        }
