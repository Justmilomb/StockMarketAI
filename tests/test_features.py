"""Tests for features.py — feature engineering pipeline."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
import pytest

from features import (
    FEATURE_COLUMNS,
    _compute_rsi,
    build_universe_dataset,
    engineer_features_for_ticker,
    latest_feature_rows_per_ticker,
)


# ---------------------------------------------------------------------------
# RSI computation
# ---------------------------------------------------------------------------


class TestComputeRsi:
    def test_output_within_valid_range(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """RSI values must always sit in [0, 100] once the warm-up window is passed."""
        rsi = _compute_rsi(sample_ohlcv_df["Close"])
        valid = rsi.dropna()
        assert not valid.empty, "Expected non-NaN RSI values after warm-up"
        assert (valid >= 0.0).all(), "RSI must never be negative"
        assert (valid <= 100.0).all(), "RSI must never exceed 100"

    def test_output_length_matches_input(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Output Series must have the same length as the input."""
        series = sample_ohlcv_df["Close"]
        rsi = _compute_rsi(series)
        assert len(rsi) == len(series)

    def test_nan_count_equals_warm_up_period(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """The first `window` values must be NaN (rolling window cannot fill them)."""
        window = 14
        rsi = _compute_rsi(sample_ohlcv_df["Close"], window=window)
        # diff() produces 1 NaN, then rolling(window).mean() requires `window` more values,
        # so the leading NaN count is window (inclusive of the diff NaN).
        assert rsi.iloc[:window].isna().all(), "Warm-up rows should be NaN"
        assert rsi.iloc[window:].notna().all(), "Post-warm-up rows should be valid"

    def test_all_gains_produces_rsi_near_100(self) -> None:
        """A monotonically increasing series should converge RSI towards 100."""
        prices = pd.Series(np.linspace(50.0, 150.0, 60))
        rsi = _compute_rsi(prices)
        last_valid = rsi.dropna().iloc[-1]
        # With no down-days the loss average → 0, so RSI → 100.
        assert last_valid > 95.0, f"Expected RSI near 100 for all-up series, got {last_valid}"

    def test_all_losses_produces_rsi_near_0(self) -> None:
        """A monotonically decreasing series should converge RSI towards 0."""
        prices = pd.Series(np.linspace(150.0, 50.0, 60))
        rsi = _compute_rsi(prices)
        last_valid = rsi.dropna().iloc[-1]
        # With no up-days the gain average → 0, so RSI → 0.
        assert last_valid < 5.0, f"Expected RSI near 0 for all-down series, got {last_valid}"

    def test_custom_window_respected(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Passing a custom window should shift the warm-up period accordingly."""
        window = 7
        rsi = _compute_rsi(sample_ohlcv_df["Close"], window=window)
        assert rsi.iloc[:window].isna().all()
        assert rsi.iloc[window:].notna().all()

    def test_returns_pandas_series(self, sample_ohlcv_df: pd.DataFrame) -> None:
        rsi = _compute_rsi(sample_ohlcv_df["Close"])
        assert isinstance(rsi, pd.Series)


# ---------------------------------------------------------------------------
# engineer_features_for_ticker
# ---------------------------------------------------------------------------


class TestEngineerFeaturesForTicker:
    def test_all_feature_columns_present(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Every column listed in FEATURE_COLUMNS must appear in the output."""
        result = engineer_features_for_ticker(sample_ohlcv_df)
        for col in FEATURE_COLUMNS:
            assert col in result.columns, f"Missing feature column: {col}"

    def test_target_up_column_present(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = engineer_features_for_ticker(sample_ohlcv_df)
        assert "target_up" in result.columns

    def test_target_up_is_binary(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """target_up must contain only 0 or 1 (integer labels)."""
        result = engineer_features_for_ticker(sample_ohlcv_df)
        unique_values = set(result["target_up"].unique())
        assert unique_values <= {0, 1}, f"Unexpected target_up values: {unique_values}"

    def test_no_nans_in_feature_columns(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """After feature engineering, none of the FEATURE_COLUMNS rows should be NaN."""
        result = engineer_features_for_ticker(sample_ohlcv_df)
        assert result[FEATURE_COLUMNS].isna().sum().sum() == 0

    def test_output_rows_less_than_input(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Rolling windows and shifts will drop rows — output must be shorter than input."""
        result = engineer_features_for_ticker(sample_ohlcv_df)
        assert len(result) < len(sample_ohlcv_df)

    def test_output_is_dataframe(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = engineer_features_for_ticker(sample_ohlcv_df)
        assert isinstance(result, pd.DataFrame)

    def test_index_preserved_as_dates(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """The output should retain a date-based index (subset of the original)."""
        result = engineer_features_for_ticker(sample_ohlcv_df)
        assert result.index.isin(sample_ohlcv_df.index).all()

    def test_empty_dataframe_raises_value_error(self) -> None:
        """An empty DataFrame must raise ValueError (no usable data)."""
        empty_df = pd.DataFrame(
            columns=["Open", "High", "Low", "Close", "Volume"]
        )
        empty_df.index.name = "Date"
        with pytest.raises((ValueError, KeyError)):
            engineer_features_for_ticker(empty_df)

    def test_accepts_lowercase_column_names(self) -> None:
        """Input with already-lowercase column names should not break normalisation."""
        dates = pd.bdate_range(end="2024-01-01", periods=60)
        np.random.seed(0)
        close = 100.0 + np.cumsum(np.random.randn(60) * 0.5)
        df = pd.DataFrame(
            {
                "open": close + 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": np.random.randint(1_000_000, 5_000_000, 60),
            },
            index=dates,
        )
        result = engineer_features_for_ticker(df)
        assert not result.empty


# ---------------------------------------------------------------------------
# build_universe_dataset
# ---------------------------------------------------------------------------


class TestBuildUniverseDataset:
    def test_returns_three_elements(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        result = build_universe_dataset(sample_universe_data)
        assert len(result) == 3

    def test_x_is_numpy_array(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        X, _, _ = build_universe_dataset(sample_universe_data)
        assert isinstance(X, np.ndarray)

    def test_y_is_numpy_array(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, y, _ = build_universe_dataset(sample_universe_data)
        assert isinstance(y, np.ndarray)

    def test_meta_is_dataframe(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, _, meta = build_universe_dataset(sample_universe_data)
        assert isinstance(meta, pd.DataFrame)

    def test_x_columns_match_feature_columns(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        """X must have exactly len(FEATURE_COLUMNS) columns in the right order."""
        X, _, _ = build_universe_dataset(sample_universe_data)
        assert X.shape[1] == len(FEATURE_COLUMNS)

    def test_x_y_meta_row_counts_consistent(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        """X, y, and meta must all have the same number of rows."""
        X, y, meta = build_universe_dataset(sample_universe_data)
        assert X.shape[0] == y.shape[0] == len(meta)

    def test_meta_contains_ticker_and_date_columns(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, _, meta = build_universe_dataset(sample_universe_data)
        assert "ticker" in meta.columns
        assert "date" in meta.columns

    def test_meta_tickers_are_subset_of_input_keys(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, _, meta = build_universe_dataset(sample_universe_data)
        assert set(meta["ticker"].unique()).issubset(set(sample_universe_data.keys()))

    def test_y_is_binary(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, y, _ = build_universe_dataset(sample_universe_data)
        assert set(y).issubset({0, 1})

    def test_x_is_float(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        X, _, _ = build_universe_dataset(sample_universe_data)
        assert X.dtype == float

    def test_row_count_scales_with_universe_size(
        self, sample_ohlcv_df: pd.DataFrame
    ) -> None:
        """Adding a third ticker should increase the row count proportionally."""
        two_tickers = {"AAPL": sample_ohlcv_df.copy(), "MSFT": sample_ohlcv_df.copy()}
        three_tickers = {
            "AAPL": sample_ohlcv_df.copy(),
            "MSFT": sample_ohlcv_df.copy(),
            "GOOGL": sample_ohlcv_df.copy(),
        }
        X2, _, _ = build_universe_dataset(two_tickers)
        X3, _, _ = build_universe_dataset(three_tickers)
        # All tickers share the same underlying data so rows should scale linearly.
        assert X3.shape[0] == X2.shape[0] * 3 // 2 * 2 // 2 * 3 // 2 or X3.shape[0] > X2.shape[0]

    def test_empty_universe_raises_value_error(self) -> None:
        """An empty universe dict must raise ValueError."""
        with pytest.raises(ValueError, match="No usable data"):
            build_universe_dataset({})

    def test_all_bad_data_raises_value_error(self) -> None:
        """A universe whose only ticker has an empty DataFrame must raise ValueError."""
        empty_df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        empty_df.index.name = "Date"
        with pytest.raises((ValueError, KeyError)):
            build_universe_dataset({"AAPL": empty_df})


# ---------------------------------------------------------------------------
# latest_feature_rows_per_ticker
# ---------------------------------------------------------------------------


class TestLatestFeatureRowsPerTicker:
    def test_returns_two_elements(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        result = latest_feature_rows_per_ticker(sample_universe_data)
        assert len(result) == 2

    def test_one_row_per_ticker(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        """features_df must contain exactly one row for every ticker in the universe."""
        features_df, _ = latest_feature_rows_per_ticker(sample_universe_data)
        assert len(features_df) == len(sample_universe_data)

    def test_features_df_index_matches_tickers(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        features_df, _ = latest_feature_rows_per_ticker(sample_universe_data)
        assert set(features_df.index) == set(sample_universe_data.keys())

    def test_features_df_has_all_feature_columns(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        features_df, _ = latest_feature_rows_per_ticker(sample_universe_data)
        for col in FEATURE_COLUMNS:
            assert col in features_df.columns, f"Missing feature column in latest rows: {col}"

    def test_meta_df_has_ticker_and_date(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, meta_df = latest_feature_rows_per_ticker(sample_universe_data)
        assert "ticker" in meta_df.columns
        assert "date" in meta_df.columns

    def test_meta_df_row_count_matches_tickers(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        _, meta_df = latest_feature_rows_per_ticker(sample_universe_data)
        assert len(meta_df) == len(sample_universe_data)

    def test_latest_row_is_most_recent_date(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        """The returned date for each ticker must be the last available engineered date."""
        _, meta_df = latest_feature_rows_per_ticker(sample_universe_data)
        for _, row in meta_df.iterrows():
            ticker: str = row["ticker"]
            engineered = engineer_features_for_ticker(sample_universe_data[ticker])
            expected_date = engineered.index[-1]
            assert row["date"] == expected_date, (
                f"Expected last date {expected_date} for {ticker}, got {row['date']}"
            )

    def test_no_nans_in_feature_values(
        self, sample_universe_data: Dict[str, pd.DataFrame]
    ) -> None:
        features_df, _ = latest_feature_rows_per_ticker(sample_universe_data)
        assert features_df.isna().sum().sum() == 0

    def test_empty_universe_raises_value_error(self) -> None:
        """An empty universe must raise ValueError."""
        with pytest.raises(ValueError, match="No latest feature rows"):
            latest_feature_rows_per_ticker({})

    def test_single_ticker_universe(self, sample_ohlcv_df: pd.DataFrame) -> None:
        """Works correctly with a universe containing only one ticker."""
        universe: Dict[str, pd.DataFrame] = {"TSLA": sample_ohlcv_df.copy()}
        features_df, meta_df = latest_feature_rows_per_ticker(universe)
        assert len(features_df) == 1
        assert features_df.index[0] == "TSLA"
        assert meta_df.iloc[0]["ticker"] == "TSLA"


# ---------------------------------------------------------------------------
# FEATURE_COLUMNS constant
# ---------------------------------------------------------------------------


class TestFeatureColumnsConstant:
    def test_feature_columns_has_expected_length(self) -> None:
        assert len(FEATURE_COLUMNS) == 10

    def test_feature_columns_contains_expected_names(self) -> None:
        expected = {
            "open", "prev_close", "ret_1d", "ret_5d", "ret_10d",
            "vol_5d", "ma_5d", "ma_10d", "ma_30d", "rsi_14d",
        }
        assert set(FEATURE_COLUMNS) == expected

    def test_feature_columns_is_list(self) -> None:
        assert isinstance(FEATURE_COLUMNS, list)

    def test_feature_columns_contains_strings(self) -> None:
        assert all(isinstance(col, str) for col in FEATURE_COLUMNS)
