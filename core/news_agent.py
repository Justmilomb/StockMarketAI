from __future__ import annotations

import logging
import random
import time
import threading
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

try:
    import feedparser
except ImportError:
    feedparser = None  # type: ignore

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


@dataclass
class TickerNews:
    """News data for a single ticker."""
    ticker: str
    sentiment: float = 0.0  # -1 to +1
    summary: str = ""
    headlines: List[str] = field(default_factory=list)
    last_updated: Optional[datetime] = None
    # Enriched scraping fields
    earnings_date: Optional[str] = None
    analyst_rating: Optional[str] = None
    target_price: Optional[float] = None
    short_float: Optional[float] = None
    social_mentions: int = 0
    social_posts: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)


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

    def __init__(
        self,
        ai_client: Any,
        refresh_interval_minutes: int = 5,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ai_client = ai_client  # Duck-typed — works with ClaudeClient
        self.refresh_interval = refresh_interval_minutes * 60
        self._news_data: Dict[str, TickerNews] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._tickers: List[str] = []
        # Scraper config
        news_cfg = (config or {}).get("news", {})
        self._scrapers_enabled = bool(news_cfg.get("scrapers_enabled", True))
        self._yahoo_enabled = bool(news_cfg.get("yahoo_scrape_enabled", True))
        self._finviz_enabled = bool(news_cfg.get("finviz_enabled", True))
        self._reddit_enabled = bool(news_cfg.get("reddit_enabled", True))
        # Per-domain rate limiting
        self._domain_last_hit: Dict[str, float] = {}
        self._rate_limit_seconds = 2.0
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": random.choice(_USER_AGENTS)})

    @property
    def news_data(self) -> Dict[str, Dict[str, Any]]:
        """Return news as plain dicts for panel consumers.

        Maps TickerNews.sentiment → 'sentiment_score' to match what
        watchlist and news panels expect.
        """
        return {
            ticker: {
                "sentiment_score": tn.sentiment,
                "summary": tn.summary,
                "headlines": tn.headlines,
                "earnings_date": tn.earnings_date,
                "analyst_rating": tn.analyst_rating,
                "target_price": tn.target_price,
                "short_float": tn.short_float,
                "social_mentions": tn.social_mentions,
                "social_posts": tn.social_posts,
                "catalysts": tn.catalysts,
            }
            for ticker, tn in self._news_data.items()
        }

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
            logger.warning("Immediate fetch error: %s", e)

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
                # Store headlines immediately so the panel shows something
                if ticker not in self._news_data:
                    self._news_data[ticker] = TickerNews(
                        ticker=ticker,
                        headlines=headlines[:5],
                        last_updated=datetime.utcnow(),
                    )

        # Phase 1.5: Enhanced scraping (parallel, per ticker)
        ticker_enrichment: Dict[str, Dict[str, Any]] = {}
        if self._scrapers_enabled:
            print(f"[news_agent] Scraping enrichment for {len(tickers)} tickers")

            def scrape_one(ticker: str) -> tuple:
                return ticker, self._scrape_enrichment(ticker)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                scrape_results = list(executor.map(scrape_one, tickers))
            for ticker, enrichment in scrape_results:
                if enrichment:
                    ticker_enrichment[ticker] = enrichment
                    # Merge enrichment into existing TickerNews immediately
                    tn = self._news_data.get(ticker)
                    if tn:
                        tn.earnings_date = enrichment.get("earnings_date", tn.earnings_date)
                        tn.analyst_rating = enrichment.get("analyst_rating", tn.analyst_rating)
                        tn.target_price = enrichment.get("target_price", tn.target_price)
                        tn.short_float = enrichment.get("short_float", tn.short_float)
                        tn.social_mentions = enrichment.get("social_mentions", tn.social_mentions)
                        tn.social_posts = enrichment.get("social_posts", tn.social_posts)
                        tn.catalysts = enrichment.get("catalysts", tn.catalysts)

        # Phase 2: Batch sentiment analysis to reduce API calls
        # Skip if AI is unavailable — still show headlines without sentiment
        ai_available = getattr(self.ai_client, "available", True) if self.ai_client else False
        if not ai_available:
            print("[news_agent] AI client unavailable — showing headlines only")
            for ticker, headlines in ticker_headlines.items():
                self._news_data[ticker] = TickerNews(
                    ticker=ticker,
                    sentiment=0.0,
                    summary="AI unavailable — install Claude CLI",
                    headlines=headlines[:5],
                    last_updated=datetime.utcnow(),
                )
            return

        if ticker_headlines:
            self._batch_analyze_sentiment(ticker_headlines, ticker_enrichment)

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
            except Exception as exc:
                logger.debug("RSS fetch failed for %s: %s", url, exc)
                continue
        return headlines[:8]

    def _batch_analyze_sentiment(
        self,
        ticker_headlines: Dict[str, List[str]],
        ticker_enrichment: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Analyze sentiment for all tickers in a single Claude call."""
        if self.ai_client is None:
            return
        enrichment = ticker_enrichment or {}

        # Build a combined prompt with headlines + scraped context
        sections = []
        for ticker, headlines in ticker_headlines.items():
            hl_str = "; ".join(headlines[:3])
            parts = [f"{ticker}: Headlines: {hl_str}"]
            enr = enrichment.get(ticker, {})
            if enr.get("earnings_date"):
                parts.append(f"Earnings: {enr['earnings_date']}")
            if enr.get("analyst_rating"):
                parts.append(f"Analyst: {enr['analyst_rating']}")
            if enr.get("target_price"):
                parts.append(f"Target: ${enr['target_price']:.2f}")
            if enr.get("short_float"):
                parts.append(f"Short: {enr['short_float']:.1f}%")
            if enr.get("social_mentions", 0) > 0:
                parts.append(f"Reddit: {enr['social_mentions']} mentions")
            if enr.get("catalysts"):
                parts.append(f"Catalysts: {'; '.join(enr['catalysts'][:2])}")
            sections.append(" | ".join(parts))

        combined = "\n".join(sections)
        prompt = (
            "Analyze the sentiment of these stock news headlines for each ticker.\n"
            "Rate each from -1.0 (very bearish) to +1.0 (very bullish) "
            "and give a one-sentence summary per ticker.\n\n"
            f"{combined}\n\n"
            "Respond strictly as JSON object where keys are tickers:\n"
            '{"AAPL": {"sentiment": 0.5, "summary": "..."}, "MSFT": {"sentiment": -0.2, "summary": "..."}, ...}'
        )

        scored_tickers: set = set()
        try:
            text = self.ai_client._call(prompt, task_type="simple")
            if not text:
                logger.warning("[news_agent] Claude returned empty for batch sentiment")
            else:
                obj = self.ai_client._parse_json(text)
                if isinstance(obj, dict):
                    for ticker, headlines in ticker_headlines.items():
                        data = obj.get(ticker, {})
                        if not isinstance(data, dict):
                            continue
                        sentiment = max(-1.0, min(1.0, float(data.get("sentiment", 0.0))))
                        summary = str(data.get("summary", "No summary"))
                        enr = enrichment.get(ticker, {})
                        self._news_data[ticker] = TickerNews(
                            ticker=ticker,
                            sentiment=sentiment,
                            summary=summary,
                            headlines=headlines[:5],
                            last_updated=datetime.utcnow(),
                            earnings_date=enr.get("earnings_date"),
                            analyst_rating=enr.get("analyst_rating"),
                            target_price=enr.get("target_price"),
                            short_float=enr.get("short_float"),
                            social_mentions=enr.get("social_mentions", 0),
                            social_posts=enr.get("social_posts", []),
                            catalysts=enr.get("catalysts", []),
                        )
                        scored_tickers.add(ticker)
                else:
                    logger.warning("[news_agent] Batch sentiment response was not JSON dict")
        except Exception as e:
            logger.warning("[news_agent] Batch sentiment error: %s", e)

        # Fallback: try individual calls for tickers the batch missed
        missed = set(ticker_headlines.keys()) - scored_tickers
        for ticker in missed:
            headlines = ticker_headlines[ticker]
            enr = enrichment.get(ticker, {})
            try:
                result = self.ai_client.analyze_news(ticker, headlines)
                self._news_data[ticker] = TickerNews(
                    ticker=ticker,
                    sentiment=result.get("sentiment", 0.0),
                    summary=result.get("summary", "sentiment pending"),
                    headlines=headlines[:5],
                    last_updated=datetime.utcnow(),
                    earnings_date=enr.get("earnings_date"),
                    analyst_rating=enr.get("analyst_rating"),
                    target_price=enr.get("target_price"),
                    short_float=enr.get("short_float"),
                    social_mentions=enr.get("social_mentions", 0),
                    social_posts=enr.get("social_posts", []),
                    catalysts=enr.get("catalysts", []),
                )
            except Exception as exc:
                logger.debug("Individual sentiment failed for %s: %s", ticker, exc)
                self._news_data[ticker] = TickerNews(
                    ticker=ticker,
                    sentiment=0.0,
                    summary="sentiment analysis failed",
                    headlines=headlines[:5],
                    last_updated=datetime.utcnow(),
                    earnings_date=enr.get("earnings_date"),
                    analyst_rating=enr.get("analyst_rating"),
                    target_price=enr.get("target_price"),
                    short_float=enr.get("short_float"),
                    social_mentions=enr.get("social_mentions", 0),
                    social_posts=enr.get("social_posts", []),
                    catalysts=enr.get("catalysts", []),
                )

    def _analyze_sentiment(self, ticker: str, headlines: List[str]) -> Dict[str, Any]:
        if self.ai_client is None:
            return {"sentiment": 0.0, "summary": "No AI client available."}
        return self.ai_client.analyze_news(ticker, headlines)

    # ── Rate-limited HTTP helper ──────────────────────────────────────

    def _rate_limited_get(self, url: str, **kwargs: Any) -> Optional[requests.Response]:
        """GET with per-domain rate limiting and retry."""
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        now = time.time()
        last = self._domain_last_hit.get(domain, 0.0)
        wait = self._rate_limit_seconds - (now - last)
        if wait > 0:
            time.sleep(wait)

        self._session.headers["User-Agent"] = random.choice(_USER_AGENTS)
        for attempt in range(3):
            try:
                resp = self._session.get(url, timeout=10, **kwargs)
                self._domain_last_hit[domain] = time.time()
                if resp.status_code in (429, 503):
                    time.sleep(2 ** (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                logger.debug("HTTP %s attempt %d failed: %s", url, attempt, exc)
                if attempt < 2:
                    time.sleep(2 ** attempt)
        return None

    # ── Yahoo Finance scraper ─────────────────────────────────────────

    def _scrape_yahoo_finance(self, ticker: str) -> Dict[str, Any]:
        """Scrape earnings date, analyst rating, and target price from Yahoo."""
        clean = ticker.split("_")[0]  # AAPL_US_EQ → AAPL
        result: Dict[str, Any] = {}
        try:
            resp = self._rate_limited_get(
                f"https://finance.yahoo.com/quote/{clean}/",
            )
            if not resp:
                return result
            tree = lxml_html.fromstring(resp.text)

            # Earnings date — look for the "Earnings Date" row
            for el in tree.xpath("//*[contains(text(), 'Earnings Date')]"):
                parent = el.getparent()
                if parent is not None:
                    sibling_text = parent.text_content()
                    # Extract date after "Earnings Date"
                    parts = sibling_text.split("Earnings Date")
                    if len(parts) > 1:
                        date_text = parts[1].strip().split("\n")[0].strip()
                        if date_text:
                            result["earnings_date"] = date_text[:30]
                    break

            # Target price and analyst rating from analysis page
            resp2 = self._rate_limited_get(
                f"https://finance.yahoo.com/quote/{clean}/analysis/",
            )
            if resp2:
                tree2 = lxml_html.fromstring(resp2.text)
                for el in tree2.xpath("//*[contains(text(), 'Recommendation')]"):
                    parent = el.getparent()
                    if parent is not None:
                        text = parent.text_content()
                        for label in ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"):
                            if label.lower() in text.lower():
                                result["analyst_rating"] = label
                                break
                        break
        except Exception as exc:
            logger.debug("Yahoo scrape failed for %s: %s", ticker, exc)
        return result

    # ── Finviz scraper ────────────────────────────────────────────────

    def _scrape_finviz(self, ticker: str) -> Dict[str, Any]:
        """Scrape analyst actions, short float, target price from Finviz."""
        clean = ticker.split("_")[0]
        result: Dict[str, Any] = {}
        try:
            resp = self._rate_limited_get(
                f"https://finviz.com/quote.ashx?t={clean}&p=d",
            )
            if not resp:
                return result
            tree = lxml_html.fromstring(resp.text)

            # Snapshot table — key metrics
            for row in tree.xpath("//table[contains(@class,'snapshot-table')]//tr/td"):
                label = row.text_content().strip()
                sibling = row.getnext()
                if sibling is None:
                    continue
                value = sibling.text_content().strip()
                if label == "Target Price" and value not in ("-", ""):
                    try:
                        result["target_price"] = float(value)
                    except ValueError:
                        pass
                elif label == "Short Float" and value not in ("-", ""):
                    try:
                        result["short_float"] = float(value.replace("%", ""))
                    except ValueError:
                        pass
                elif label == "Recom" and value not in ("-", ""):
                    # Finviz 1-5 scale: 1=Strong Buy, 5=Strong Sell
                    try:
                        rec = float(value)
                        if rec <= 1.5:
                            result["analyst_rating"] = "Strong Buy"
                        elif rec <= 2.5:
                            result["analyst_rating"] = "Buy"
                        elif rec <= 3.5:
                            result["analyst_rating"] = "Hold"
                        elif rec <= 4.5:
                            result["analyst_rating"] = "Sell"
                        else:
                            result["analyst_rating"] = "Strong Sell"
                    except ValueError:
                        pass

            # News table — extract catalyst headlines (upgrades/downgrades/insider)
            catalysts: List[str] = []
            for link in tree.xpath("//table[@id='news-table']//a"):
                title = link.text_content().strip()
                title_lower = title.lower()
                if any(kw in title_lower for kw in (
                    "upgrade", "downgrade", "initiate", "insider",
                    "buy", "sell", "target", "rating",
                )):
                    catalysts.append(title[:120])
                if len(catalysts) >= 5:
                    break
            if catalysts:
                result["catalysts"] = catalysts
        except Exception as exc:
            logger.debug("Finviz scrape failed for %s: %s", ticker, exc)
        return result

    # ── Reddit scraper ────────────────────────────────────────────────

    def _scrape_reddit(self, ticker: str) -> Dict[str, Any]:
        """Scrape mention count and post titles from Reddit (no auth)."""
        clean = ticker.split("_")[0]
        result: Dict[str, Any] = {"social_mentions": 0, "social_posts": []}
        subreddits = ["wallstreetbets", "stocks"]
        for sub in subreddits:
            try:
                resp = self._rate_limited_get(
                    f"https://old.reddit.com/r/{sub}/search.json",
                    params={"q": clean, "sort": "new", "t": "week", "limit": "10", "restrict_sr": "on"},
                )
                if not resp:
                    continue
                data = resp.json()
                posts = data.get("data", {}).get("children", [])
                result["social_mentions"] += len(posts)
                for post in posts:
                    title = post.get("data", {}).get("title", "")
                    if title and title not in result["social_posts"]:
                        result["social_posts"].append(title[:120])
            except Exception as exc:
                logger.debug("Reddit scrape failed for %s in r/%s: %s", ticker, sub, exc)
        result["social_posts"] = result["social_posts"][:8]
        return result

    # ── Scraper orchestration ─────────────────────────────────────────

    def _scrape_enrichment(self, ticker: str) -> Dict[str, Any]:
        """Run all enabled scrapers for a single ticker, merge results."""
        merged: Dict[str, Any] = {}
        if self._yahoo_enabled:
            merged.update(self._scrape_yahoo_finance(ticker))
        if self._finviz_enabled:
            finviz = self._scrape_finviz(ticker)
            # Finviz analyst_rating wins over Yahoo if both present
            for k, v in finviz.items():
                if k not in merged or merged[k] is None:
                    merged[k] = v
                elif k == "analyst_rating":
                    merged[k] = v  # Finviz is more reliable
                elif k == "catalysts":
                    merged[k] = list(merged.get(k, [])) + list(v)
        if self._reddit_enabled:
            merged.update(self._scrape_reddit(ticker))
        return merged

    # ── Market buzz (watchlist-independent) ───────────────────────────

    def get_market_buzz(self) -> Dict[str, Any]:
        """Fetch trending tickers from Reddit — independent of watchlist.

        Returns {"trending": ["TICKER", ...], "top_posts": ["title", ...]}.
        """
        result: Dict[str, Any] = {"trending": [], "top_posts": []}
        if not self._scrapers_enabled or not self._reddit_enabled:
            return result
        try:
            for sub in ("wallstreetbets", "stocks"):
                resp = self._rate_limited_get(
                    f"https://old.reddit.com/r/{sub}/hot.json",
                    params={"limit": "25"},
                )
                if not resp:
                    continue
                posts = resp.json().get("data", {}).get("children", [])
                for post in posts:
                    title = post.get("data", {}).get("title", "")
                    if title:
                        result["top_posts"].append(title[:120])
                        # Extract potential tickers (1-5 uppercase letters)
                        import re
                        for match in re.findall(r"\b[A-Z]{2,5}\b", title):
                            if match not in ("DD", "CEO", "IPO", "SEC", "FDA", "EU",
                                             "ATH", "YOLO", "HODL", "EPS", "ETF", "WSB",
                                             "IMO", "LOL", "WTF", "OMG", "FYI", "USA",
                                             "NYSE", "THE", "AND", "FOR", "NOT", "BUT",
                                             "THIS", "THAT", "WITH", "FROM", "JUST",
                                             "HAVE", "BEEN", "WILL", "WHAT", "YOUR",
                                             "WHEN", "THEY", "THAN", "INTO", "OVER",
                                             "ALL", "ARE", "HAS", "WAS", "CAN", "HOW",
                                             "NEW", "NOW", "OUT", "OUR", "WAR", "BIG",
                                             "MAY", "DAY", "DID", "GOT", "PUT", "BUY",
                                             "RUN", "RED", "TOP", "UP", "GO", "NO",
                                             "PEACE", "TALKS", "DEAL", "NEWS", "FREE"):
                                result["trending"].append(match)
        except Exception as exc:
            logger.debug("Market buzz fetch failed: %s", exc)
        # Deduplicate and rank by frequency
        from collections import Counter
        counts = Counter(result["trending"])
        result["trending"] = [t for t, _ in counts.most_common(15)]
        result["top_posts"] = result["top_posts"][:10]
        return result

