# Features

## Goal
Engineers technical indicator features from raw OHLCV data and creates the binary classification target (will tomorrow's close be higher?).

## Implementation
Computes 10 features per ticker-date: open, prev_close, ret_1d/5d/10d, vol_5d, ma_5d/10d/30d, rsi_14d. RSI uses standard gain/loss rolling average method. Target is `(close.shift(-1) > close).astype(int)`. NaN rows from rolling windows are dropped. Training dataset concatenates all tickers sorted by date.

## Key Code
```python
FEATURE_COLUMNS = ["open", "prev_close", "ret_1d", "ret_5d", "ret_10d",
                   "vol_5d", "ma_5d", "ma_10d", "ma_30d", "rsi_14d"]
def build_universe_dataset(universe_data) -> (X, y, meta)
def latest_feature_rows_per_ticker(universe_data) -> (features_df, meta_df)
```

## Notes
- Column names normalised to lowercase on ingestion
- Non-numeric rows coerced via `pd.to_numeric(errors="coerce")`
- Latest row kept even if target is NaN (needed for inference)
- 30-day MA window means first ~30 rows per ticker are lost
