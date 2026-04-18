"""News tools — aggregated headline feed from the scraper cache.

The scraper runner writes into ``scraper_items`` on a schedule; these
tools read from there so the agent sees headlines immediately instead
of waiting for a live HTTP round-trip per source.

If the cache is empty (fresh install, runner not yet started, or
recent purge) we fall back to a one-shot live fetch via
``core.scrapers`` so the agent still gets useful output on its first
iteration. This is the only tool in the bus that does synchronous
HTTP — the cost is bounded by each scraper's ``MAX_PER_TICKER`` and
rate-limiter.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool

from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _parse_tickers(raw: Any) -> List[str]:
    """Coerce the incoming ``tickers`` arg to a clean list of symbols."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        # Accept either JSON array strings or comma-separated strings.
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except (ValueError, TypeError):
            pass
        return [t.strip() for t in stripped.split(",") if t.strip()]
    return []


def _row_to_public(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal-only keys from a scraper_items row."""
    return {
        "source": row.get("source"),
        "kind": row.get("kind"),
        "ticker": row.get("ticker"),
        "title": row.get("title"),
        "url": row.get("url"),
        "ts": row.get("ts") or row.get("fetched_at"),
        "summary": row.get("summary"),
        "meta": row.get("meta") or {},
        "sentiment_score": row.get("sentiment_score"),
        "sentiment_label": row.get("sentiment_label"),
    }


def _live_fallback(
    tickers: List[str],
    since_minutes: int,
    kinds: List[str],
) -> List[Dict[str, Any]]:
    """Cache miss recovery: run every scraper once, synchronously.

    Importing ``core.scrapers`` lazily keeps the tool bus startup cheap
    and avoids a hard dependency on ``requests`` at import time.
    """
    try:
        from core.scrapers import SCRAPERS
    except Exception:
        return []

    hits: List[Dict[str, Any]] = []
    for scraper in SCRAPERS:
        if scraper.kind not in kinds:
            continue
        items = scraper.safe_fetch(tickers=tickers, since_minutes=since_minutes)
        for it in items:
            hits.append(_row_to_public(it.to_dict()))
    return hits


@tool(
    "get_news",
    "Return recent news headlines from the scraper cache, optionally "
    "filtered to a list of tickers. Covers Google News, BBC, financial "
    "news feeds, and YouTube finance channels. If the cache is "
    "empty, falls back to a one-shot live fetch.",
    {"tickers": str, "since_minutes": int, "limit": int},
)
async def get_news(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    tickers = _parse_tickers(args.get("tickers"))
    since_minutes = int(args.get("since_minutes") or 120)
    limit = int(args.get("limit") or 40)

    rows = ctx.db.get_scraper_items(
        kinds=["news"],
        tickers=tickers or None,
        since_minutes=since_minutes,
        limit=limit,
    )
    items = [_row_to_public(r) for r in rows]

    if not items:
        items = _live_fallback(tickers, since_minutes, kinds=["news"])[:limit]

    return _text_result({
        "tickers": tickers,
        "since_minutes": since_minutes,
        "count": len(items),
        "items": items,
    })


@tool(
    "subscribe_news",
    "Add tickers to the background scraper watchlist so their news is "
    "refreshed automatically on every scraper cycle. The agent's "
    "watchlist is the source of truth; this is a no-op convenience "
    "that just ensures the tickers are present on it.",
    {"tickers": str},
)
async def subscribe_news(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    tickers = _parse_tickers(args.get("tickers"))
    if not tickers:
        return _text_result({"status": "rejected", "reason": "tickers required"})

    key = "watchlists_paper" if ctx.paper_mode else "watchlists"
    wl_root = ctx.config.setdefault(key, {})
    if not isinstance(wl_root, dict):
        wl_root = {}
        ctx.config[key] = wl_root
    name = str(ctx.config.get("active_watchlist", "Default"))
    current = list(wl_root.get(name, []) or [])
    added: List[str] = []
    for t in tickers:
        if t not in current:
            current.append(t)
            added.append(t)
    wl_root[name] = current

    return _text_result({
        "status": "ok",
        "added": added,
        "watchlist": name,
        "size": len(current),
    })


@tool(
    "get_scraper_health",
    "Return a snapshot of every scraper's health (last success, "
    "consecutive errors, total calls). Useful when headlines look "
    "stale and you want to know which source is degraded.",
    {},
)
async def get_scraper_health(args: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from core.scrapers import SCRAPERS
    except Exception as exc:
        return _text_result({"error": f"scrapers unavailable: {exc}"})
    return _text_result({
        "scrapers": [s.get_health() for s in SCRAPERS],
    })


NEWS_TOOLS = [get_news, subscribe_news, get_scraper_health]
