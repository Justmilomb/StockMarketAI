"""MarketStack-backed intraday bar fetcher for US equities.

Provides the same OHLCV DataFrame interface as data_loader.py but fetches
minute/hour bars from MarketStack's REST API.  Non-US tickers
(e.g. London Stock Exchange) are not supported — call ``is_intraday_supported``
to check before fetching.

Data is cached aggressively to CSV to minimise API calls (10k/month on
the Basic plan).  The research tool and live terminal both read from cache
when available.

NOTE: Intraday trading is dormant for now — the code is ready but not
activated in the live terminal.  The research tool can use it to train
intraday profiles when the user is ready.
"""
from __future__ import annotations

import logging
import os
import time
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from data_loader import _clean_ticker, sanitise_ohlcv

logger = logging.getLogger(__name__)

DEFAULT_INTRADAY_DIR = Path("data") / "intraday"

# MarketStack interval string → bars per 6.5-hour US trading day
INTERVAL_BARS_PER_DAY = {
    "1min": 390,
    "5min": 78,
    "15min": 26,
    "30min": 13,
    "1hour": 7,
}

# Mapping from our internal names to MarketStack API interval params
_INTERVAL_API_MAP = {
    "1Min": "1min",
    "5Min": "5min",
    "15Min": "15min",
    "30Min": "30min",
    "1Hour": "1hour",
    # Also accept the MarketStack native format
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "30min": "30min",
    "1hour": "1hour",
}

# T212 suffixes that indicate non-US exchanges
_NON_US_SUFFIXES = {"l_EQ", "_GB_EQ", "_UK_EQ", "_DE_EQ", "_FR_EQ",
                    "_NL_EQ", "_ES_EQ", "_IT_EQ", "_CH_EQ", "_SE_EQ",
                    "_NO_EQ", "_DK_EQ", "_FI_EQ"}

_BASE_URL = "https://api.marketstack.com/v1"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_intraday_supported(ticker: str) -> bool:
    """True if the ticker is a US equity eligible for intraday data.

    Checks the raw T212-format ticker — London stocks (ending ``l_EQ``)
    and other non-US suffixes return False.
    """
    raw = ticker.strip()
    if raw.endswith("l_EQ"):
        return False
    for suffix in _NON_US_SUFFIXES:
        if raw.endswith(suffix):
            return False
    cleaned = _clean_ticker(raw)
    if cleaned.endswith(".L"):
        return False
    return True


def bars_per_day(interval: str) -> int:
    """Return number of bars in one US trading day for the given interval."""
    api_interval = _INTERVAL_API_MAP.get(interval, interval)
    return INTERVAL_BARS_PER_DAY.get(api_interval, 1)


