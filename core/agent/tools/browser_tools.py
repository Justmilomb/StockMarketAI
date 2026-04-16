"""Research-only browser tool.

``fetch_page`` lets the agent pull a single URL and receive the cleaned
article text. It exists so the agent can read things the typed tool bus
can't cover — earnings releases, SEC filings, macro posts, the long
tail of ticker-specific IR pages — without us building a dedicated
scraper for each.

**This tool is not a price feed.** The system prompt forbids using it
to poll prices. Latency is high (seconds per page), token cost is
high (HTML payloads), and the broker already returns live prices for
held positions via ``get_portfolio``. ``get_live_price`` covers the
rest at a fraction of the cost.

Safety
------

* Per-iteration hard cap on fetches (default 10) — tracked on
  ``ctx.stats["browser_fetches"]`` so the limit survives any single
  tool invocation.
* SSRF guard: only ``http://`` and ``https://`` URLs, with a blocklist
  for localhost, loopback, and RFC1918 private ranges.
* Response body read is capped at ~1 MB so a malicious or broken page
  can't OOM the runner.
* Downloaded HTML is stripped of ``<script>``, ``<style>``, ``<nav>``,
  ``<aside>``, ``<header>``, ``<footer>``, ``<form>``, ``<iframe>``,
  ``<button>`` before text extraction. The largest meaningful block
  (``<article>`` → ``<main>`` → longest ``<div>``) is preferred, with
  a body-level fallback.
"""
from __future__ import annotations

import json
import logging
import random
import re
import socket
import ssl
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core.agent._sdk import tool

from core.agent.context import get_agent_context

logger = logging.getLogger(__name__)

#: Hard cap on page fetches per agent iteration. The agent can pass a
#: lower ``max_chars`` but not a higher fetch count.
MAX_FETCHES_PER_ITER: int = 10

#: Body read cap — we stop at this many bytes even if Content-Length is
#: larger. Keeps a runaway page from eating the runner.
MAX_BODY_BYTES: int = 1_000_000

#: Default character budget for the cleaned text we return to the
#: agent. Chosen to leave plenty of room in the context window.
DEFAULT_MAX_CHARS: int = 8000

#: Absolute ceiling on ``max_chars`` — the agent can't ask for more.
HARD_MAX_CHARS: int = 20000

#: HTTP timeout (seconds).
FETCH_TIMEOUT: float = 15.0

#: Reused User-Agent pool — keeps us off the most obvious bot lists.
USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

_PRIVATE_HOST_PREFIXES: tuple[str, ...] = (
    "10.", "127.", "0.", "169.254.",
    "192.168.",
    *(f"172.{i}." for i in range(16, 32)),
)

_STRIP_TAGS: tuple[str, ...] = (
    "script", "style", "noscript", "nav", "aside", "header", "footer",
    "form", "iframe", "button", "svg", "canvas",
)

_WHITESPACE_RE = re.compile(r"\s+")


# ── helpers ────────────────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _validate_url(raw: str) -> tuple[Optional[str], Optional[str]]:
    """Return (normalised_url, error_message). Error is None on success."""
    if not raw or not isinstance(raw, str):
        return None, "url is required"
    raw = raw.strip()
    try:
        parsed = urlparse(raw)
    except Exception as exc:
        return None, f"could not parse url: {exc}"

    if parsed.scheme not in ("http", "https"):
        return None, f"unsupported scheme '{parsed.scheme}' — only http/https allowed"
    if not parsed.netloc:
        return None, "url is missing a host"

    host = parsed.hostname or ""
    lower = host.lower()
    if lower in ("localhost", "::1"):
        return None, "blocked: localhost"
    if any(lower.startswith(p) for p in _PRIVATE_HOST_PREFIXES):
        return None, f"blocked: private address {lower}"

    return parsed.geturl(), None


def _bump_fetch_count() -> int:
    ctx = get_agent_context()
    count = int(ctx.stats.get("browser_fetches", 0)) + 1
    ctx.stats["browser_fetches"] = count
    return count


def _current_fetch_count() -> int:
    ctx = get_agent_context()
    return int(ctx.stats.get("browser_fetches", 0))


def _extract_article_text(html: bytes) -> tuple[str, str]:
    """Return (title, cleaned_text) from raw HTML bytes using lxml."""
    try:
        from lxml import html as lhtml  # lazy — lxml is already a dep
    except ImportError as exc:
        raise RuntimeError(f"lxml not available: {exc}") from exc

    # lxml handles encoding detection; drop any stray null bytes first.
    doc = lhtml.fromstring(html.replace(b"\x00", b""))

    # Title first — prefer <title>, fall back to <h1>.
    title_nodes = doc.xpath("//title/text()")
    title = (title_nodes[0] if title_nodes else "").strip()
    if not title:
        h1_nodes = doc.xpath("//h1//text()")
        title = " ".join(t.strip() for t in h1_nodes if t and t.strip())[:200]

    # Rip out boilerplate tags.
    for tag in _STRIP_TAGS:
        for el in doc.xpath(f"//{tag}"):
            el.getparent().remove(el) if el.getparent() is not None else None

    # Prefer <article>, then <main>, then the longest <div> by text length.
    candidates = doc.xpath("//article")
    if not candidates:
        candidates = doc.xpath("//main")
    if not candidates:
        divs = doc.xpath("//div")
        if divs:
            candidates = [max(divs, key=lambda d: len(d.text_content() or ""))]
    if not candidates:
        candidates = doc.xpath("//body")

    text = ""
    if candidates:
        text = candidates[0].text_content() or ""
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return title, text


