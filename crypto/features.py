"""Crypto feature engineering.

Reuses stock OHLCV indicators (RSI, MACD, Bollinger, ATR, etc.) from
``features_advanced.py`` and adds crypto-specific features:
- BTC correlation (rolling correlation to BTC returns)
- Funding rate (placeholder for exchange-specific API)
- Time-of-day / day-of-week cyclical features

Produces a feature DataFrame compatible with the ML ensemble.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np
import pandas as pd

from features import _compute_rsi
from features_advanced import (
    FEATURE_GROUPS,
    compute_atr,
    compute_bollinger_bands,
    compute_macd,
    compute_obv,
    compute_stochastic,
    compute_williams_r,
    compute_adx,
    compute_vwap_proxy,
)
from types_shared import FeatureGroup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Crypto-specific feature groups — extends the stock groups
# ---------------------------------------------------------------------------

CRYPTO_FEATURE_GROUPS: Dict[str, FeatureGroup] = {
    **FEATURE_GROUPS,
    "crypto": FeatureGroup(
        name="crypto",
        columns=["btc_corr_30d", "funding_rate", "hour_sin", "hour_cos", "dow_sin", "dow_cos"],
        description="Crypto-specific: BTC correlation, funding rate, time cyclicals",
    ),
}

# Full ordered list of crypto feature columns
CRYPTO_FEATURE_COLUMNS: List[str] = [
    col
    for group_name in ["price", "trend", "momentum", "volatility", "volume", "multi_tf", "crypto"]
    for col in CRYPTO_FEATURE_GROUPS[group_name].columns
]


# ---------------------------------------------------------------------------
# Crypto-specific indicator functions
# ---------------------------------------------------------------------------


def compute_btc_correlation(
    data: pd.DataFrame,
    btc_data: pd.DataFrame,
    window: int = 30,
) -> None:
    """Compute rolling correlation of returns to BTC. Adds column in-place.

    If the pair *is* BTC, the correlation is set to 1.0.
    """
    if btc_data.empty or len(btc_data) < window:
        data["btc_corr_30d"] = 0.0
        return

    asset_returns = data["close"].pct_change()
    btc_returns = btc_data["Close"].pct_change()

    # Align on index (both should be datetime-indexed)
    aligned = pd.DataFrame({
        "asset": asset_returns,
        "btc": btc_returns,
    }).dropna()

    if len(aligned) < window:
        data["btc_corr_30d"] = 0.0
        return

    rolling_corr = aligned["asset"].rolling(window=window).corr(aligned["btc"])

    # Map back to original index
    data["btc_corr_30d"] = rolling_corr.reindex(data.index).fillna(0.0)


def compute_funding_rate(data: pd.DataFrame) -> None:
    """Placeholder for funding rate feature.

    Real implementation requires exchange-specific API calls to fetch
    perpetual futures funding rates. For now, fills with 0.0.
    """
    data["funding_rate"] = 0.0


def compute_time_features(data: pd.DataFrame) -> None:
    """Add cyclical time features for 24/7 crypto markets.

    Encodes hour-of-day and day-of-week as sine/cosine pairs to capture
    cyclical patterns without discontinuities.
    """
    if not isinstance(data.index, pd.DatetimeIndex):
        data["hour_sin"] = 0.0
        data["hour_cos"] = 1.0
        data["dow_sin"] = 0.0
        data["dow_cos"] = 1.0
        return

    hours = data.index.hour
    days = data.index.dayofweek

    data["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
    data["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
    data["dow_sin"] = np.sin(2 * np.pi * days / 7.0)
    data["dow_cos"] = np.cos(2 * np.pi * days / 7.0)


# ---------------------------------------------------------------------------
# Composite feature engineering
# ---------------------------------------------------------------------------


def engineer_crypto_features(
    df: pd.DataFrame,
    btc_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Full feature engineering pipeline for one crypto pair.

    Takes a raw OHLCV DataFrame (columns: Open, High, Low, Close, Volume),
    normalises column names, computes all technical + crypto-specific features,
    creates the binary ``target_up`` label, and drops NaN rows.

    Args:
        df: Raw OHLCV data for one crypto pair.
        btc_data: BTC OHLCV data for correlation computation. Pass None to
            skip BTC correlation (filled with 0.0).

    Returns:
        Enriched DataFrame with all feature columns and target.
    """
    data = df.copy()

    # Normalise column names (same as stock pipeline)
    data = data.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    })

    # Coerce to numeric
    numeric_cols = ["open", "high", "low", "close", "volume"]
    existing = [c for c in numeric_cols if c in data.columns]
    data[existing] = data[existing].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["close"])

    # --- Standard technical indicators (shared with stocks) ---
    data["prev_close"] = data["close"].shift(1)
    data["ret_1d"] = data["close"].pct_change(periods=1)
    data["ret_5d"] = data["close"].pct_change(periods=5)
    data["ret_10d"] = data["close"].pct_change(periods=10)
    data["vol_5d"] = (
        data["high"].rolling(window=5).max() - data["low"].rolling(window=5).min()
    )
    data["ma_5d"] = data["close"].rolling(window=5).mean()
    data["ma_10d"] = data["close"].rolling(window=10).mean()
    data["ma_30d"] = data["close"].rolling(window=30).mean()
    data["rsi_14d"] = _compute_rsi(data["close"], window=14)

    compute_macd(data)
    compute_bollinger_bands(data)
    compute_atr(data)
    compute_obv(data)
    compute_stochastic(data)
    compute_williams_r(data)
    compute_adx(data)
    compute_vwap_proxy(data)

    # Rate of change (10-day)
    data["roc_10d"] = data["close"].pct_change(periods=10) * 100.0

    # Volume SMA ratio
    vol_sma_20 = data["volume"].rolling(window=20).mean()
    data["volume_sma_ratio"] = data["volume"] / vol_sma_20.replace(0.0, np.nan)

    # Multi-timeframe returns
    data["ret_20d"] = data["close"].pct_change(periods=20)
    data["ret_60d"] = data["close"].pct_change(periods=60)
    data["weekly_momentum"] = data["ma_5d"].pct_change(periods=5)
    data["monthly_momentum"] = data["ma_30d"].pct_change(periods=20)

    # --- Crypto-specific indicators ---
    if btc_data is not None and not btc_data.empty:
        compute_btc_correlation(data, btc_data, window=30)
    else:
        data["btc_corr_30d"] = 0.0

    compute_funding_rate(data)
    compute_time_features(data)

    # --- Target ---
    data["target_up"] = (data["close"].shift(-1) > data["close"]).astype(int)

    # Drop NaN rows from rolling windows
    data = data.dropna(subset=CRYPTO_FEATURE_COLUMNS).copy()

    return data


def get_crypto_feature_group_columns(group_name: str) -> List[str]:
    """Return the feature column names for a named crypto group.

    Raises:
        KeyError: If the group name is not recognised.
    """
    if group_name not in CRYPTO_FEATURE_GROUPS:
        raise KeyError(
            f"Unknown crypto feature group '{group_name}'. "
            f"Available: {list(CRYPTO_FEATURE_GROUPS.keys())}"
        )
    return list(CRYPTO_FEATURE_GROUPS[group_name].columns)
