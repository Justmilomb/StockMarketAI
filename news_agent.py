from __future__ import annotations

import time
import threading
import concurrent.futures
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
    Background agent that periodically fetches news for ALL watchlisted tickers
    via RSS feeds and uses Claude to score sentiment.

    Headlines are fetched in parallel (I/O bound), then sentiment analysis
    is batched to reduce API calls.
    """

    RSS_SOURCES = [
        "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US",
    ]

    def __init__(self, ai_client: Any, refresh_interval_minutes: int = 5) -> None:
        self.ai_client = ai_client  # Duck-typed — works with ClaudeClient
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

    def fetch_now(self) -> None:
        """Immediately fetch news without waiting for the interval."""
        try:
            self._fetch_all()
        except Exception as e:
            print(f"[news_agent] Immediate fetch error: {e}")

    def _run_loop(self) -> None:
        # Fetch immediately on start, then sleep-and-repeat
        while self._running:
            try:
                self._fetch_all()
            except Exception as e:
                print(f"[news_agent] Error in fetch loop: {e}")
            if self._running:
                time.sleep(self.refresh_interval)

    def _fetch_all(self) -> None:
        from data_loader import _clean_ticker

        tickers = list(self._tickers)
        if not tickers:
            print("[news_agent] No tickers to fetch — skipping")
            return
        print(f"[news_agent] Fetching news for {len(tickers)} tickers")

        # Phase 1: Fetch ALL headlines in parallel (I/O bound, fast)
        ticker_headlines: Dict[str, List[str]] = {}

        def fetch_one(ticker: str) -> tuple:
            search_ticker = _clean_ticker(ticker)
            return ticker, self._fetch_headlines(search_ticker)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_one, tickers))

        for ticker, headlines in results:
            if headlines:
                ticker_headlines[ticker] = headlines

        # Phase 2: Batch sentiment analysis to reduce API calls
        # Instead of one call per ticker, send all tickers in one prompt
        if ticker_headlines:
            self._batch_analyze_sentiment(ticker_headlines)

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
        return headlines[:8]

    def _batch_analyze_sentiment(self, ticker_headlines: Dict[str, List[str]]) -> None:
        """Analyze sentiment for all tickers in a single Claude call."""
        if self.ai_client is None:
            return

        # Build a combined prompt for all tickers at once
        sections = []
        for ticker, headlines in ticker_headlines.items():
            hl_str = "; ".join(headlines[:5])
            sections.append(f"{ticker}: {hl_str}")

        combined = "\n".join(sections)
        prompt = (
            "Analyze the sentiment of these stock news headlines for each ticker.\n"
            "Rate each from -1.0 (very bearish) to +1.0 (very bullish) "
            "and give a one-sentence summary per ticker.\n\n"
            f"{combined}\n\n"
            "Respond strictly as JSON object where keys are tickers:\n"
            '{"AAPL": {"sentiment": 0.5, "summary": "..."}, "MSFT": {"sentiment": -0.2, "summary": "..."}, ...}'
        )

        try:
            text = self.ai_client._call(prompt)
            if not text:
                return

            obj = self.ai_client._parse_json(text)
            if not isinstance(obj, dict):
                return

            for ticker, headlines in ticker_headlines.items():
                data = obj.get(ticker, {})
                if not isinstance(data, dict):
                    continue
                sentiment = max(-1.0, min(1.0, float(data.get("sentiment", 0.0))))
                summary = str(data.get("summary", "No summary"))
                self._news_data[ticker] = TickerNews(
                    ticker=ticker,
                    sentiment=sentiment,
                    summary=summary,
                    headlines=headlines[:5],
                    last_updated=datetime.utcnow(),
                )
        except Exception as e:
            print(f"[news_agent] Batch sentiment error: {e}")
            # Fallback: try individual analysis for tickers we missed
            for ticker, headlines in ticker_headlines.items():
                if ticker not in self._news_data:
                    try:
                        result = self.ai_client.analyze_news(ticker, headlines)
                        self._news_data[ticker] = TickerNews(
                            ticker=ticker,
                            sentiment=result.get("sentiment", 0.0),
                            summary=result.get("summary", ""),
                            headlines=headlines[:5],
                            last_updated=datetime.utcnow(),
                        )
                    except Exception:
                        pass

    def _analyze_sentiment(self, ticker: str, headlines: List[str]) -> Dict[str, Any]:
        if self.ai_client is None:
            return {"sentiment": 0.0, "summary": "No AI client available."}
        return self.ai_client.analyze_news(ticker, headlines)

    def fetch_now(self) -> None:
        """Force an immediate fetch (called from a worker thread)."""
        self._fetch_all()
