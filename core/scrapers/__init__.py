"""Free, rate-limited scrapers for news + social signal.

Phase 5 of the agent-native rebuild. Every scraper inherits from
``ScraperBase``, returns ``list[ScrapedItem]`` (or an empty list on
failure), and never raises. The agent tool bus reads cached items from
``core.database`` via ``scraper_items``; a background worker refreshes
the cache on a schedule.

Public API:
    from core.scrapers import SCRAPERS, ScraperBase, ScrapedItem
"""
from __future__ import annotations

from core.scrapers.base import ScrapedItem, ScraperBase
from core.scrapers.bbc import BBCScraper
from core.scrapers.bloomberg import BloombergScraper
from core.scrapers.google_news import GoogleNewsScraper
from core.scrapers.marketwatch import MarketWatchScraper
from core.scrapers.reddit import RedditScraper
from core.scrapers.stocktwits import StockTwitsScraper
from core.scrapers.x_via_gnews import XViaGoogleNewsScraper
from core.scrapers.yahoo_finance import YahooFinanceScraper
from core.scrapers.youtube import YouTubeScraper

#: Every scraper wired into the tool bus. The background worker iterates
#: this list; tools read the cached items the worker writes to sqlite.
SCRAPERS: list[ScraperBase] = [
    GoogleNewsScraper(),
    YahooFinanceScraper(),
    BBCScraper(),
    BloombergScraper(),
    MarketWatchScraper(),
    YouTubeScraper(),
    StockTwitsScraper(),
    RedditScraper(),
    XViaGoogleNewsScraper(),
]

__all__ = [
    "SCRAPERS",
    "ScrapedItem",
    "ScraperBase",
    "BBCScraper",
    "BloombergScraper",
    "GoogleNewsScraper",
    "MarketWatchScraper",
    "RedditScraper",
    "StockTwitsScraper",
    "XViaGoogleNewsScraper",
    "YahooFinanceScraper",
    "YouTubeScraper",
]
