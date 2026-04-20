import os
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yfinance as yf
import concurrent.futures


DEFAULT_DATA_DIR = Path("data")

# ── Shared OHLCV validation ───────────────────────────────────────────

_OHLCV_COLS = ("Open", "High", "Low", "Close", "Volume")
_OHLCV_LOWER = ("open", "high", "low", "close", "volume")


def sanitise_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce OHLCV columns to numeric and drop rows with NaN Close.

    Handles both capitalised (yfinance) and lowercase (features) column names.
    Safe to call multiple times — already-numeric columns are unaffected.
    """
    # Flatten MultiIndex columns if present (yfinance sometimes returns these)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    # Deduplicate columns — keep first occurrence only
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    for col in _OHLCV_COLS + _OHLCV_LOWER:
        if col in df.columns:
            series = df[col]
            # If MultiIndex wasn't fully flattened, df[col] can be a DataFrame
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
            df[col] = pd.to_numeric(series, errors="coerce")
    close_col = "Close" if "Close" in df.columns else "close" if "close" in df.columns else None
    if close_col:
        df = df.dropna(subset=[close_col])
    return df


def _clean_ticker(ticker: str) -> str:
    """
    Remove Trading 212 internal suffixes like _US_EQ, _GB_EQ, etc.
    and convert to yfinance-compatible symbols.

    T212 uses a lowercase 'l' before _EQ for London Stock Exchange stocks
    (e.g. RRl_EQ → RR.L, BBYl_EQ → BBY.L, VUKGl_EQ → VUKG.L).
    """
    original = ticker.strip()
    # Detect London exchange: T212 uses lowercase 'l' immediately before _EQ
    is_london = original.endswith("l_EQ")

    suffixes = [
        "_US_EQ", "_GB_EQ", "_UK_EQ", "_DE_EQ", "_FR_EQ", "_IL_EQ",
        "_UK", "_DE", "_FR", "_IL", "_NL_EQ", "_ES_EQ", "_IT_EQ",
        "_CH_EQ", "_SE_EQ", "_NO_EQ", "_DK_EQ", "_FI_EQ",
        "_EQ",  # catch-all for remaining _EQ suffixes — MUST be last
    ]
    cleaned = original.upper().strip()
    for s in suffixes:
        if cleaned.endswith(s):
            cleaned = cleaned[: -len(s)]
            break

    # London stocks: the trailing 'L' (from lowercase 'l' after uppercasing)
    # is not part of the symbol — replace with yfinance '.L' suffix
    if is_london and cleaned.endswith("L") and len(cleaned) > 1:
        cleaned = cleaned[:-1] + ".L"

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

            df = sanitise_ohlcv(df)

            # Sanity check: if the cached file has suspiciously few rows
            # relative to the requested date range, discard it and re-fetch.
            from datetime import datetime as _dt
            try:
                expected_days = (_dt.strptime(end_date, "%Y-%m-%d") - _dt.strptime(start_date, "%Y-%m-%d")).days
                expected_trading_days = max(10, int(expected_days * 0.7))  # ~70% are trading days
                if len(df) >= expected_trading_days * 0.3:  # accept if ≥30% of expected
                    return df
                else:
                    print(f"[data_loader] Stale cache for {yf_ticker}: {len(df)} rows vs ~{expected_trading_days} expected — re-fetching")
                    cache_path.unlink(missing_ok=True)
            except Exception:
                return df  # Can't parse dates — trust the cache
        except Exception:
            pass  # Fallback to download

    try:
        import time as _time_mod

        # Retry with backoff — yfinance rate-limits aggressively
        df = pd.DataFrame()
        for _attempt in range(3):
            try:
                df = yf.download(yf_ticker, start=start_date, end=end_date, auto_adjust=False, progress=False, multi_level_index=False)
                if not df.empty:
                    break
            except Exception as _dl_err:
                err_str = str(_dl_err).lower()
                if "rate" in err_str or "too many" in err_str:
                    _time_mod.sleep(2 ** _attempt)  # 1s, 2s, 4s
                    continue
                raise
            _time_mod.sleep(1)

        if df.empty:
            print(f"[data_loader] No data returned for {yf_ticker} ({ticker})")
            return pd.DataFrame()

        # Ensure expected columns exist
        needed_cols = ["Open", "High", "Low", "Close", "Volume"]
        # Handle MultiIndex if present (yfinance returns ('Close','AAPL') etc.)
        if isinstance(df.columns, pd.MultiIndex):
            # Pick the level that contains OHLCV names
            for level in range(df.columns.nlevels):
                names = set(df.columns.get_level_values(level))
                if "Close" in names or "close" in names:
                    df.columns = df.columns.get_level_values(level)
                    break
            else:
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(fetch_one, tickers))

    for ticker, df in results:
        if not df.empty:
            universe_data[ticker] = sanitise_ohlcv(df)
    return universe_data


# Default anomaly threshold for fetch_live_prices. A single tick that
# diverges more than this from the previous close is treated as bad
# yfinance data and zeroed out. 20% is wider than any realistic intraday
# move for liquid names but still catches the obvious garbage (wrong
# symbol, stale pre-market prints, partial downloads).
_LIVE_PRICE_ANOMALY_THRESHOLD = 0.20


def fetch_live_prices(
    tickers: List[str],
    anomaly_threshold: float = _LIVE_PRICE_ANOMALY_THRESHOLD,
) -> Dict[str, Dict[str, float]]:
    """
    Fetch near real-time prices and calculate day change percentage.
    Returns: { "AAPL": {"price": 150.0, "change_pct": 1.5}, ... }

    If a returned tick diverges from the previous close by more than
    ``anomaly_threshold`` (fractional, e.g. 0.20 = 20%), the price is
    zeroed out and the result includes ``anomaly=True``, ``rejected_price``
    and ``reference`` keys so callers can tell a rejection apart from a
    plain "yfinance returned nothing".
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
        # Fetch each ticker individually to avoid MultiIndex issues (yfinance 1.2.0+)
        for original_ticker, cleaned_ticker in ticker_map.items():
            try:
                tdf = yf.download(
                    cleaned_ticker, period="5d", auto_adjust=False,
                    progress=False, timeout=15, multi_level_index=False,
                )
                if tdf is None or tdf.empty or "Close" not in tdf.columns:
                    live_data[original_ticker] = {"price": 0.0, "change_pct": 0.0}
                    continue

                ticker_closes = tdf["Close"].dropna()
                if len(ticker_closes) >= 2:
                    current = float(ticker_closes.iloc[-1])
                    prev_close = float(ticker_closes.iloc[-2])
                    change_pct = ((current - prev_close) / prev_close) * 100.0

                    # Anomaly guard: a single tick that moves >threshold
                    # from the prior close is almost always bad data
                    # (yfinance occasionally serves wrong-symbol or
                    # pre-market micro-prints). Zero out so the broker's
                    # "no live price" path kicks in instead of filling
                    # an order at the garbage price.
                    if prev_close > 0 and abs(current - prev_close) / prev_close > anomaly_threshold:
                        print(
                            f"[data_loader] anomaly: {cleaned_ticker} tick "
                            f"{current} vs prev close {prev_close} "
                            f"({change_pct:+.1f}%) — rejected"
                        )
                        live_data[original_ticker] = {
                            "price": 0.0,
                            "change_pct": 0.0,
                            "anomaly": True,
                            "rejected_price": current,
                            "reference": prev_close,
                        }
                        continue
                elif len(ticker_closes) == 1:
                    current = float(ticker_closes.iloc[-1])
                    change_pct = 0.0
                else:
                    current = 0.0
                    change_pct = 0.0

                live_data[original_ticker] = {
                    "price": current,
                    "change_pct": change_pct,
                }
            except Exception:
                live_data[original_ticker] = {"price": 0.0, "change_pct": 0.0}
    except Exception as e:
        print(f"[data_loader] Error fetching live prices: {e}")
        for t in tickers:
            live_data[t] = {"price": 0.0, "change_pct": 0.0}

    return live_data

