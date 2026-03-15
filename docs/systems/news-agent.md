# News Agent

## Goal
Background agent that periodically fetches news headlines for watchlisted tickers via RSS feeds and uses Gemini to score sentiment.

## Implementation
Runs on a daemon thread with configurable refresh interval (default 5 min). Fetches from Google News RSS and Yahoo Finance RSS. Headlines are deduplicated and capped at 15 per ticker. Sentiment scored by `gemini_client.analyze_news()` returning -1.0 to +1.0. Results stored as `TickerNews` dataclass instances.

## Key Code
```python
@dataclass
class TickerNews:
    ticker: str
    sentiment: float  # -1 to +1
    summary: str
    headlines: List[str]

class NewsAgent:
    def start(self) -> None
    def fetch_now(self) -> None
    def update_tickers(tickers) -> None
```

## Notes
- Requires `feedparser` (optional import, degrades gracefully)
- Daemon thread — no cleanup on crash
- `news_data` property returns a copy to prevent mutation
- Sentiment of 0.0 if Gemini client unavailable
