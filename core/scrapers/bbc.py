"""BBC Business News scraper.

BBC publishes a simple business RSS feed with no auth and generous
rate limits. It's market-wide rather than ticker-specific — we still
tag ticker matches in the title so the tool bus can filter downstream.
"""
from __future__ import annotations

import re
from typing import List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class BBCScraper(ScraperBase):
    name = "bbc"
    kind = "news"

    FEED_URL: str = "https://feeds.bbci.co.uk/news/business/rss.xml"

    #: Maximum items to return per call — the feed is ~30 items.
    MAX_ITEMS: int = 30

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        entries = self.fetch_rss(self.FEED_URL)
        if not entries:
            return []

        cleaned = [self.clean_ticker(t) for t in (tickers or []) if t]

        items: List[ScrapedItem] = []
        for entry in entries[: self.MAX_ITEMS]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title:
                continue

            matched_ticker = _match_ticker(title, cleaned)
            items.append(ScrapedItem(
                source=self.name,
                kind=self.kind,
                title=title,
                url=link,
                ticker=matched_ticker,
                ts=self.parse_rss_date(entry),
                summary=(entry.get("summary") or "")[:500],
            ))
        return items


def _match_ticker(title: str, watchlist: List[str]) -> Optional[str]:
    """Return the first watchlist ticker whose symbol appears in *title*."""
    if not watchlist:
        return None
    # Word-boundary match so "HOOD" doesn't match "brotherhood".
    for ticker in watchlist:
        if re.search(rf"\b{re.escape(ticker)}\b", title, re.IGNORECASE):
            return ticker
    return None
