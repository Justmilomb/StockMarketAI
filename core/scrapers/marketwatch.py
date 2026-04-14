"""MarketWatch RSS — market-wide headline feed.

MarketWatch's top-stories and market-pulse RSS feeds are free, no
auth, and refresh every few minutes. These are *market-wide* not
ticker-specific, so we tag items whose titles mention watchlist
tickers so ticker searches still pick up matches.
"""
from __future__ import annotations

import re
from typing import List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


class MarketWatchScraper(ScraperBase):
    name = "marketwatch"
    kind = "news"

    FEED_URLS: List[str] = [
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",
    ]

    MAX_PER_FEED: int = 20

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        cleaned = [self.clean_ticker(t) for t in (tickers or []) if t]

        items: List[ScrapedItem] = []
        for url in self.FEED_URLS:
            entries = self.fetch_rss(url)
            for entry in entries[: self.MAX_PER_FEED]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title:
                    continue

                matched: Optional[str] = None
                for t in cleaned:
                    if t and re.search(rf"\b{re.escape(t)}\b", title, re.IGNORECASE):
                        matched = t
                        break

                items.append(ScrapedItem(
                    source=self.name,
                    kind=self.kind,
                    title=title,
                    url=link,
                    ticker=matched,
                    ts=self.parse_rss_date(entry),
                    summary=(entry.get("summary") or "")[:500],
                ))
        return items
