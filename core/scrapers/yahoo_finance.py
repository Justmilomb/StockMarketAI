"""Yahoo Finance RSS — per-ticker headline feed.

Yahoo Finance publishes a free RSS feed per ticker with no auth:

    https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US

Content is shallow (title + link + published date) but refresh is
fast and the rate limit is generous. We fetch per ticker in the
caller's watchlist.
"""
from __future__ import annotations

from typing import List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class YahooFinanceScraper(ScraperBase):
    name = "yahoo_finance"
    kind = "news"

    URL_TEMPLATE: str = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        "?s={ticker}&region=US&lang=en-US"
    )

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
            url = self.URL_TEMPLATE.format(ticker=clean)
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
                ))
        return items
