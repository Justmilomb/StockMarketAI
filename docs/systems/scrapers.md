# Scrapers

`core/scrapers/` — 24/7 background news + social feeds. A single daemon
thread cycles every 5 minutes through 10 sources, VADER-scores each
item for sentiment, writes results to `scraper_items`, and serves
them to the agent via `news_tools` and `social_tools`.

## Purpose

Phase 5 of the rebuild. The old news pipeline routed RSS through the
legacy `NewsAgent` into a sentiment committee the agent never saw
directly. The rebuild inverts that: scrapers persist raw items, and the
agent reads them on demand through typed tool calls.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ desktop/app.py  (boot)                                      │
│     └── _start_scraper_runner()                             │
│             └── ScraperRunner(db, watchlist_provider).start()│
└───────────────────────┬─────────────────────────────────────┘
                        │ threading.Thread daemon
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ core/scrapers/runner.py                                     │
│                                                             │
│   while not stop:                                           │
│     tickers = watchlist_provider()                          │
│     with ThreadPoolExecutor(max_workers=4) as pool:         │
│         futures = [pool.submit(s.safe_fetch, tickers) ...]  │
│         items = flatten(f.result() for f in futures)        │
│     items = [score_item(i) for i in items]  # VADER         │
│     db.save_scraper_items(items)                            │
│     db.purge_old_scraper_items(keep_days=7)                 │
│     wait(cadence or refresh_event)                          │
└───────────────────────┬─────────────────────────────────────┘
                        │ save → sqlite → read
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ core/agent/tools/{news_tools,social_tools}.py               │
│                                                             │
│   get_news(tickers, since_minutes) → List[dict]             │
│   get_social_buzz(ticker, since_minutes) → dict (score)    │
│   get_scraper_health() → per-source health snapshot         │
└─────────────────────────────────────────────────────────────┘
```

## Sources

| Name | Kind | Notes |
|------|------|-------|
| `google_news` | news | RSS search per ticker, up to 10 items each |
| `yahoo_finance` | news | RSS per ticker, up to 10 items each |
| `bbc` | news | Business RSS, word-boundary ticker tagging |
| `bloomberg` | news | Google News `site:bloomberg.com` filter (direct RSS gates) |
| `marketwatch` | news | Top stories + market pulse RSS, ticker tagging |
| `youtube` | news | Hardcoded finance channels via RSS (`feeds/videos.xml`) |
| `youtube_transcripts` | news | Captions from the @markets channel + 24/7 live stream, Haiku-summarised, regex-extractive fallback |
| `stocktwits` | social | Public `api.stocktwits.com` symbol streams, sentiment in meta |
| `reddit` | social | old.reddit.com JSON search for r/wsb, stocks, investing |
| `x` | social | Google News `(site:x.com OR site:twitter.com)` filter |

Instagram and Facebook are deliberately excluded — both gate too
aggressively to stay stable.

## Safety invariants

- `ScraperBase.safe_fetch()` wraps every call in try/except and updates
  `health` counters. **Scrapers never raise out to the runner.**
- Per-source rate limit: `rate_limited_get()` sleeps per-domain based on
  `rate_limit_seconds` (default 2s) and retries on 429/503 with
  exponential backoff.
- User-agent rotation from `USER_AGENTS` (5 browser strings) on every
  request.
- `ScraperHealth.is_healthy` flips to `False` after 3 consecutive
  failures; the agent can see this via `get_scraper_health()`.

## Database

Table `scraper_items` (`core/database.py`):

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `fetched_at` | TEXT | DB-side `datetime('now')` at insert |
| `source` | TEXT | `ScraperBase.name` |
| `kind` | TEXT | `"news"` or `"social"` |
| `ticker` | TEXT NULL | Normalised symbol (broker suffix stripped) |
| `title` | TEXT NOT NULL | |
| `url` | TEXT NULL | |
| `ts` | TEXT NULL | Publisher timestamp (ISO) |
| `summary` | TEXT | Up to 500 chars |
| `meta_json` | TEXT | Source-specific extras |
| `sentiment_score` | REAL NULL | VADER compound score, `[-1,+1]` |
| `sentiment_label` | TEXT NULL | `bullish` / `bearish` / `neutral` (threshold ±0.1) |

Dedupe on `UNIQUE(source, url, title)` via `INSERT OR IGNORE`. Retention
capped at 7 days (`purge_old_scraper_items`).

## Runner control

```python
class ScraperRunner(threading.Thread):
    CADENCE_FLOOR_SECONDS: int = 60
    RETENTION_DAYS: int = 7

    def start() -> None: ...             # inherited from Thread
    def stop() -> None: ...              # set stop event + wake
    def request_refresh() -> None: ...   # fire wake event, cycle now
    def get_health_report() -> dict: ... # per-source health snapshot
```

`MainWindow.closeEvent` calls `scraper_runner.stop()` before Qt quits.

## Sentiment scoring

`core/scrapers/_sentiment.py` — VADER (`vaderSentiment.SentimentIntensityAnalyzer`)
scores `title + " " + summary` on every item before save. Compound
score in `[-1,+1]` maps to a label via fixed thresholds:

- `> 0.1` → `bullish`
- `< -0.1` → `bearish`
- otherwise `neutral`

VADER is pure-Python and runs in microseconds so scaling to 100+
items per cycle costs almost nothing. Nuanced summarisation stays
on Haiku (`_transcript_summariser.py`) where the token volume is
smaller but context matters.

## Transcript source

`core/scrapers/youtube_transcripts.py` pulls captions from two
endpoints on the same channel:

- **Recent uploads on the @markets channel** — RSS discovers the 5
  newest video IDs; `YouTubeTranscriptApi.get_transcript(vid)`
  pulls the English captions; `summarise_transcript` condenses
  them to <400 chars via Haiku.
- **24/7 live stream (`iEpJwprxDdk`)** — the API returns a rolling
  caption window; the scraper keeps the last 600 seconds and
  summarises that chunk on every cycle. If the broadcaster's
  auto-captions are still lagging, the scraper skips gracefully.

A per-video in-process cache keeps the scraper from re-summarising
the same upload on each cycle. Rerunning `summarise_transcript`
also has a regex-extractive fallback (first 180 chars + detected
`$TICKER` mentions) so a missing Haiku CLI never breaks the source.

## Dependencies

- `requests` (HTTP + sessions)
- `feedparser` (lazy-imported in RSS scrapers)
- `vaderSentiment>=3.3.2` (sentiment scorer)
- `youtube-transcript-api>=0.6.2` (caption fetcher, no key / no ffmpeg)
- `core/database.py` — `save_scraper_items`, `get_scraper_items`,
  `purge_old_scraper_items`
- No PySide6 dependency — `core/` stays UI-framework agnostic so the
  same runner could be embedded in a headless daemon later.
