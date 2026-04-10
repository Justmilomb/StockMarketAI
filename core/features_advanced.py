from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from features import FEATURE_COLUMNS, _compute_rsi
from types_shared import FeatureGroup


# ---------------------------------------------------------------------------
# Feature group definitions
# ---------------------------------------------------------------------------

FEATURE_GROUPS: Dict[str, FeatureGroup] = {
    "trend": FeatureGroup(
        name="trend",
        columns=["ma_5d", "ma_10d", "ma_30d", "macd", "macd_signal", "macd_hist", "adx_14d"],
        description="Trend-following indicators: moving averages, MACD, ADX",
    ),
    "momentum": FeatureGroup(
        name="momentum",
        columns=["rsi_14d", "stoch_k", "stoch_d", "williams_r", "ret_1d", "ret_5d", "ret_10d", "roc_10d"],
        description="Momentum oscillators and short-term returns",
    ),
    "volatility": FeatureGroup(
        name="volatility",
        columns=["vol_5d", "bb_upper", "bb_lower", "bb_width", "atr_14d", "atr_pct"],
        description="Volatility measures: Bollinger Bands, ATR, high-low range",
    ),
    "volume": FeatureGroup(
        name="volume",
        columns=["obv", "obv_slope", "volume_sma_ratio", "vwap_proxy_ratio"],
        description="Volume-based indicators: OBV, volume ratios, VWAP proxy",
    ),
    "multi_tf": FeatureGroup(
        name="multi_tf",
        columns=["ret_20d", "ret_60d", "weekly_momentum", "monthly_momentum"],
        description="Multi-timeframe returns and momentum",
    ),
    "short_term": FeatureGroup(
        name="short_term",
        columns=[
            "rsi_3d", "ret_2d", "gap_pct", "range_pct", "close_position",
            "body_pct", "upper_shadow_pct", "lower_shadow_pct",
            "vol_spike", "mean_reversion_5d",
        ],
        description="Short-term day-trading features: candlestick patterns, gaps, volume spikes",
    ),
    "price": FeatureGroup(
        name="price",
        columns=["open", "prev_close"],
        description="Raw price reference features",
    ),
}

# Full ordered list of V2 feature columns — the union of all groups
FEATURE_COLUMNS_V2: List[str] = [
    col
    for group_name in ["price", "trend", "momentum", "volatility", "volume", "multi_tf", "short_term"]
    for col in FEATURE_GROUPS[group_name].columns
]


# ---------------------------------------------------------------------------
# Individual indicator compute functions
# ---------------------------------------------------------------------------


