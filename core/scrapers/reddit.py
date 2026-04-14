"""Reddit scraper — WSB / stocks / investing without auth.

Uses the old-Reddit JSON endpoint which is free and auth-less. We
query ``/r/{sub}/search.json`` per ticker (recent week, restrict to
the sub) and the hot listing for watchlist-independent buzz.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class RedditScraper(ScraperBase):
    name = "reddit"
    kind = "social"

    #: Subs to search for ticker-specific buzz.
    TICKER_SUBS: List[str] = ["wallstreetbets", "stocks", "investing"]

    #: Also fetch the hot listing from these subs for trending tickers.
    HOT_SUBS: List[str] = ["wallstreetbets", "stocks"]

    MAX_PER_SUB: int = 10
    MAX_HOT_PER_SUB: int = 25

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []

        if tickers:
            for raw_ticker in tickers:
                clean = self.clean_ticker(raw_ticker)
                if not clean:
                    continue
                items.extend(self._fetch_ticker(clean))

        # Hot feeds — market-wide trending regardless of watchlist.
        items.extend(self._fetch_hot())
        return items

    # ── per-ticker search ───────────────────────────────────────────

    def _fetch_ticker(self, ticker: str) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        for sub in self.TICKER_SUBS:
            url = f"https://old.reddit.com/r/{sub}/search.json"
            data = self.fetch_json(url, params={
                "q": ticker,
                "sort": "new",
                "t": "week",
                "limit": str(self.MAX_PER_SUB),
                "restrict_sr": "on",
            })
            if not isinstance(data, dict):
                continue
            children = (data.get("data") or {}).get("children") or []
            for child in children:
                item = _to_item(ticker, sub, child)
                if item is not None:
                    items.append(item)
        return items

    # ── hot / trending ──────────────────────────────────────────────

    def _fetch_hot(self) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        for sub in self.HOT_SUBS:
            url = f"https://old.reddit.com/r/{sub}/hot.json"
            data = self.fetch_json(url, params={"limit": str(self.MAX_HOT_PER_SUB)})
            if not isinstance(data, dict):
                continue
            children = (data.get("data") or {}).get("children") or []
            for child in children:
                item = _to_item(None, sub, child)
                if item is not None:
                    items.append(item)
        return items


def _to_item(
    ticker: Optional[str],
    sub: str,
    child: Dict[str, Any],
) -> Optional[ScrapedItem]:
    payload = child.get("data") or {}
    title = (payload.get("title") or "").strip()
    if not title:
        return None
    permalink = payload.get("permalink") or ""
    url = f"https://reddit.com{permalink}" if permalink else ""

    created_utc = payload.get("created_utc")
    ts: Optional[datetime] = None
    if isinstance(created_utc, (int, float)):
        try:
            ts = datetime.utcfromtimestamp(float(created_utc))
        except (ValueError, OSError):
            ts = None

    return ScrapedItem(
        source="reddit",
        kind="social",
        title=title,
        url=url,
        ticker=ticker,
        ts=ts,
        summary=(payload.get("selftext") or "")[:500],
        meta={
            "subreddit": sub,
            "score": payload.get("score"),
            "num_comments": payload.get("num_comments"),
            "author": payload.get("author"),
            "is_hot": ticker is None,
        },
    )