def fetch_intraday_bars(
    ticker: str,
    interval: str = "5Min",
    start_date: str = "2024-01-01",
    end_date: str = "2026-04-06",
    data_dir: Path | str = DEFAULT_INTRADAY_DIR,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV intraday bars from MarketStack for a single US ticker.

    Returns a DataFrame with columns: Open, High, Low, Close, Volume
    indexed by timestamp, matching the data_loader convention.

    Parameters
    ----------
    ticker : str
        Raw or T212-format ticker (e.g. ``TSLA`` or ``TSLA_US_EQ``).
    interval : str
        Bar size: ``"1Min"``, ``"5Min"``, ``"15Min"``, ``"30Min"``, ``"1Hour"``.
    start_date, end_date : str
        ISO date strings for the data range.
    data_dir : Path
        Cache directory (default ``data/intraday/``).
    use_cache : bool
        If True, read from CSV cache when available.
    """
    symbol = _clean_ticker(ticker)
    api_interval = _INTERVAL_API_MAP.get(interval, "5min")
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_path = _cache_path(symbol, api_interval, start_date, end_date, data_dir)

    # ── Try cache ──
    if use_cache and cache_path.exists():
        try:
            df = pd.read_csv(cache_path, parse_dates=["timestamp"], index_col="timestamp")
            df = sanitise_ohlcv(df)
            if len(df) >= 100:
                return df
            cache_path.unlink(missing_ok=True)
        except Exception:
            cache_path.unlink(missing_ok=True)

    # ── Fetch from MarketStack ──
    api_key = _get_api_key()
    if not api_key:
        logger.warning("MarketStack API key not set — set MARKETSTACK_API_KEY env var")
        return pd.DataFrame()

    try:
        df = _download_bars(api_key, symbol, api_interval, start_date, end_date)
    except Exception as exc:
        logger.warning("MarketStack fetch failed for %s: %s", symbol, exc)
        return pd.DataFrame()

    if df.empty:
        logger.info("No MarketStack data for %s (%s, %s–%s)", symbol, api_interval, start_date, end_date)
        return pd.DataFrame()

    df = sanitise_ohlcv(df)

    # ── Cache to CSV (saves API calls) ──
    try:
        df.to_csv(cache_path, index_label="timestamp")
        logger.info("Cached %d bars for %s to %s", len(df), symbol, cache_path.name)
    except Exception as exc:
        logger.debug("Cache write failed for %s: %s", symbol, exc)

    return df


def fetch_intraday_universe(
    tickers: List[str],
    interval: str = "5Min",
    start_date: str = "2024-01-01",
    end_date: str = "2026-04-06",
    data_dir: Path | str = DEFAULT_INTRADAY_DIR,
    use_cache: bool = True,
    max_workers: int = 2,
) -> Dict[str, pd.DataFrame]:
    """Fetch intraday bars for multiple tickers.

    Only fetches US-eligible tickers. Uses sequential fetching by default
    to respect MarketStack rate limits (max_workers=2).
    Returns {original_ticker: DataFrame}.
    """
    eligible = [t for t in tickers if is_intraday_supported(t)]
    if not eligible:
        return {}

    results: Dict[str, pd.DataFrame] = {}

    def _fetch_one(t: str) -> tuple:
        df = fetch_intraday_bars(t, interval, start_date, end_date, data_dir, use_cache)
        return t, df

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for orig, df in pool.map(_fetch_one, eligible):
            if not df.empty:
                results[orig] = df

    return results


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _cache_path(
    symbol: str, interval: str, start: str, end: str, data_dir: Path,
) -> Path:
    safe = symbol.replace("/", "_").replace(".", "_").upper()
    return data_dir / f"{safe}_{interval}_{start}_{end}.csv"


def _get_api_key() -> str:
    """Read MarketStack API key from environment."""
    return os.environ.get("MARKETSTACK_API_KEY", "")


def _download_bars(
    api_key: str,
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Download intraday bars from MarketStack, handling pagination.

    MarketStack returns max 1000 results per request.  We paginate with
    offset to get full history.
    """
    all_rows: List[Dict] = []
    offset = 0
    limit = 1000

    while True:
        params = {
            "access_key": api_key,
            "symbols": symbol,
            "interval": interval,
            "date_from": f"{start_date}T00:00:00+0000",
            "date_to": f"{end_date}T23:59:59+0000",
            "limit": limit,
            "offset": offset,
        }

        for attempt in range(3):
            try:
                resp = requests.get(
                    f"{_BASE_URL}/intraday",
                    params=params,
                    timeout=30,
                )
                resp.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise exc

        data = resp.json()

        # Check for API errors
        if "error" in data:
            err = data["error"]
            raise RuntimeError(
                f"MarketStack API error: {err.get('code', '?')} — {err.get('message', 'unknown')}"
            )

        bars = data.get("data", [])
        if not bars:
            break

        all_rows.extend(bars)

        # Check if more pages exist
        pagination = data.get("pagination", {})
        total = pagination.get("total", 0)
        offset += limit
        if offset >= total:
            break

        # Rate limiting courtesy
        time.sleep(0.5)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # MarketStack returns: date, symbol, exchange, open, high, low, close,
    # volume, last, split_factor
    if "date" not in df.columns:
        return pd.DataFrame()

    df["timestamp"] = pd.to_datetime(df["date"], utc=True)
    df = df.set_index("timestamp").sort_index()

    # Normalise column names to match data_loader convention
    col_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df.rename(columns=col_map, inplace=True)

    keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep]

    # Drop duplicates and sort
    df = df[~df.index.duplicated(keep="last")].sort_index()

    return df
