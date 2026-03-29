"""Crypto OHLCV data loader using ccxt.

Fetches historical and live price data from crypto exchanges.
Mirrors the stock ``data_loader.py`` interface: returns DataFrames with
columns [Open, High, Low, Close, Volume] and a datetime index.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("data")


def _safe_import_ccxt():  # noqa: ANN202
    """Lazy-import ccxt, returning None if unavailable."""
    try:
        import ccxt
        return ccxt
    except ImportError:
        logger.warning(
            "ccxt is not installed — crypto data loading unavailable. "
            "Install with: pip install ccxt"
        )
        return None


def _pair_to_filename(pair: str) -> str:
    """Convert 'BTC/USDT' to 'BTC_USDT' for filesystem-safe filenames."""
    return pair.replace("/", "_").replace(":", "_").upper()


def _get_cache_path(
    pair: str,
    exchange_name: str,
    timeframe: str,
    data_dir: Path,
) -> Path:
    """Build a cache file path for a given pair, exchange, and timeframe."""
    safe_pair = _pair_to_filename(pair)
    filename = f"crypto_{exchange_name}_{safe_pair}_{timeframe}.csv"
    return data_dir / filename


def _create_exchange(exchange_name: str = "binance"):  # noqa: ANN202
    """Create a ccxt exchange instance with rate limiting enabled."""
    ccxt = _safe_import_ccxt()
    if ccxt is None:
        return None

    exchange_class = getattr(ccxt, exchange_name, None)
    if exchange_class is None:
        logger.error("Exchange '%s' not found in ccxt", exchange_name)
        return None

    return exchange_class({
        "enableRateLimit": True,
        "timeout": 30_000,
    })


def fetch_pair_data(
    pair: str,
    exchange_name: str = "binance",
    timeframe: str = "1d",
    limit: int = 500,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch OHLCV data for a single crypto pair.

    Returns a DataFrame with columns [Open, High, Low, Close, Volume]
    and a datetime index, matching the stock data_loader format.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cache_path = _get_cache_path(pair, exchange_name, timeframe, data_dir)

    # Try cache first
    if use_cache and cache_path.exists():
        try:
            df = pd.read_csv(cache_path, parse_dates=["Date"], index_col="Date")
            needed = ["Open", "High", "Low", "Close", "Volume"]
            if all(c in df.columns for c in needed) and len(df) >= limit * 0.3:
                return df
            logger.info(
                "[crypto_data] Stale cache for %s (%d rows) — re-fetching",
                pair, len(df),
            )
        except Exception:
            pass  # Fall through to download

    exchange = _create_exchange(exchange_name)
    if exchange is None:
        return pd.DataFrame()

    try:
        # Retry with backoff
        ohlcv = []
        for attempt in range(3):
            try:
                ohlcv = exchange.fetch_ohlcv(pair, timeframe=timeframe, limit=limit)
                if ohlcv:
                    break
            except Exception as exc:
                err_str = str(exc).lower()
                if "rate" in err_str or "too many" in err_str:
                    time.sleep(2 ** attempt)
                    continue
                raise
            time.sleep(1)

        if not ohlcv:
            logger.warning("[crypto_data] No data returned for %s on %s", pair, exchange_name)
            return pd.DataFrame()

        # ccxt returns [[timestamp, open, high, low, close, volume], ...]
        df = pd.DataFrame(ohlcv, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
        df["Date"] = pd.to_datetime(df["Timestamp"], unit="ms", utc=True)
        df = df.set_index("Date").drop(columns=["Timestamp"])
        df.index.name = "Date"

        # Ensure numeric types
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["Close"])

        # Cache to CSV
        df.to_csv(cache_path)
        logger.info("[crypto_data] Fetched %d bars for %s from %s", len(df), pair, exchange_name)
        return df

    except Exception as exc:
        logger.error("[crypto_data] Error fetching %s: %s", pair, exc)
        return pd.DataFrame()


def fetch_universe_data(
    pairs: List[str],
    exchange_name: str = "binance",
    timeframe: str = "1d",
    limit: int = 500,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    use_cache: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Fetch OHLCV data for multiple crypto pairs.

    Returns a dict mapping pair -> DataFrame, matching the stock
    ``fetch_universe_data`` interface.
    """
    import concurrent.futures

    universe_data: Dict[str, pd.DataFrame] = {}

    def _fetch_one(pair: str) -> tuple[str, pd.DataFrame]:
        return pair, fetch_pair_data(
            pair=pair,
            exchange_name=exchange_name,
            timeframe=timeframe,
            limit=limit,
            data_dir=data_dir,
            use_cache=use_cache,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(_fetch_one, pairs))

    for pair, df in results:
        if not df.empty:
            universe_data[pair] = df

    return universe_data


def fetch_live_prices(
    pairs: List[str],
    exchange_name: str = "binance",
) -> Dict[str, Dict[str, float]]:
    """Fetch near real-time prices for crypto pairs.

    Returns: { "BTC/USDT": {"price": 65000.0, "change_pct": 2.1}, ... }
    """
    live_data: Dict[str, Dict[str, float]] = {}
    if not pairs:
        return live_data

    exchange = _create_exchange(exchange_name)
    if exchange is None:
        return {p: {"price": 0.0, "change_pct": 0.0} for p in pairs}

    for pair in pairs:
        try:
            ticker = exchange.fetch_ticker(pair)
            price = float(ticker.get("last", 0.0) or 0.0)
            change_pct = float(ticker.get("percentage", 0.0) or 0.0)
            live_data[pair] = {"price": price, "change_pct": change_pct}
        except Exception as exc:
            logger.warning("[crypto_data] Live price error for %s: %s", pair, exc)
            live_data[pair] = {"price": 0.0, "change_pct": 0.0}

    return live_data
