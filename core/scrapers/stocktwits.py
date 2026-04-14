"""StockTwits scraper — real-time retail chat + bullish/bearish flags.

StockTwits exposes a free, auth-less JSON API:

    https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json

Each message has:
    body         — the post text
    created_at   — ISO timestamp
    entities.sentiment.basic — "Bullish" | "Bearish" | null
    user.username, id, ...

We fetch the stream per ticker in the caller's watchlist and produce
a ``ScrapedItem`` per message with the sentiment hint stashed in
``meta`` so downstream tools can compute a buzz score.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class StockTwitsScraper(ScraperBase):
    name = "stocktwits"
    kind = "social"

    URL_TEMPLATE: str = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

    #: Cap per ticker — stream can return up to 30.
    MAX_PER_TICKER: int = 25

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        if not tickers:
            return []

        items: List[ScrapedItem] = []
        for raw_ticker in tickers:
            clean = self.clean_ticker(raw_ticker)
            if not clean:
                continue
            url = self.URL_TEMPLATE.format(ticker=clean)
            data = self.fetch_json(url)
            if not isinstance(data, dict):
                continue
            messages = data.get("messages") or []
            for msg in messages[: self.MAX_PER_TICKER]:
                item = _to_item(clean, msg)
                if item is not None:
                    items.append(item)
        return items


def _to_item(ticker: str, msg: Dict[str, Any]) -> Optional[ScrapedItem]:
    body = (msg.get("body") or "").strip()
    if not body:
        return None

    user = msg.get("user") or {}
    entities = msg.get("entities") or {}
    sentiment_obj = entities.get("sentiment") or {}
    sentiment_basic = sentiment_obj.get("basic")  # "Bullish" | "Bearish" | None

    ts: Optional[datetime] = None
    created = msg.get("created_at")
    if isinstance(created, str):
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            ts = None

    msg_id = msg.get("id")
    url = f"https://stocktwits.com/{user.get('username', '')}/message/{msg_id}" if msg_id else ""

    return ScrapedItem(
        source="stocktwits",
        kind="social",
        title=body[:280],
        url=url,
        ticker=ticker,
        ts=ts,
        summary="",
        meta={
            "username": user.get("username"),
            "followers": user.get("followers"),
            "sentiment": sentiment_basic,
        },
    )
