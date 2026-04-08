from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


# Core feature columns used by the model
FEATURE_COLUMNS: List[str] = [
    "open",
    "prev_close",
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "vol_5d",
    "ma_5d",
    "ma_10d",
    "ma_30d",
    "rsi_14d",
]


def _compute_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def engineer_features_for_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given a raw OHLCV DataFrame for a single ticker indexed by Date, produce
    a feature DataFrame with engineered technical features and a binary target:

    target_up = 1 if tomorrow's close > today's close, else 0.
    """
    # Normalize column names to lower snake case for consistency
    data = df.copy()
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

    # Some cached CSVs may contain non-numeric header rows in the first record.
    # Coerce all price/volume columns to numeric and drop rows that don't parse.
    numeric_cols = ["open", "high", "low", "close", "volume"]
    existing_numeric = [c for c in numeric_cols if c in data.columns]
    data[existing_numeric] = data[existing_numeric].apply(
        pd.to_numeric, errors="coerce"
    )
    data = data.dropna(subset=["close"])

    # --- Construct Technical Features ---
    data["prev_close"] = data["close"].shift(1)
    data["ret_1d"] = data["close"].pct_change(periods=1)
    data["ret_5d"] = data["close"].pct_change(periods=5)
    data["ret_10d"] = data["close"].pct_change(periods=10)

    data["vol_5d"] = data["high"].rolling(window=5).max() - data["low"].rolling(window=5).min()

    data["ma_5d"] = data["close"].rolling(window=5).mean()
    data["ma_10d"] = data["close"].rolling(window=10).mean()
    data["ma_30d"] = data["close"].rolling(window=30).mean()

    data["rsi_14d"] = _compute_rsi(data["close"], window=14)

    # Binary classification target: will tomorrow's close be higher than today's?
    data["target_up"] = (data["close"].shift(-1) > data["close"]).astype(int)

    # Drop rows with any NaNs (from rolling windows / shifts)
    data = data.dropna().copy()

    # We shift(-1) so the final row in real-time has no target yet. Keep it!
    # The original filtering explicitly removed it, which caused errors when generating latest features.
    # We will ONLY drop rows where 'target_up' is missing if we are building the training dataset,
    # but not when engineering features generally.
    
    return data


def build_universe_dataset(
    universe_data: Dict[str, pd.DataFrame],
) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """
    Turn a mapping ticker -> raw OHLCV DataFrame into:
      - X: feature matrix
      - y: binary labels (1 = tomorrow up, 0 = not up)
      - meta: DataFrame with columns [ticker, date] aligned with rows in X/y
    """
    feature_frames: List[pd.DataFrame] = []

    for ticker, df in universe_data.items():
        engineered = engineer_features_for_ticker(df)
        if engineered.empty:
            continue
        
        # Only for training: drop the rows where target_up is NaN
        engineered = engineered.dropna(subset=["target_up"]).copy()
        
        if engineered.empty:
            continue
            
        engineered["ticker"] = ticker
        engineered["date"] = engineered.index
        feature_frames.append(engineered)

    if not feature_frames:
        raise ValueError("No usable data after feature engineering. Check your date range and tickers.")

    all_features = pd.concat(feature_frames, axis=0).sort_values("date")

    X = all_features[FEATURE_COLUMNS].values.astype(float)
    y = all_features["target_up"].values.astype(int)
    meta = all_features[["ticker", "date"]].reset_index(drop=True)

    return X, y, meta


def latest_feature_rows_per_ticker(
    universe_data: Dict[str, pd.DataFrame],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    For each ticker, compute engineered features and return the *latest* row
    (most recent date) with features available.

    Returns:
      - features_df: DataFrame indexed by ticker with FEATURE_COLUMNS
      - meta_df: DataFrame with columns [ticker, date]
    """
    rows: List[pd.Series] = []
    meta_rows: List[dict] = []

    for ticker, df in universe_data.items():
        engineered = engineer_features_for_ticker(df)
        if engineered.empty:
            continue
        latest = engineered.iloc[-1]
        rows.append(latest[FEATURE_COLUMNS])
        meta_rows.append({"ticker": ticker, "date": latest.name})

    if not rows:
        raise ValueError("No latest feature rows could be generated for any ticker.")

    features_df = pd.DataFrame(rows, index=[m["ticker"] for m in meta_rows])
    meta_df = pd.DataFrame(meta_rows)
    return features_df, meta_df

