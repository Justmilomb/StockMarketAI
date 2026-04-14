"""Google News scraper — primary ticker-specific headline feed.

Google News serves free RSS per search query with no auth and very
lenient rate limits. We hit it per ticker in the caller-supplied
watchlist. If no tickers are given we skip cleanly (returns ``[]``).
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

    #: Per-ticker cap on the number of items we keep. Headlines past
    #: the top 10 are rarely load-bearing.
    MAX_PER_TICKER: int = 10

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