def _journal_fetch(url: str, status: int, length: int, err: str = "") -> None:
    """Best-effort journal row so fetches show up in the agent log."""
    try:
        import sqlite3
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'browser_fetch', 'fetch_page', ?, 'browser')",
                (
                    ctx.iteration_id,
                    json.dumps(
                        {"url": url, "status": status, "bytes": length, "error": err},
                        default=str,
                    ),
                ),
            )
    except Exception as exc:  # journal is best-effort
        logger.debug("browser_tools journal insert failed: %s", exc)


# ── tools ──────────────────────────────────────────────────────────────

@tool(
    "fetch_page",
    (
        "Fetch a web page by URL and return its cleaned article text. "
        "Use for RESEARCH reads only: earnings press releases, SEC filings, "
        "analyst blog posts, IR pages, macro news, long-tail ticker context "
        "the other tools can't reach. "
        "DO NOT USE FOR LIVE PRICES — call get_live_price instead; it's "
        "an order of magnitude faster and cheaper. "
        "Hard cap: 10 fetches per iteration. Response is truncated to "
        "max_chars (default 8000). Only http/https URLs are accepted; "
        "localhost and private IPs are blocked."
    ),
    {"url": str, "max_chars": int},
)
async def fetch_page(args: Dict[str, Any]) -> Dict[str, Any]:
    # ── 1. rate limit ──
    current = _current_fetch_count()
    if current >= MAX_FETCHES_PER_ITER:
        return _text_result({
            "error": (
                f"fetch_page rate limit reached "
                f"({current}/{MAX_FETCHES_PER_ITER} per iteration). "
                f"Use end_iteration and continue next wake-up."
            ),
            "fetch_count": current,
        })

    # ── 2. validate URL ──
    raw_url = str(args.get("url", "") or "")
    url, err = _validate_url(raw_url)
    if err:
        return _text_result({"error": err, "url": raw_url})
    assert url is not None  # for mypy

    max_chars_raw = args.get("max_chars", DEFAULT_MAX_CHARS)
    try:
        max_chars = int(max_chars_raw or DEFAULT_MAX_CHARS)
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_CHARS
    max_chars = max(500, min(max_chars, HARD_MAX_CHARS))

    # Count the attempt immediately so errors still burn budget.
    new_count = _bump_fetch_count()

    # ── 3. download with a hard byte cap ──
    #
    # We deliberately use stdlib ``urllib.request`` here, not requests
    # or httpx. The reason is portability: Python 3.14 + OpenSSL 3.x on
    # Windows doesn't always plumb the system CA store through to
    # ``urllib3``'s SSL context, but it does work via
    # ``ssl.create_default_context()`` (which stdlib uses). Research
    # fetches are one-shot and don't need sessions or cookies, so the
    # simpler stdlib path wins on every axis that matters to us.
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Connection": "close",
    }

    parsed_host = urlparse(url).hostname or "?"
    status_code: int = 0
    body = b""
    ssl_ctx = ssl.create_default_context()
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=FETCH_TIMEOUT, context=ssl_ctx) as resp:
            status_code = int(getattr(resp, "status", 200))
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if content_type and not any(
                t in content_type for t in ("html", "xml", "text", "json")
            ):
                _journal_fetch(url, status_code, 0, f"unsupported content-type {content_type}")
                return _text_result({
                    "error": f"unsupported content-type: {content_type}",
                    "url": url,
                    "status": status_code,
                    "fetch_count": new_count,
                })

            total = 0
            chunks: list[bytes] = []
            while True:
                chunk = resp.read(32 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BODY_BYTES:
                    chunks.append(chunk[: MAX_BODY_BYTES - (total - len(chunk))])
                    break
                chunks.append(chunk)
            body = b"".join(chunks)
    except HTTPError as exc:
        _journal_fetch(url, int(exc.code), 0, f"http {exc.code}")
        return _text_result({
            "error": f"http {exc.code}",
            "url": url,
            "status": int(exc.code),
            "fetch_count": new_count,
        })
    except socket.timeout:
        _journal_fetch(url, 0, 0, "timeout")
        return _text_result({
            "error": f"timeout after {FETCH_TIMEOUT}s",
            "url": url,
            "fetch_count": new_count,
        })
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        _journal_fetch(url, 0, 0, str(reason))
        return _text_result({
            "error": f"fetch failed: {reason}",
            "url": url,
            "fetch_count": new_count,
        })
    except Exception as exc:
        _journal_fetch(url, 0, 0, str(exc))
        return _text_result({
            "error": f"fetch failed: {exc}",
            "url": url,
            "fetch_count": new_count,
        })

    # ── 4. extract main-article text ──
    try:
        title, text = _extract_article_text(body)
    except Exception as exc:
        _journal_fetch(url, status_code, len(body), f"extract failed: {exc}")
        return _text_result({
            "error": f"html parse failed: {exc}",
            "url": url,
            "status": status_code,
            "fetch_count": new_count,
        })

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars].rsplit(" ", 1)[0] + "…"

    _journal_fetch(url, status_code, len(body), "")

    return _text_result({
        "url": url,
        "host": parsed_host,
        "status": status_code,
        "title": title,
        "text": text,
        "truncated": truncated,
        "bytes": len(body),
        "fetch_count": new_count,
        "fetches_remaining": max(0, MAX_FETCHES_PER_ITER - new_count),
    })


BROWSER_TOOLS = [fetch_page]
