# NLP (FinBERT sentiment)

## FinBERT pipeline (`core/nlp/finbert.py`)

Wraps `ProsusAI/finbert` via HuggingFace `transformers.pipeline`. Lazy
singleton — the ~440 MB model only loads on first call. Thread-safe
init via a module-level lock.

Never raises. If transformers isn't installed, the model can't be
downloaded, or scoring blows up mid-batch, the module returns an empty
list and logs at INFO.

Core API:

```python
scores = score_texts([
    "Shares rallied after record earnings",
    "Regulator opens probe into accounting",
], max_texts=32)
# [{"label": "positive", "score": 0.93, "compound":  0.93},
#  {"label": "negative", "score": 0.88, "compound": -0.88}]

compound = aggregate_compound(scores)  # mean of compounds, clamped to [-1, 1]
```

`compound` converts FinBERT's three-class output to a single scalar:
`+score` for positive, `-score` for negative, `0` for neutral.

## `score_sentiment` MCP tool

Batch-score free text. Use this when the agent already has headlines or
research notes and just wants a numeric mood.

Args: `{texts: list[str]}`. Returns per-text labels + scores plus an
aggregate compound.

## `finbert_ticker_sentiment` MCP tool

Pulls recent cached social posts for *ticker* from the scraper buffer
(`db.get_scraper_items(tickers=[ticker], since_minutes=since)`) and
scores them with FinBERT.

Also extracts the existing `meta.sentiment` tag (Bullish/Bearish) that
the StockTwits scraper attaches and reports:

- `finbert_aggregate` — mean compound score across all scored posts
- `stocktwits_ratio` — `(bulls - bears) / (bulls + bears)`
- `disagreement` — `|finbert_aggregate - stocktwits_ratio|`

High `disagreement` means explicit user tags and model inference
diverge — often a sign that retail is buying on hopium while actual
news reads bearish (or vice versa).
