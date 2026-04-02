# News Agent

## Goal
Background agent that periodically fetches news headlines for watchlisted tickers via RSS feeds and uses Claude to score sentiment.

## Implementation
Runs on a daemon thread with configurable refresh interval (default 5 min). Fetches from Google News RSS and Yahoo Finance RSS in parallel (up to 10 concurrent threads). Headlines are capped at 8 per ticker per source. Sentiment is scored via a batched Claude call — all tickers in a single prompt — reducing API calls. Falls back to per-ticker `claude_client.analyze_news()` calls if the batch fails. Results stored as `TickerNews` dataclass instances.

## Key Code
```python
@dataclass
class TickerNews:
    ticker: str
    sentiment: float  # -1 to +1
    summary: str
    headlines: List[str]
    last_updated: Optional[datetime]

class NewsAgent:
    def start(self) -> None
    def stop(self) -> None
    def fetch_now(self) -> None
    def update_tickers(tickers: List[str]) -> None
```

## Notes
- Requires `feedparser` (optional import, degrades gracefully — returns empty headlines)
- Daemon thread — no cleanup on crash
- `news_data` property returns a copy to prevent mutation
- Sentiment of 0.0 if Claude client unavailable
- Batched sentiment analysis sends all tickers in one Claude call; falls back to per-ticker calls on JSON parse errors
