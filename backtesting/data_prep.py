"""Data preparation for backtesting — pre-computes features and labels
for the entire historical period, then generates walk-forward splits.

All heavy lifting is done upfront so the backtest loop only indexes into
pre-computed arrays.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from backtesting.types import BacktestConfig, WalkForwardSplit

logger = logging.getLogger(__name__)


def prepare_backtest_data(
    universe_data: Dict[str, pd.DataFrame],
    config: BacktestConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series]]:
    """Pre-compute features and labels for every ticker across full history.

    Routes to daily or intraday feature engineering based on
    ``config.bar_interval``.

    Returns:
        features_by_ticker: {ticker: DataFrame of features indexed by date}
        labels_by_ticker:   {ticker: Series of binary labels indexed by date}
    """
    is_intraday = config.bar_interval != "1d"

    if is_intraday:
        return _prepare_intraday(universe_data, config)
    return _prepare_daily(universe_data, config)


def _prepare_daily(
    universe_data: Dict[str, pd.DataFrame],
    config: BacktestConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series]]:
    """Daily feature engineering (original path)."""
    from features_advanced import FEATURE_COLUMNS_V2, engineer_features_v2

    features_by_ticker: Dict[str, pd.DataFrame] = {}
    labels_by_ticker: Dict[str, pd.Series] = {}

    for ticker, df in universe_data.items():
        if len(df) < 60:
            logger.warning("Skipping %s — only %d bars (need 60+)", ticker, len(df))
            continue

        try:
            feat_df = engineer_features_v2(df)
            if feat_df.empty:
                continue

            # Align columns to V2 spec — fill missing with NaN then drop
            for col in FEATURE_COLUMNS_V2:
                if col not in feat_df.columns:
                    feat_df[col] = np.nan
            feat_df = feat_df[FEATURE_COLUMNS_V2].dropna()

            if len(feat_df) < 60:
                continue

            # Labels: did next day's close go up?
            closes = df["Close"].reindex(feat_df.index)
            next_close = closes.shift(-1)
            labels = (next_close > closes).astype(int)
            labels = labels.iloc[:-1]  # Last row has no next-day label
            feat_df = feat_df.iloc[:-1]

            features_by_ticker[ticker] = feat_df
            labels_by_ticker[ticker] = labels

        except Exception as e:
            logger.warning("Feature computation failed for %s: %s", ticker, e)
            continue

    logger.info(
        "Prepared %d tickers, %d total feature rows",
        len(features_by_ticker),
        sum(len(f) for f in features_by_ticker.values()),
    )
    return features_by_ticker, labels_by_ticker


def _prepare_intraday(
    universe_data: Dict[str, pd.DataFrame],
    config: BacktestConfig,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.Series]]:
    """Intraday feature engineering for minute/hour bars."""
    from features_intraday import FEATURE_COLUMNS_INTRADAY, engineer_intraday_features

    interval_map = {"1Min": 1, "5Min": 5, "15Min": 15, "30Min": 30, "1Hour": 60}
    interval_minutes = interval_map.get(config.bar_interval, 5)
    horizon = config.target_horizon_bars

    features_by_ticker: Dict[str, pd.DataFrame] = {}
    labels_by_ticker: Dict[str, pd.Series] = {}

    for ticker, df in universe_data.items():
        if len(df) < 200:
            logger.warning("Skipping %s — only %d intraday bars (need 200+)", ticker, len(df))
            continue

        try:
            feat_df = engineer_intraday_features(df, interval_minutes, horizon)
            if feat_df.empty:
                continue

            # Align to intraday feature spec
            for col in FEATURE_COLUMNS_INTRADAY:
                if col not in feat_df.columns:
                    feat_df[col] = np.nan
            feat_cols = [c for c in FEATURE_COLUMNS_INTRADAY if c in feat_df.columns]
            feat_df = feat_df[feat_cols].dropna()

            if len(feat_df) < 200:
                continue

            # Labels from engineer_intraday_features already set target_up
            closes = df["Close"].reindex(feat_df.index) if "Close" in df.columns else df["close"].reindex(feat_df.index)
            next_close = closes.shift(-horizon)
            labels = (next_close > closes).astype(int)
            labels = labels.reindex(feat_df.index).dropna().astype(int)
            # Trim to common index
            common_idx = feat_df.index.intersection(labels.index)
            feat_df = feat_df.loc[common_idx]
            labels = labels.loc[common_idx]

            features_by_ticker[ticker] = feat_df
            labels_by_ticker[ticker] = labels

        except Exception as e:
            logger.warning("Intraday feature computation failed for %s: %s", ticker, e)
            continue

    logger.info(
        "Prepared %d tickers (intraday %s), %d total bars",
        len(features_by_ticker), config.bar_interval,
        sum(len(f) for f in features_by_ticker.values()),
    )
    return features_by_ticker, labels_by_ticker


def generate_walk_forward_splits(
    features_by_ticker: Dict[str, pd.DataFrame],
    config: BacktestConfig,
) -> List[WalkForwardSplit]:
    """Generate walk-forward train/test splits.

    For expanding window:
        Fold 0: train [start .. start + min_train], test [.. + test_window]
        Fold 1: train [start .. start + min_train + step], test [.. + test_window]
        ...until test_end exceeds data range

    For rolling window:
        Same but train_start also slides forward by step_days.
    """
    # Find the common date range across all tickers
    all_dates: set[date] = set()
    for feat_df in features_by_ticker.values():
        all_dates.update(feat_df.index.date if hasattr(feat_df.index, 'date') else feat_df.index)

    if not all_dates:
        return []

    sorted_dates = sorted(all_dates)
    data_start = sorted_dates[0]
    data_end = sorted_dates[-1]

    min_train = config.min_train_days
    test_window = config.test_window_days
    step = config.step_days

    splits: List[WalkForwardSplit] = []
    fold_id = 0

    train_start = data_start
    train_end_offset = min_train

    while True:
        # Compute dates using trading day indices
        if train_end_offset >= len(sorted_dates):
            break

        train_end = sorted_dates[min(train_end_offset, len(sorted_dates) - 1)]

        test_start_idx = train_end_offset + 1
        test_end_idx = test_start_idx + test_window - 1

        if test_start_idx >= len(sorted_dates):
            break

        test_start = sorted_dates[test_start_idx]
        test_end = sorted_dates[min(test_end_idx, len(sorted_dates) - 1)]

        actual_test_days = min(test_end_idx, len(sorted_dates) - 1) - test_start_idx + 1
        if actual_test_days < 5:
            break

        if not config.expanding_window:
            # Rolling window: train_start also moves forward
            roll_start_idx = max(0, train_end_offset - min_train)
            train_start = sorted_dates[roll_start_idx]

        actual_train_days = train_end_offset - sorted_dates.index(train_start) + 1 if train_start in sorted_dates else train_end_offset

        splits.append(WalkForwardSplit(
            fold_id=fold_id,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_days=train_end_offset + 1,
            test_days=actual_test_days,
        ))

        fold_id += 1
        train_end_offset += step

    logger.info(
        "Generated %d walk-forward folds (train_min=%d, test=%d, step=%d)",
        len(splits), min_train, test_window, step,
    )
    return splits


def split_data_for_fold(
    features_by_ticker: Dict[str, pd.DataFrame],
    labels_by_ticker: Dict[str, pd.Series],
    split: WalkForwardSplit,
) -> Tuple[
    Dict[str, pd.DataFrame],  # train features per ticker
    Dict[str, pd.Series],     # train labels per ticker
    Dict[str, pd.DataFrame],  # test features per ticker
    Dict[str, pd.Series],     # test labels per ticker
]:
    """Slice pre-computed features/labels for one walk-forward fold."""
    train_feats: Dict[str, pd.DataFrame] = {}
    train_labels: Dict[str, pd.Series] = {}
    test_feats: Dict[str, pd.DataFrame] = {}
    test_labels: Dict[str, pd.Series] = {}

    for ticker in features_by_ticker:
        feat_df = features_by_ticker[ticker]
        label_s = labels_by_ticker[ticker]

        # Convert index to date if datetime
        idx = feat_df.index
        if hasattr(idx, 'date'):
            dates = idx.date
        else:
            dates = idx

        train_mask = (dates >= split.train_start) & (dates <= split.train_end)
        test_mask = (dates >= split.test_start) & (dates <= split.test_end)

        tr_f = feat_df.loc[train_mask]
        tr_l = label_s.loc[train_mask]
        te_f = feat_df.loc[test_mask]
        te_l = label_s.loc[test_mask]

        if len(tr_f) >= 30 and len(te_f) >= 1:
            train_feats[ticker] = tr_f
            train_labels[ticker] = tr_l
            test_feats[ticker] = te_f
            test_labels[ticker] = te_l

    return train_feats, train_labels, test_feats, test_labels


def get_price_data_for_dates(
    universe_data: Dict[str, pd.DataFrame],
    start: date,
    end: date,
) -> Dict[str, pd.DataFrame]:
    """Extract OHLCV data for a date range (used by trade simulator for stops/fills)."""
    result: Dict[str, pd.DataFrame] = {}
    for ticker, df in universe_data.items():
        idx = df.index
        if hasattr(idx, 'date'):
            mask = (idx.date >= start) & (idx.date <= end)
        else:
            mask = (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))
        sliced = df.loc[mask]
        if not sliced.empty:
            result[ticker] = sliced
    return result
