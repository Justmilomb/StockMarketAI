"""Intraday feature engineering for minute/hour bar data.

Reuses the core technical indicator functions from ``features_advanced``
(RSI, MACD, Bollinger, ATR, Stochastic, etc.) with window sizes adapted
to the bar interval, and adds intraday-specific features: true VWAP,
opening range breakout, bar-of-day position, cumulative volume, and
spread proxy.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from features import _compute_rsi
from features_advanced import (
    compute_adx,
    compute_atr,
    compute_bollinger_bands,
    compute_macd,
    compute_obv,
    compute_stochastic,
    compute_williams_r,
)
from intraday_data import bars_per_day

# ---------------------------------------------------------------------------
# Intraday-specific feature columns (on top of the standard set)
# ---------------------------------------------------------------------------

INTRADAY_EXTRA_COLUMNS: List[str] = [
    "vwap",
    "vwap_deviation",
    "opening_range_high",
    "opening_range_low",
    "or_breakout",
    "bar_of_day",
    "cumulative_volume_pct",
    "spread_proxy",
]

# Standard technical features produced (same names as features_advanced)
STANDARD_COLUMNS: List[str] = [
    "open", "prev_close",
    "ma_fast", "ma_mid", "ma_slow",
    "macd", "macd_signal", "macd_hist", "adx",
    "rsi", "stoch_k", "stoch_d", "williams_r",
    "ret_1", "ret_5", "ret_10", "roc_10",
    "vol_range", "bb_upper", "bb_lower", "bb_width", "atr", "atr_pct",
    "obv", "obv_slope", "volume_sma_ratio",
    "ret_slow", "ret_very_slow",
]

FEATURE_COLUMNS_INTRADAY: List[str] = STANDARD_COLUMNS + INTRADAY_EXTRA_COLUMNS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def engineer_intraday_features(
    df: pd.DataFrame,
    interval_minutes: int = 5,
    target_horizon_bars: int = 1,
) -> pd.DataFrame:
    """Compute all features for intraday bar data.

    Parameters
    ----------
    df : pd.DataFrame
        Raw OHLCV DataFrame from Alpaca (columns: Open, High, Low, Close,
        Volume, optionally VWAP).  Index must be a DatetimeIndex.
    interval_minutes : int
        Bar size in minutes (1, 5, 15, 30, 60).
    target_horizon_bars : int
        How many bars ahead to set the target label.  ``target_up = 1``
        if close[t + horizon] > close[t].

    Returns
    -------
    pd.DataFrame
        Enriched DataFrame with all feature columns and ``target_up``.
    """
    data = df.copy()

    # ── Normalise column names ──
    data = data.rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume", "VWAP": "vwap_raw",
    })
    numeric_cols = ["open", "high", "low", "close", "volume"]
    existing = [c for c in numeric_cols if c in data.columns]
    data[existing] = data[existing].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["close"])

    bpd = bars_per_day(_interval_to_alpaca(interval_minutes))

    # ── Window sizes adapted to bar interval ──
    # "fast" ≈ 1 trading day, "mid" ≈ 2 days, "slow" ≈ 1 week
    w_fast = max(bpd, 5)
    w_mid = max(bpd * 2, 10)
    w_slow = max(bpd * 5, 30)
    w_rsi = max(14, bpd)
    w_bb = max(20, bpd)
    w_atr = max(14, bpd)

    # ── Standard technical indicators ──
    data["prev_close"] = data["close"].shift(1)
    data["ret_1"] = data["close"].pct_change(1)
    data["ret_5"] = data["close"].pct_change(5)
    data["ret_10"] = data["close"].pct_change(w_fast)
    data["vol_range"] = (
        data["high"].rolling(w_fast).max() - data["low"].rolling(w_fast).min()
    )
    data["ma_fast"] = data["close"].rolling(w_fast).mean()
    data["ma_mid"] = data["close"].rolling(w_mid).mean()
    data["ma_slow"] = data["close"].rolling(w_slow).mean()
    data["rsi"] = _compute_rsi(data["close"], window=w_rsi)

    # MACD — use standard params (they're unitless EMA spans)
    compute_macd(data, fast=12, slow=26, signal=9)
    compute_bollinger_bands(data, window=w_bb)
    compute_atr(data, window=w_atr)
    # Rename ATR columns to generic names
    if "atr_14d" in data.columns:
        data.rename(columns={"atr_14d": "atr", "atr_pct": "atr_pct"}, inplace=True)
    compute_obv(data)
    compute_stochastic(data, k_period=w_rsi)
    compute_williams_r(data, period=w_rsi)
    compute_adx(data, period=w_rsi)
    if "adx_14d" in data.columns:
        data.rename(columns={"adx_14d": "adx"}, inplace=True)

    data["roc_10"] = data["close"].pct_change(w_fast) * 100.0

    vol_sma = data["volume"].rolling(w_bb).mean()
    data["volume_sma_ratio"] = data["volume"] / vol_sma.replace(0.0, np.nan)

    # Multi-bar returns (slow / very slow)
    data["ret_slow"] = data["close"].pct_change(w_mid)
    data["ret_very_slow"] = data["close"].pct_change(w_slow)

    # ── Intraday-specific features ──
    _add_vwap(data)
    _add_opening_range(data, interval_minutes, bpd)
    _add_bar_of_day(data, interval_minutes)
    _add_cumulative_volume(data, bpd)
    _add_spread_proxy(data)

    # ── Target label ──
    data["target_up"] = (
        data["close"].shift(-target_horizon_bars) > data["close"]
    ).astype(int)

    # Drop NaN rows from rolling windows
    feature_cols = [c for c in FEATURE_COLUMNS_INTRADAY if c in data.columns]
    data = data.dropna(subset=feature_cols).copy()

    return data


# ---------------------------------------------------------------------------
# Intraday feature helpers
# ---------------------------------------------------------------------------

def _add_vwap(data: pd.DataFrame) -> None:
    """Add true VWAP (from Alpaca) or compute proxy from OHLCV."""
    if "vwap_raw" in data.columns:
        data["vwap"] = pd.to_numeric(data["vwap_raw"], errors="coerce")
    else:
        typical = (data["high"] + data["low"] + data["close"]) / 3.0
        tp_vol = typical * data["volume"]
        cum_vol = data["volume"].expanding().sum()
        cum_vol = cum_vol.replace(0.0, np.nan)
        data["vwap"] = tp_vol.expanding().sum() / cum_vol

    data["vwap_deviation"] = (data["close"] - data["vwap"]) / data["vwap"].replace(0.0, np.nan)


def _add_opening_range(
    data: pd.DataFrame, interval_minutes: int, bpd: int,
) -> None:
    """Add opening range high/low and breakout signal.

    Opening range = first 30 minutes of each trading day.
    """
    if not isinstance(data.index, pd.DatetimeIndex):
        data["opening_range_high"] = np.nan
        data["opening_range_low"] = np.nan
        data["or_breakout"] = 0.0
        return

    or_bars = max(1, 30 // interval_minutes)
    dates = data.index.date
    unique_dates = pd.Series(dates).unique()

    or_high = pd.Series(np.nan, index=data.index, dtype=float)
    or_low = pd.Series(np.nan, index=data.index, dtype=float)

    for d in unique_dates:
        mask = dates == d
        day_data = data.loc[mask]
        if len(day_data) < or_bars:
            continue
        opening = day_data.iloc[:or_bars]
        h = float(opening["high"].max())
        lo = float(opening["low"].min())
        or_high.loc[mask] = h
        or_low.loc[mask] = lo

    data["opening_range_high"] = or_high
    data["opening_range_low"] = or_low

    # Breakout: +1 above range, -1 below, 0 inside
    data["or_breakout"] = np.where(
        data["close"] > data["opening_range_high"], 1.0,
        np.where(data["close"] < data["opening_range_low"], -1.0, 0.0),
    )


def _add_bar_of_day(data: pd.DataFrame, interval_minutes: int) -> None:
    """Add normalised bar position within the trading day (0.0 to 1.0)."""
    if not isinstance(data.index, pd.DatetimeIndex):
        data["bar_of_day"] = 0.5
        return

    # US market: 09:30 to 16:00 = 390 minutes
    minutes_since_open = (
        data.index.hour * 60 + data.index.minute - 570  # 9*60+30 = 570
    ).clip(lower=0)
    data["bar_of_day"] = (minutes_since_open / 390.0).clip(upper=1.0)


def _add_cumulative_volume(data: pd.DataFrame, bpd: int) -> None:
    """Add cumulative volume as percentage of average daily volume."""
    if not isinstance(data.index, pd.DatetimeIndex):
        data["cumulative_volume_pct"] = 1.0
        return

    dates = data.index.date
    daily_vol = data.groupby(dates)["volume"].transform("sum")
    avg_daily = daily_vol.rolling(window=max(bpd * 5, 20), min_periods=1).mean()
    avg_daily = avg_daily.replace(0.0, np.nan)

    cum_vol_today = data.groupby(dates)["volume"].cumsum()
    data["cumulative_volume_pct"] = cum_vol_today / avg_daily


def _add_spread_proxy(data: pd.DataFrame) -> None:
    """Add high-low range as % of close — proxy for bid-ask spread."""
    close_safe = data["close"].replace(0.0, np.nan)
    data["spread_proxy"] = (data["high"] - data["low"]) / close_safe


def _interval_to_alpaca(interval_minutes: int) -> str:
    """Convert minutes to Alpaca interval string."""
    mapping = {1: "1Min", 5: "5Min", 15: "15Min", 30: "30Min", 60: "1Hour"}
    return mapping.get(interval_minutes, "5Min")