def compute_macd(
    data: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> None:
    """Compute MACD, signal line, and histogram. Adds columns in-place."""
    ema_fast = data["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = data["close"].ewm(span=slow, adjust=False).mean()
    data["macd"] = ema_fast - ema_slow
    data["macd_signal"] = data["macd"].ewm(span=signal, adjust=False).mean()
    data["macd_hist"] = data["macd"] - data["macd_signal"]


def compute_bollinger_bands(
    data: pd.DataFrame,
    window: int = 20,
    num_std: int = 2,
) -> None:
    """Compute Bollinger Bands upper/lower and bandwidth. Adds columns in-place."""
    sma = data["close"].rolling(window=window).mean()
    std = data["close"].rolling(window=window).std()
    data["bb_upper"] = sma + num_std * std
    data["bb_lower"] = sma - num_std * std
    # Width as a ratio of the middle band to stay scale-invariant
    data["bb_width"] = (data["bb_upper"] - data["bb_lower"]) / sma


def compute_atr(data: pd.DataFrame, window: int = 14) -> None:
    """Compute Average True Range and ATR as a percentage of close. Adds columns in-place."""
    high = data["high"]
    low = data["low"]
    prev_close = data["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    data["atr_14d"] = tr.rolling(window=window).mean()
    data["atr_pct"] = data["atr_14d"] / data["close"]


def compute_obv(data: pd.DataFrame) -> None:
    """Compute On-Balance Volume and its 5-day slope. Adds columns in-place."""
    # Direction: +1 if close rose, -1 if fell, 0 if unchanged
    direction = np.sign(data["close"].diff())
    data["obv"] = (direction * data["volume"]).cumsum()
    # Slope approximated as the linear regression slope over a 5-day window
    data["obv_slope"] = data["obv"].rolling(window=5).apply(
        _linreg_slope, raw=True,
    )


def _linreg_slope(values: np.ndarray) -> float:
    """Slope of a simple linear regression over an array of values."""
    n = len(values)
    x = np.arange(n, dtype=np.float64)
    x_mean = x.mean()
    y_mean = values.mean()
    denom = (x * x).sum() - n * x_mean * x_mean
    if denom == 0.0:
        return 0.0
    return float(((x * values).sum() - n * x_mean * y_mean) / denom)


def compute_stochastic(
    data: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> None:
    """Compute Stochastic %K and %D. Adds columns in-place."""
    low_min = data["low"].rolling(window=k_period).min()
    high_max = data["high"].rolling(window=k_period).max()
    denom = high_max - low_min
    # Avoid division by zero when high == low over the window
    denom = denom.replace(0.0, np.nan)
    data["stoch_k"] = 100.0 * (data["close"] - low_min) / denom
    data["stoch_d"] = data["stoch_k"].rolling(window=d_period).mean()


def compute_williams_r(data: pd.DataFrame, period: int = 14) -> None:
    """Compute Williams %R. Adds column in-place."""
    high_max = data["high"].rolling(window=period).max()
    low_min = data["low"].rolling(window=period).min()
    denom = high_max - low_min
    denom = denom.replace(0.0, np.nan)
    data["williams_r"] = -100.0 * (high_max - data["close"]) / denom


def compute_adx(data: pd.DataFrame, period: int = 14) -> None:
    """Compute Average Directional Index (ADX). Adds column in-place.

    Uses Wilder's smoothing (equivalent to EMA with alpha = 1/period).
    """
    high = data["high"]
    low = data["low"]
    prev_close = data["close"].shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=data.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=data.index,
    )

    # Wilder's smoothing (EMA with alpha = 1/period)
    alpha = 1.0 / period
    atr_smooth = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_smooth
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_smooth

    dx_denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / dx_denom
    data["adx_14d"] = dx.ewm(alpha=alpha, adjust=False).mean()


def compute_vwap_proxy(data: pd.DataFrame) -> None:
    """Compute a VWAP proxy ratio (cumulative typical-price*volume / cumulative volume).

    This is a session-less approximation since daily bars lack intraday data.
    We use a rolling 20-day window to keep the value recent.
    Adds the ratio of VWAP proxy to close as ``vwap_proxy_ratio``.
    """
    typical_price = (data["high"] + data["low"] + data["close"]) / 3.0
    tp_vol = typical_price * data["volume"]

    cum_tp_vol = tp_vol.rolling(window=20).sum()
    cum_vol = data["volume"].rolling(window=20).sum()
    # Guard against zero-volume windows
    cum_vol = cum_vol.replace(0.0, np.nan)
    vwap_proxy = cum_tp_vol / cum_vol
    data["vwap_proxy_ratio"] = vwap_proxy / data["close"]


# ---------------------------------------------------------------------------
# Composite feature engineering
# ---------------------------------------------------------------------------


def engineer_features_v2(df: pd.DataFrame) -> pd.DataFrame:
    """Superset of the original ``engineer_features_for_ticker``.

    Takes a raw OHLCV DataFrame (columns: Open, High, Low, Close, Volume),
    normalises column names, computes all ~30 technical features, creates
    the binary ``target_up`` label, and drops rows with NaN values.

    Returns the enriched DataFrame.
    """
    data = df.copy()

    # Normalise column names
    data = data.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
        }
    )

    # Coerce to numeric (handles header rows in cached CSVs)
    numeric_cols = ["open", "high", "low", "close", "volume"]
    existing_numeric = [c for c in numeric_cols if c in data.columns]
    data[existing_numeric] = data[existing_numeric].apply(
        pd.to_numeric, errors="coerce"
    )
    data = data.dropna(subset=["close"])

    # --- Original 10 features (from features.py logic) ---
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

    # --- New indicators ---
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

    # Volume SMA ratio (current volume vs 20-day SMA)
    vol_sma_20 = data["volume"].rolling(window=20).mean()
    data["volume_sma_ratio"] = data["volume"] / vol_sma_20.replace(0.0, np.nan)

    # Multi-timeframe returns
    data["ret_20d"] = data["close"].pct_change(periods=20)
    data["ret_60d"] = data["close"].pct_change(periods=60)

    # Weekly momentum: 5-day return of the 5-day MA (smoothed momentum)
    data["weekly_momentum"] = data["ma_5d"].pct_change(periods=5)

    # Monthly momentum: 20-day return of the 30-day MA
    data["monthly_momentum"] = data["ma_30d"].pct_change(periods=20)

    # --- Short-term day-trading features ---
    data["rsi_3d"] = _compute_rsi(data["close"], window=3)
    data["ret_2d"] = data["close"].pct_change(periods=2)
    data["gap_pct"] = (data["open"] - data["prev_close"]) / data["prev_close"].replace(0.0, np.nan)

    hl_range = (data["high"] - data["low"]).replace(0.0, np.nan)
    data["range_pct"] = hl_range / data["close"].replace(0.0, np.nan)
    data["close_position"] = (data["close"] - data["low"]) / hl_range
    data["body_pct"] = (data["close"] - data["open"]).abs() / hl_range
    data["upper_shadow_pct"] = (data["high"] - data[["open", "close"]].max(axis=1)) / hl_range
    data["lower_shadow_pct"] = (data[["open", "close"]].min(axis=1) - data["low"]) / hl_range

    vol_sma_5 = data["volume"].rolling(window=5).mean().replace(0.0, np.nan)
    data["vol_spike"] = data["volume"] / vol_sma_5
    data["mean_reversion_5d"] = (data["close"] - data["ma_5d"]) / data["atr_14d"].replace(0.0, np.nan)

    # --- Target ---
    data["target_up"] = (data["close"].shift(-1) > data["close"]).astype(int)

    # Drop NaN rows (from rolling windows / shifts) but keep the latest row
    # which may lack a target value — same logic as the original
    data = data.dropna(subset=FEATURE_COLUMNS_V2).copy()

    return data


# ---------------------------------------------------------------------------
# Dataset builders (V2 variants)
# ---------------------------------------------------------------------------


def build_universe_dataset_v2(
    universe_data: Dict[str, pd.DataFrame],
    feature_columns: List[str] | None = None,
) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Build a training dataset from multiple tickers using V2 features.

    Args:
        universe_data: Mapping of ticker symbol to raw OHLCV DataFrame.
        feature_columns: Subset of columns to include. Defaults to
            ``FEATURE_COLUMNS_V2`` (all ~30 features).

    Returns:
        X: Feature matrix (n_samples, n_features).
        y: Binary labels (1 = next-day close higher).
        meta: DataFrame with ``ticker`` and ``date`` aligned to X/y rows.
    """
    cols = feature_columns if feature_columns is not None else FEATURE_COLUMNS_V2
    feature_frames: List[pd.DataFrame] = []

    for ticker, df in universe_data.items():
        engineered = engineer_features_v2(df)
        if engineered.empty:
            continue
        # Only for training: require valid target
        engineered = engineered.dropna(subset=["target_up"]).copy()
        if engineered.empty:
            continue
        engineered["ticker"] = ticker
        engineered["date"] = engineered.index
        feature_frames.append(engineered)

    if not feature_frames:
        raise ValueError(
            "No usable data after feature engineering. Check your date range and tickers."
        )

    all_features = pd.concat(feature_frames, axis=0).sort_values("date")

    X = all_features[cols].values.astype(float)
    y = all_features["target_up"].values.astype(int)
    meta = all_features[["ticker", "date"]].reset_index(drop=True)

    return X, y, meta


def latest_feature_rows_v2(
    universe_data: Dict[str, pd.DataFrame],
    feature_columns: List[str] | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return the latest feature row per ticker using V2 features.

    Args:
        universe_data: Mapping of ticker symbol to raw OHLCV DataFrame.
        feature_columns: Subset of columns to include. Defaults to
            ``FEATURE_COLUMNS_V2``.

    Returns:
        features_df: DataFrame indexed by ticker with the requested columns.
        meta_df: DataFrame with ``ticker`` and ``date`` columns.
    """
    cols = feature_columns if feature_columns is not None else FEATURE_COLUMNS_V2
    rows: List[pd.Series] = []
    meta_rows: List[Dict[str, str]] = []

    for ticker, df in universe_data.items():
        engineered = engineer_features_v2(df)
        if engineered.empty:
            continue
        latest = engineered.iloc[-1]
        rows.append(latest[cols])
        meta_rows.append({"ticker": ticker, "date": str(latest.name)})

    if not rows:
        raise ValueError(
            "No latest feature rows could be generated for any ticker."
        )

    features_df = pd.DataFrame(rows, index=[m["ticker"] for m in meta_rows])
    meta_df = pd.DataFrame(meta_rows)
    return features_df, meta_df


# ---------------------------------------------------------------------------
# Group lookup helper
# ---------------------------------------------------------------------------


def get_feature_group_columns(group_name: str) -> List[str]:
    """Return the list of feature column names belonging to a named group.

    Args:
        group_name: One of the keys in ``FEATURE_GROUPS``
            (trend, momentum, volatility, volume, multi_tf, price).

    Raises:
        KeyError: If the group name is not recognised.
    """
    if group_name not in FEATURE_GROUPS:
        raise KeyError(
            f"Unknown feature group '{group_name}'. "
            f"Available groups: {sorted(FEATURE_GROUPS.keys())}"
        )
    return list(FEATURE_GROUPS[group_name].columns)
