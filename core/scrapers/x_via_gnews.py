"""x.com (Twitter) scraper via Google News filter.

Direct x.com scraping needs auth + JS execution and will break in
days. Google News, however, happily indexes tweets from x.com as news
entries and exposes them via RSS with no auth. We search each ticker
through Google News with a ``site:x.com`` / ``site:twitter.com``
filter and return the matching entries.

Results are tagged ``source='x'`` so consumers can treat them as
social buzz rather than news.
"""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote_plus

from core.scrapers.base import ScrapedItem, ScraperBase


class XViaGoogleNewsScraper(ScraperBase):
    name = "x"
    kind = "social"

    FEED_URL: str = (
        "https://news.google.com/rss/search"
        "?q=(site%3Ax.com+OR+site%3Atwitter.com)+{q}"
        "&hl=en-US&gl=US&ceid=US:en"
    )

    MAX_PER_TICKER: int = 15

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
            query = quote_plus(f"${clean}")
            url = self.FEED_URL.format(q=query)
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
                    meta={"via": "google_news"},
                ))
        return items
