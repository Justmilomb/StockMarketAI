"""Google News scraper — primary headline feed.

Google News serves free RSS per search query with no auth and very
lenient rate limits. When the caller supplies a watchlist we query
each ticker by symbol; when they don't, we fall back to a small set
of generic market queries so the cache still fills on a fresh account
with an empty watchlist.
"""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote_plus

from core.scrapers.base import ScrapedItem, ScraperBase


class GoogleNewsScraper(ScraperBase):
    name = "google_news"
    kind = "news"

    #: Template — ``{q}`` is the URL-encoded search query.
    SEARCH_URL: str = (
        "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    )

    #: Per-query cap on the number of items we keep. Headlines past
    #: the top 10 are rarely load-bearing.
    MAX_PER_TICKER: int = 10

    #: Broad-mode queries fired when the caller passes an empty watchlist.
    #: Kept small on purpose — ~8 × 10 = 80 headlines per cycle is plenty
    #: of raw material for the agent without hammering the RSS endpoint.
    FALLBACK_QUERIES: List[str] = [
        "stock market today",
        "trending stocks",
        "earnings beat",
        "stock breakout",
        "biotech fda approval",
        "analyst upgrade",
        "pre-market movers",
        "small cap surge",
    ]

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        if tickers:
            return self._fetch_per_ticker(tickers)
        return self._fetch_broad()

    def _fetch_per_ticker(self, tickers: List[str]) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        for raw_ticker in tickers:
            clean = self.clean_ticker(raw_ticker)
            if not clean:
                continue
            query = quote_plus(f"{clean} stock")
            url = self.SEARCH_URL.format(q=query)
            entries = self.fetch_rss(url)
            for entry in entries[: self.MAX_PER_TICKER]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title:
                    continue
                items.append(ScrapedItem(
                    source=self.name,
                    kind=self.kind,
                    title=title,
                    url=link,
                    ticker=clean,
                    ts=self.parse_rss_date(entry),
                    summary=(entry.get("summary") or "")[:500],
                    meta={"query": clean},
                ))
        return items

    def _fetch_broad(self) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        for query in self.FALLBACK_QUERIES:
            url = self.SEARCH_URL.format(q=quote_plus(query))
            entries = self.fetch_rss(url)
            for entry in entries[: self.MAX_PER_TICKER]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title:
                    continue
                items.append(ScrapedItem(
                    source=self.name,
                    kind=self.kind,
                    title=title,
                    url=link,
                    ticker=None,
                    ts=self.parse_rss_date(entry),
                    summary=(entry.get("summary") or "")[:500],
                    meta={"query": query, "mode": "broad"},
                ))
        return items
