"""YouTube scraper — channel RSS feeds (no auth, no API key).

YouTube publishes an RSS feed per channel at:

    https://www.youtube.com/feeds/videos.xml?channel_id={id}

We poll a curated set of high-signal finance channels and return each
recent video as a news-kind ``ScrapedItem``. The channel catalogue is
hardcoded because it's small, stable, and lets the agent trust
sources by name.
"""
from __future__ import annotations

from typing import List, Optional

from core.scrapers.base import ScrapedItem, ScraperBase


#: (channel_name, channel_id) — curated finance YouTube sources.
#: These are stable channel IDs, not usernames. The feed still works
#: even if the channel rebrands.
FINANCE_CHANNELS: List[tuple[str, str]] = [
    ("Bloomberg Television", "UCIALMKvObZNtJ6AmdCLP7Lg"),
    ("CNBC Television", "UCrp_UI8XtuYfpiqluWLD7Lw"),
    ("Yahoo Finance", "UCEAZeUIeJs0IjQiqTCdVSIg"),
    ("Benzinga", "UC1IK5OtVK9sPIpnvvKTyJrA"),
]


class YouTubeScraper(ScraperBase):
    name = "youtube"
    kind = "news"

    #: Most recent videos per channel.
    MAX_PER_CHANNEL: int = 5

    FEED_TEMPLATE: str = "https://www.youtube.com/feeds/videos.xml?channel_id={id}"

    def fetch(
        self,
        tickers: Optional[List[str]] = None,
        since_minutes: int = 60,
    ) -> List[ScrapedItem]:
        items: List[ScrapedItem] = []
        cleaned = [self.clean_ticker(t) for t in (tickers or []) if t]

        for channel_name, channel_id in FINANCE_CHANNELS:
            url = self.FEED_TEMPLATE.format(id=channel_id)
            entries = self.fetch_rss(url)
            for entry in entries[: self.MAX_PER_CHANNEL]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title:
                    continue

                # Tag the first watchlist ticker that appears in the
                # title (case-insensitive whole-word) so ticker
                # searches pick up the match.
                matched_ticker: Optional[str] = None
                for t in cleaned:
                    if t and t in title.upper():
                        matched_ticker = t
                        break

                items.append(ScrapedItem(
                    source=self.name,
                    kind=self.kind,
                    title=title,
                    url=link,
                    ticker=matched_ticker,
                    ts=self.parse_rss_date(entry),
                    summary=(entry.get("summary") or "")[:500],
                    meta={"channel": channel_name},
                ))
        return items
