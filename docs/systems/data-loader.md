# Data Loader

## Goal
Downloads and caches daily OHLCV stock data from yfinance. Provides both historical data for model training and near-real-time prices for the TUI.

## Implementation
Uses `yfinance.download()` for historical data with a simple CSV caching layer keyed by `{TICKER}_{start}_{end}.csv`. Cache files are stored in `data/`. Live prices use `yf.download(period="5d")` to compute current price and day change percentage. Handles both single and multi-ticker download formats from yfinance.

## Key Code
```python
def fetch_universe_data(tickers, start_date, end_date, data_dir, use_cache) -> Dict[str, pd.DataFrame]
def fetch_live_prices(tickers) -> Dict[str, Dict[str, float]]
```

## Notes
- Cache key includes date range — changing dates creates new cache files
- yfinance returns MultiIndex columns for multi-ticker downloads
- `auto_adjust=False` to get raw OHLCV (not adjusted prices)
- Live price fallback: returns `{price: 0.0, change_pct: 0.0}` on error
