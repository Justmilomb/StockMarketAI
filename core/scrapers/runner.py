"""ScraperRunner — background thread that refreshes the scraper cache.

This is the 24/7 worker the plan calls for. It wakes on a schedule,
asks every scraper in ``core.scrapers.SCRAPERS`` for fresh items
(scoped to the current watchlist), and writes them into
``scraper_items`` via ``HistoryManager.save_scraper_items``.

Design notes
------------

* **Plain ``threading.Thread``, not a QThread.** The runner lives in
  ``core`` so it can be reused by CLI tooling (scripts, tests) without
  dragging PySide6 into ``core``. The desktop app just spins one up
  and calls ``.start()`` — Qt never touches it.
* **Never raises.** Each scraper is invoked via ``safe_fetch``; the
  runner wraps the whole cycle in a try/except so a single bad source
  can't kill the thread. Failures are counted on the scraper's
  ``ScraperHealth`` and surfaced via ``get_health_report``.
* **Watchlist source of truth:** the runner takes a callable so it
  can pull the live watchlist from the app state without coupling to
  any particular state shape.
* **Concurrency:** scrapers run in a small ``ThreadPoolExecutor`` so
  total wall-clock ≈ max(per-source time), not sum.
"""
from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from core.database import HistoryManager
from core.scrapers import SCRAPERS, ScrapedItem, ScraperBase
from core.scrapers._sentiment import score_item
from core.telemetry import hooks as telemetry_hooks

logger = logging.getLogger(__name__)


#: Cadence floor — the runner never polls more often than this even
#: if the caller asks for a lower value. Keeps scrapers well below
#: the rate limits on every source.
CADENCE_FLOOR_SECONDS: int = 60

#: Retention window for cached items. Older rows are purged on each
#: cycle to keep the sqlite file from growing unbounded.
RETENTION_DAYS: int = 7


class ScraperRunner(threading.Thread):
    """Daemon thread that refreshes the scraper cache on a schedule."""

    def __init__(
        self,
        db: HistoryManager,
        watchlist_provider: Callable[[], List[str]],
        *,
        scrapers: Optional[List[ScraperBase]] = None,
        cadence_seconds: int = 300,
        max_workers: int = 4,
    ) -> None:
        super().__init__(daemon=True, name="scraper-runner")
        self._db: HistoryManager = db
        self._watchlist_provider: Callable[[], List[str]] = watchlist_provider
        self._scrapers: List[ScraperBase] = scrapers or list(SCRAPERS)
        self._cadence: int = max(CADENCE_FLOOR_SECONDS, int(cadence_seconds))
        self._max_workers: int = max(1, int(max_workers))

        self._stop_event: threading.Event = threading.Event()
        self._wake_event: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._last_run_at: Optional[float] = None
        self._last_run_stats: Dict[str, int] = {}

    # ── lifecycle ────────────────────────────────────────────────────

    def run(self) -> None:  # noqa: D401 — Thread API
        logger.info("[scraper-runner] started, cadence=%ds", self._cadence)
        # Fire once immediately so the cache isn't empty for the first
        # few minutes of a fresh session.
        self._run_cycle()
        while not self._stop_event.is_set():
            # Use wake_event.wait so request_refresh() can interrupt.
            self._wake_event.wait(timeout=self._cadence)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._run_cycle()
        logger.info("[scraper-runner] stopped")

    def stop(self) -> None:
        """Request the runner to exit at the next safe point."""
        self._stop_event.set()
        self._wake_event.set()

    def request_refresh(self) -> None:
        """Wake the runner immediately, bypassing the cadence sleep."""
        self._wake_event.set()

    # ── one full cycle ───────────────────────────────────────────────

    def _run_cycle(self) -> None:
        try:
            tickers = list(self._watchlist_provider() or [])
        except Exception as exc:
            logger.debug("[scraper-runner] watchlist provider failed: %s", exc)
            tickers = []

        started = time.monotonic()
        total_inserted = 0
        stats: Dict[str, int] = {}

        def run_one(scraper: ScraperBase) -> tuple[str, List[ScrapedItem]]:
            return scraper.name, scraper.safe_fetch(tickers=tickers)

        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self._max_workers,
            ) as pool:
                results = list(pool.map(run_one, self._scrapers))
        except Exception as exc:
            logger.warning("[scraper-runner] cycle failed in pool: %s", exc)
            return

        for name, items in results:
            if not items:
                stats[name] = 0
                continue
            try:
                rows = [it.to_dict() for it in items]
                # Score each row with VADER before saving so the info
                # panel can colour-code headlines and the agent can
                # filter by mood without a second pass.
                rows = [score_item(r) for r in rows]
                # to_dict uses "meta" key, database.save_scraper_items
                # also accepts "meta" via json.dumps fallback.
                new = self._db.save_scraper_items(rows)
                # Telemetry: only ship newly-inserted rows (dedup is
                # done inside save_scraper_items). We approximate by
                # taking the tail ``new`` rows — identical IDs the
                # database already held will be filtered out.
                if new:
                    for r in rows[-new:]:
                        telemetry_hooks.record_scraper_item(r)
            except Exception as exc:
                logger.debug("[scraper-runner] save %s failed: %s", name, exc)
                new = 0
            stats[name] = new
            total_inserted += new

        # Housekeeping — keep the cache size bounded.
        try:
            self._db.purge_old_scraper_items(keep_days=RETENTION_DAYS)
        except Exception as exc:
            logger.debug("[scraper-runner] purge failed: %s", exc)

        with self._lock:
            self._last_run_at = time.time()
            self._last_run_stats = dict(stats)

        logger.info(
            "[scraper-runner] cycle done in %.1fs, inserted=%d, sources=%s",
            time.monotonic() - started, total_inserted,
            ",".join(f"{k}:{v}" for k, v in stats.items()),
        )

    # ── introspection ────────────────────────────────────────────────

    def get_health_report(self) -> Dict[str, Any]:
        """Return a JSON-safe snapshot of per-scraper health + last run."""
        with self._lock:
            last_run_at = self._last_run_at
            last_stats = dict(self._last_run_stats)
        return {
            "last_run_at": last_run_at,
            "last_run_stats": last_stats,
            "scrapers": [s.get_health() for s in self._scrapers],
        }
