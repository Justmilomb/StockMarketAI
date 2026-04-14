"""Bloomberg scraper — routed through Google News.

Bloomberg gates its RSS behind a paywall / heavy rate limit, and
anything that returns 403 consistently would just clog up health
metrics. What *does* work reliably is Google News with a
``site:bloomberg.com`` filter — same content, zero auth, same lenient
Google News rate budget.
"""
from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote_plus

from core.scrapers.base import ScrapedItem, ScraperBase


class BloombergScraper(ScraperBase):
    name = "bloomberg"
    kind = "news"

    #: Google News RSS filtered to bloomberg.com.
    FEED_URL: str = (
        "https://news.google.com/rss/search"
        "?q=site%3Abloomberg.com+{q}&hl=en-US&gl=US&ceid=US:en"
    )

    MAX_PER_QUERY: int = 15

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        # Build a single multi-ticker query when we have tickers, else
        # fall back to a generic markets query so the feed still turns
        # up breaking macro news.
        cleaned = [self.clean_ticker(t) for t in (tickers or []) if t]
        queries: List[str]
        if cleaned:
            queries = [f"{t} stock" for t in cleaned[:5]]
        else:
            queries = ["markets"]

        items: List[ScrapedItem] = []
        for q in queries:
            url = self.FEED_URL.format(q=quote_plus(q))
            entries = self.fetch_rss(url)
            for entry in entries[: self.MAX_PER_QUERY]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title:
                    continue
                items.append(ScrapedItem(
                    source=self.name,
                    kind=self.kind,
                    title=title,
                    url=link,
                    ticker=q.split()[0] if cleaned else None,
                    ts=self.parse_rss_date(entry),
                    summary=(entry.get("summary") or "")[:500],
                    meta={"query": q},
                ))
        return items
