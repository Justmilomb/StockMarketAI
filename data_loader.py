import os
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yfinance as yf
import concurrent.futures


DEFAULT_DATA_DIR = Path("data")


def _clean_ticker(ticker: str) -> str:
    """
    Remove Trading 212 internal suffixes like _US_EQ, _GB_EQ, etc.
    that yfinance cannot resolve.
    """
    suffixes = [
        "_US_EQ", "_GB_EQ", "_UK_EQ", "_DE_EQ", "_FR_EQ", "_IL_EQ",
        "_UK", "_DE", "_FR", "_IL", "_NL_EQ", "_ES_EQ", "_IT_EQ",
        "_CH_EQ", "_SE_EQ", "_NO_EQ", "_DK_EQ", "_FI_EQ",
        "_EQ",  # catch-all for remaining _EQ suffixes — MUST be last
    ]
    cleaned = ticker.upper().strip()
    for s in suffixes:
        if cleaned.endswith(s):
            cleaned = cleaned[: -len(s)]
            break
    return cleaned


def _get_cache_path(ticker: str, start_date: str, end_date: str, data_dir: Path) -> Path:
    """
    Build a simple cache file path for a given ticker and date range.
    """
    safe_ticker = ticker.replace("/", "_").upper()
    filename = f"{safe_ticker}_{start_date}_{end_date}.csv"
    return data_dir / filename


def fetch_ticker_data(
    ticker: str,
    start_date: str,
    end_date: str,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Download daily OHLCV data for a single ticker using yfinance, with basic CSV caching.

    Returns a DataFrame indexed by date with at least:
    - Open, High, Low, Close, Volume
    """
    # Clean the ticker for yfinance
    yf_ticker = _clean_ticker(ticker)

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_path = _get_cache_path(yf_ticker, start_date, end_date, data_dir)

    if use_cache and cache_path.exists():
        try:
            # Be tolerant of different CSV formats that may have been written earlier.
            df = pd.read_csv(cache_path)
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                df = df.set_index("Date")
            else:
                # Assume the first column is the date index if no explicit Date column exists.
                first_col = df.columns[0]
                df[first_col] = pd.to_datetime(df[first_col], errors="coerce")
                df = df.set_index(first_col)
            return df
        except Exception:
            pass # Fallback to download

    try:
        df = yf.download(yf_ticker, start=start_date, end=end_date, auto_adjust=False, progress=False)
        if df.empty:
            print(f"[data_loader] No data returned for {yf_ticker} ({ticker})")
            return pd.DataFrame()

        # Ensure expected columns exist
        needed_cols = ["Open", "High", "Low", "Close", "Volume"]
        # Handle MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        missing = [c for c in needed_cols if c not in df.columns]
        if missing:
            print(f"[data_loader] Missing columns {missing} for {yf_ticker}")
            return pd.DataFrame()

        # Normalize index/column names
        df = df[needed_cols].copy()
        df.index.name = "Date"

        df.to_csv(cache_path)
        return df
    except Exception as e:
        print(f"[data_loader] Error fetching {yf_ticker}: {e}")
        return pd.DataFrame()


def fetch_universe_data(
    tickers: List[str],
    start_date: str,
    end_date: str,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    use_cache: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Fetch data for a list of tickers in parallel and return a mapping ticker -> DataFrame.
    """
    universe_data: Dict[str, pd.DataFrame] = {}
    
    def fetch_one(ticker: str):
        return ticker, fetch_ticker_data(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            data_dir=data_dir,
            use_cache=use_cache,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_one, tickers))

    for ticker, df in results:
        if not df.empty:
            universe_data[ticker] = df
    return universe_data


def fetch_live_prices(tickers: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Fetch near real-time prices and calculate day change percentage.
    Returns: { "AAPL": {"price": 150.0, "change_pct": 1.5}, ... }
    """
    live_data: Dict[str, Dict[str, float]] = {}
    if not tickers:
        return live_data

    # Map input tickers to cleaned yfinance tickers
    ticker_map = {t: _clean_ticker(t) for t in tickers}
    yf_tickers = list(set(ticker_map.values()))

    # Download recent 5 days to get current price and previous close
    try:
        # If a ticker is delisted, yfinance might raise an error for the whole batch or return empty.
        # We try to get as much as we can.
        df = yf.download(yf_tickers, period="5d", auto_adjust=False, progress=False, group_by='column')
        
        # yfinance returns a DataFrame with MultiIndex columns (Attribute, Ticker) if len(yf_tickers) > 1
        # If len(yf_tickers) == 1, it might return a simple Index if group_by='column' (default)
        
        for original_ticker, cleaned_ticker in ticker_map.items():
            try:
                if len(yf_tickers) > 1:
                    # Access Close attribute, then specific ticker
                    if "Close" in df.columns.levels[0] and cleaned_ticker in df["Close"].columns:
                        ticker_closes = df["Close"][cleaned_ticker].dropna()
                    else:
                        ticker_closes = pd.Series()
                else:
                    # Single ticker or empty matches
                    if "Close" in df.columns:
                        ticker_closes = df["Close"].dropna()
                    else:
                        ticker_closes = pd.Series()
                
                if len(ticker_closes) >= 2:
                    current = float(ticker_closes.iloc[-1])
                    prev_close = float(ticker_closes.iloc[-2])
                    change_pct = ((current - prev_close) / prev_close) * 100.0
                elif len(ticker_closes) == 1:
                    current = float(ticker_closes.iloc[-1])
                    change_pct = 0.0
                else:
                    current = 0.0
                    change_pct = 0.0
                    
                live_data[original_ticker] = {
                    "price": current,
                    "change_pct": change_pct
                }
            except Exception:
                live_data[original_ticker] = {"price": 0.0, "change_pct": 0.0}
    except Exception as e:
        print(f"[data_loader] Error fetching live prices: {e}")
        for t in tickers:
            live_data[t] = {"price": 0.0, "change_pct": 0.0}

    return live_data

