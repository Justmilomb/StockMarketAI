"""Social tools — buzz score + raw posts from StockTwits, Reddit, x.com.

The heavy lifting lives in ``core.scrapers``; this module just reads
the cached items for a given ticker and computes a simple buzz score
the agent can feed into its decisions.

Buzz score heuristic
--------------------

``buzz_score`` = number of posts per hour in the lookback window,
normalised by 10 (so ~10 posts/hour ≈ 1.0). It's coarse on purpose —
we don't want the agent to treat this as a regression output, just
as a "lots of chatter happening right now" signal.

``sentiment`` is the StockTwits bullish-vs-bearish ratio clamped into
[-1.0, 1.0]. Posts without an explicit sentiment tag (most Reddit /
x items) are ignored for sentiment computation but still counted
toward buzz.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.agent._sdk import tool

from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _row_to_public(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": row.get("source"),
        "ticker": row.get("ticker"),
        "title": row.get("title"),
        "url": row.get("url"),
        "ts": row.get("ts") or row.get("fetched_at"),
        "meta": row.get("meta") or {},
    }


def _live_fallback(ticker: str, since_minutes: int) -> List[Dict[str, Any]]:
    try:
        from core.scrapers import SCRAPERS
    except Exception:
        return []

    hits: List[Dict[str, Any]] = []
    for scraper in SCRAPERS:
        if scraper.kind != "social":
            continue
        for it in scraper.safe_fetch(tickers=[ticker], since_minutes=since_minutes):
            hits.append(_row_to_public(it.to_dict()))
    return hits


def _compute_score(items: List[Dict[str, Any]], since_minutes: int) -> Dict[str, Any]:
    total = len(items)
    hours = max(since_minutes / 60.0, 0.1)
    posts_per_hour = total / hours
    buzz_score = min(posts_per_hour / 10.0, 10.0)  # cap at 10×

    bulls = 0
    bears = 0
    for it in items:
        meta = it.get("meta") or {}
        sentiment = meta.get("sentiment")
        if sentiment == "Bullish":
            bulls += 1
        elif sentiment == "Bearish":
            bears += 1
    if bulls + bears > 0:
        sentiment_score = (bulls - bears) / (bulls + bears)
    else:
        sentiment_score = 0.0

    return {
        "buzz_score": round(buzz_score, 2),
        "posts_per_hour": round(posts_per_hour, 2),
        "total_posts": total,
        "sentiment": round(sentiment_score, 2),
        "bulls": bulls,
        "bears": bears,
    }


@tool(
    "get_social_buzz",
    "Return a social buzz summary for one ticker: post count, "
    "posts/hour, sentiment (from StockTwits tags), and the top recent "
    "posts. Aggregates StockTwits, Reddit, and x.com via Google News. "
    "Falls back to a live one-shot fetch if the cache is empty.",
    {"ticker": str, "since_minutes": int, "limit": int},
)
async def get_social_buzz(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip().upper().split("_")[0]
    if not ticker:
        return _text_result({"error": "ticker is required"})
    since_minutes = int(args.get("since_minutes") or 240)
    limit = int(args.get("limit") or 20)

    rows = ctx.db.get_scraper_items(
        kinds=["social"],
        tickers=[ticker],
        since_minutes=since_minutes,
        limit=max(limit, 100),
    )
    items = [_row_to_public(r) for r in rows]

    if not items:
        items = _live_fallback(ticker, since_minutes)

    summary = _compute_score(items, since_minutes)
    return _text_result({
        "ticker": ticker,
        "since_minutes": since_minutes,
        **summary,
        "top_posts": items[:limit],
    })


@tool(
    "get_market_buzz",
    "Return trending tickers across Reddit WSB / stocks hot lists — "
    "market-wide buzz independent of the watchlist. Useful for "
    "discovering what retail is piling into right now.",
    {"limit": int},
)
async def get_market_buzz(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    limit = int(args.get("limit") or 15)

    # Reddit hot items don't carry a ticker tag; pull every recent
    # social row and compute a ticker frequency table.
    rows = ctx.db.get_scraper_items(
        kinds=["social"],
        since_minutes=180,
        limit=300,
    )
    import re
    from collections import Counter

    counts: Counter[str] = Counter()
    top_posts: List[Dict[str, Any]] = []
    _STOPWORDS = {
        "DD", "CEO", "IPO", "SEC", "FDA", "EU", "ATH", "YOLO", "HODL",
        "EPS", "ETF", "WSB", "USA", "NYSE", "THE", "AND", "FOR", "NOT",
        "BUT", "WITH", "FROM", "JUST", "HAVE", "BEEN", "WILL", "WHAT",
        "YOUR", "WHEN", "THEY", "THAN", "INTO", "OVER", "NEWS", "FREE",
    }
    for r in rows:
        title = str(r.get("title") or "")
        for match in re.findall(r"\b[A-Z]{2,5}\b", title):
            if match not in _STOPWORDS:
                counts[match] += 1
        top_posts.append(_row_to_public(r))

    trending = [{"ticker": t, "mentions": n} for t, n in counts.most_common(limit)]
    return _text_result({
        "trending": trending,
        "top_posts": top_posts[:limit],
    })


SOCIAL_TOOLS = [get_social_buzz, get_market_buzz]
