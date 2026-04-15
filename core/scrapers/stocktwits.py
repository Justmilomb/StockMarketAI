"""StockTwits scraper — real-time retail chat + bullish/bearish flags.

StockTwits exposes a free, auth-less JSON API:

    https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json
    https://api.stocktwits.com/api/2/streams/trending.json

Each message has:
    body         — the post text
    created_at   — ISO timestamp
    entities.sentiment.basic — "Bullish" | "Bearish" | null
    user.username, id, ...
    symbols      — list of {symbol, ...} the post is tagged with

When the caller supplies a watchlist we fetch per ticker. When they
don't, we hit the ``trending`` stream so the cache still fills on a
fresh account — the trending endpoint returns recent high-velocity
messages across the whole market and is the same one the StockTwits
web app uses for its "Trending" tab.

Each message becomes a ``ScrapedItem`` with the sentiment hint stashed
in ``meta`` so downstream tools can compute a buzz score.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class StockTwitsScraper(ScraperBase):
    name = "stocktwits"
    kind = "social"

    SYMBOL_URL_TEMPLATE: str = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    TRENDING_URL: str = "https://api.stocktwits.com/api/2/streams/trending.json"

    #: Cap per ticker — stream can return up to 30.
    MAX_PER_TICKER: int = 25

    #: Cap on broad (trending) fetches — trending stream returns up to 30.
    MAX_BROAD: int = 30

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        if tickers:
            return self._fetch_per_ticker(tickers)
        return self._fetch_trending()

    def _fetch_per_ticker(self, tickers: List[str]) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        for raw_ticker in tickers:
            clean = self.clean_ticker(raw_ticker)
            if not clean:
                continue
            url = self.SYMBOL_URL_TEMPLATE.format(ticker=clean)
            data = self.fetch_json(url)
            if not isinstance(data, dict):
                continue
            messages = data.get("messages") or []
            for msg in messages[: self.MAX_PER_TICKER]:
                item = _to_item(clean, msg, mode="symbol")
                if item is not None:
                    items.append(item)
        return items

    def _fetch_trending(self) -> List[ScrapedItem]:
        data = self.fetch_json(self.TRENDING_URL)
        if not isinstance(data, dict):
            return []
        messages = data.get("messages") or []
        items: List[ScrapedItem] = []
        for msg in messages[: self.MAX_BROAD]:
            # Trending messages carry their own symbol list; pick the
            # first entry if present so the buzz score has something
            # to aggregate on. Messages without a symbol tag still get
            # stored (ticker=None) so they're usable for market-wide
            # mood sampling.
            symbols = msg.get("symbols") or []
            ticker: Optional[str] = None
            if isinstance(symbols, list) and symbols:
                first = symbols[0]
                if isinstance(first, dict):
                    ticker = str(first.get("symbol") or "").strip() or None
            item = _to_item(ticker, msg, mode="trending")
            if item is not None:
                items.append(item)
        return items


def _to_item(
    ticker: Optional[str],
    msg: Dict[str, Any],
    mode: str = "symbol",
) -> Optional[ScrapedItem]:
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
            "mode": mode,
        },
    )
