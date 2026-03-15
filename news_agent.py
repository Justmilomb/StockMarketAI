from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import feedparser
except ImportError:
    feedparser = None  # type: ignore


@dataclass
class TickerNews:
    """News data for a single ticker."""
    ticker: str
    sentiment: float = 0.0  # -1 to +1
    summary: str = ""
    headlines: List[str] = field(default_factory=list)
    last_updated: Optional[datetime] = None


class NewsAgent:
    """
    Background agent that periodically fetches news for watchlisted tickers
    via RSS feeds and uses Gemini to score sentiment.
    """

    RSS_SOURCES = [
        "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    ]

    def __init__(self, gemini_client: Any, refresh_interval_minutes: int = 5) -> None:
        self.gemini_client = gemini_client
        self.refresh_interval = refresh_interval_minutes * 60
        self._news_data: Dict[str, TickerNews] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._tickers: List[str] = []

    @property
    def news_data(self) -> Dict[str, TickerNews]:
        return self._news_data.copy()

    def update_tickers(self, tickers: List[str]) -> None:
        self._tickers = list(tickers)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._fetch_all()
            except Exception as e:
                print(f"[news_agent] Error in fetch loop: {e}")
            time.sleep(self.refresh_interval)

    def _fetch_all(self) -> None:
        for ticker in self._tickers:
            try:
                # Clean ticker for news searching
                from data_loader import _clean_ticker
                search_ticker = _clean_ticker(ticker)
                
                headlines = self._fetch_headlines(search_ticker)
                if headlines:
                    sentiment_data = self._analyze_sentiment(ticker, headlines)
                    self._news_data[ticker] = TickerNews(
                        ticker=ticker,
                        sentiment=sentiment_data.get("sentiment", 0.0),
                        summary=sentiment_data.get("summary", ""),
                        headlines=headlines[:5],
                        last_updated=datetime.utcnow(),
                    )
            except Exception as e:
                print(f"[news_agent] Error processing {ticker}: {e}")

    def _fetch_headlines(self, ticker: str) -> List[str]:
        if feedparser is None:
            return []

        headlines: List[str] = []
        for source_template in self.RSS_SOURCES:
            try:
                url = source_template.format(ticker=ticker)
                feed = feedparser.parse(url)
                for entry in feed.entries[:10]:
                    title = entry.get("title", "").strip()
                    if title and title not in headlines:
                        headlines.append(title)
            except Exception:
                continue
        return headlines[:5]

    def _analyze_sentiment(self, ticker: str, headlines: List[str]) -> Dict[str, Any]:
        if self.gemini_client is None:
            return {"sentiment": 0.0, "summary": "No AI client available."}
        return self.gemini_client.analyze_news(ticker, headlines)

    def fetch_now(self) -> None:
        """Force an immediate fetch (called from a worker thread)."""
        self._fetch_all()
