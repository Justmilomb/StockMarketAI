"""Core backtest engine — runs one walk-forward fold.

Two modes:
    fast — train ensemble, predict test period, measure accuracy (no trades)
    full — same + day-by-day trade simulation with P&L and stops

Each fold is self-contained and can run in a separate process.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backtesting.data_prep import get_price_data_for_dates, split_data_for_fold
from backtesting.simulator import TradeSimulator
from backtesting.types import (
    BacktestConfig,
    DailySnapshot,
    FoldResult,
    TradeRecord,
    WalkForwardSplit,
)

logger = logging.getLogger(__name__)


def _get_n_jobs() -> int:
    """Lazy import — uses fold-aware n_jobs to avoid over-subscribing CPU."""
    from cpu_config import get_n_jobs_per_fold
    return get_n_jobs_per_fold()


class BacktestEngine:
    """Runs backtests for individual walk-forward folds."""

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_fold(
        self,
        split: WalkForwardSplit,
        features_by_ticker: Dict[str, pd.DataFrame],
        labels_by_ticker: Dict[str, pd.Series],
        universe_data: Dict[str, pd.DataFrame],
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> FoldResult:
        """Execute one complete walk-forward fold.

        1. Split data into train/test
        2. Train ensemble on training data
        3. Predict test data
        4. (Full mode) Simulate trades day-by-day
        5. Compute fold-level metrics
        """
        if on_progress:
            on_progress(f"Fold {split.fold_id}: splitting data")

        train_feats, train_labels, test_feats, test_labels = split_data_for_fold(
            features_by_ticker, labels_by_ticker, split,
        )

        if not train_feats or not test_feats:
            return _empty_fold(split)

        # -- Train ensemble for this fold ------------------------------------
        if on_progress:
            on_progress(f"Fold {split.fold_id}: training ensemble")

        ensemble, feature_cols = self._train_fold_ensemble(train_feats, train_labels)
        if ensemble is None:
            return _empty_fold(split)

        # -- Predict test period ---------------------------------------------
        if on_progress:
            on_progress(f"Fold {split.fold_id}: predicting test period")

        predictions, actuals = self._predict_test_period(
            ensemble, feature_cols, test_feats, test_labels,
        )

        # -- Compute fast-mode metrics (accuracy) ----------------------------
        all_preds: List[float] = []
        all_actual: List[int] = []
        for day_preds, day_actuals in zip(predictions, actuals):
            for ticker in day_preds:
                if ticker in day_actuals:
                    all_preds.append(day_preds[ticker])
                    all_actual.append(1 if day_actuals[ticker] else 0)

        n_predictions = len(all_preds)
        if n_predictions > 0:
            pred_binary = [1 if p > 0.5 else 0 for p in all_preds]
            n_correct = sum(1 for p, a in zip(pred_binary, all_actual) if p == a)
            accuracy = n_correct / n_predictions

            # Precision: of those we predicted UP, how many actually went up
            predicted_up = [(p, a) for p, a in zip(pred_binary, all_actual) if p == 1]
            precision = (
                sum(1 for _, a in predicted_up if a == 1) / len(predicted_up)
                if predicted_up else 0.0
            )

            # Recall: of those that went up, how many did we predict UP
            actual_up = [(p, a) for p, a in zip(pred_binary, all_actual) if a == 1]
            recall = (
                sum(1 for p, _ in actual_up if p == 1) / len(actual_up)
                if actual_up else 0.0
            )
        else:
            accuracy = precision = recall = 0.0
            n_correct = 0

        # -- Full mode: day-by-day trade simulation --------------------------
        trades: List[TradeRecord] = []
        snapshots: List[DailySnapshot] = []

        if self._config.mode == "full":
            tiers = self._config.capital_tiers or [self._config.initial_capital]
            original_capital = self._config.initial_capital

            for i, tier_capital in enumerate(tiers):
                if on_progress:
                    on_progress(f"Fold {split.fold_id}: simulating trades (£{tier_capital:,.0f})")

                self._config.initial_capital = tier_capital

                tier_trades, tier_snapshots = self._simulate_trades(
                    split, predictions, test_feats, universe_data,
                )

                for t in tier_trades:
                    t.capital_tier = tier_capital

                trades.extend(tier_trades)
                # Only use first tier's snapshots for equity curve metrics
                if i == 0:
                    snapshots = tier_snapshots

            self._config.initial_capital = original_capital

        return FoldResult(
            fold_id=split.fold_id,
            split=split,
            trades=trades,
            daily_snapshots=snapshots,
            predictions=predictions,
            actuals=actuals,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            n_predictions=n_predictions,
            n_correct=n_correct,
        )

    # ------------------------------------------------------------------
    # Internal: training
    # ------------------------------------------------------------------

    def _train_fold_ensemble(
        self,
        train_feats: Dict[str, pd.DataFrame],
        train_labels: Dict[str, pd.Series],
    ) -> Tuple[Any, List[str]]:
        """Train a fresh ensemble on training data for this fold.

        Returns (trained_model, feature_columns) or (None, []) on failure.
        """
        from features_advanced import FEATURE_COLUMNS_V2

        # Stack all tickers into one training set
        X_parts: List[np.ndarray] = []
        y_parts: List[np.ndarray] = []

        for ticker in train_feats:
            feat_df = train_feats[ticker]
            label_s = train_labels[ticker]

            # Align indices
            common_idx = feat_df.index.intersection(label_s.index)
            if len(common_idx) < 10:
                continue

            X_parts.append(feat_df.loc[common_idx].values)
            y_parts.append(label_s.loc[common_idx].values)

        if not X_parts:
            return None, []

        X = np.vstack(X_parts)
        y = np.concatenate(y_parts)

        feature_cols = list(train_feats[next(iter(train_feats))].columns)

        try:
            from ensemble import EnsembleModel
            from types_shared import EnsembleConfig

            # Build a meta DataFrame with ticker/date info for the ensemble
            meta_rows: List[Dict[str, Any]] = []
            for ticker in train_feats:
                feat_df = train_feats[ticker]
                label_s = train_labels[ticker]
                common_idx = feat_df.index.intersection(label_s.index)
                for idx_val in common_idx:
                    meta_rows.append({"ticker": ticker, "date": idx_val})
            meta_df = pd.DataFrame(meta_rows)

            ens_config = EnsembleConfig(
                n_models=self.config.ensemble_n_models,
                stacking_enabled=self.config.ensemble_stacking,
                model_dir="",
            )
            model = EnsembleModel(ens_config, model_overrides={
                "rf_n_estimators": self.config.rf_n_estimators,
                "rf_max_depth": self.config.rf_max_depth,
                "xgb_n_estimators": self.config.xgb_n_estimators,
                "xgb_max_depth": self.config.xgb_max_depth,
                "xgb_learning_rate": self.config.xgb_learning_rate,
                "lgbm_n_estimators": self.config.lgbm_n_estimators,
                "lgbm_num_leaves": self.config.lgbm_num_leaves,
                "knn_n_neighbors": self.config.knn_n_neighbors,
            })
            model.train(X, y, meta_df, feature_cols)
            return model, feature_cols
        except Exception as e:
            logger.warning("Ensemble training failed in fold: %s", e)
            # Fallback: simple sklearn ensemble
            return self._train_simple_ensemble(X, y, feature_cols)

    def _train_simple_ensemble(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_cols: List[str],
    ) -> Tuple[Any, List[str]]:
        """Fallback: train a simple RandomForest + LogisticRegression pair."""
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression

        class SimpleEnsemble:
            def __init__(self) -> None:
                self.models = [
                    RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42, n_jobs=_get_n_jobs()),
                    GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42),
                    LogisticRegression(max_iter=500, random_state=42),
                ]
                self._trained = False

            def train(self, X: np.ndarray, y: np.ndarray) -> None:
                for m in self.models:
                    m.fit(X, y)
                self._trained = True

            def predict_proba(self, X: np.ndarray) -> np.ndarray:
                if not self._trained:
                    return np.full(len(X), 0.5)
                probs = np.stack([m.predict_proba(X)[:, 1] for m in self.models])
                return probs.mean(axis=0)

        try:
            model = SimpleEnsemble()
            model.train(X, y)
            return model, feature_cols
        except Exception as e:
            logger.error("Simple ensemble training also failed: %s", e)
            return None, []

    # ------------------------------------------------------------------
    # Internal: prediction
    # ------------------------------------------------------------------

    def _predict_test_period(
        self,
        ensemble: Any,
        feature_cols: List[str],
        test_feats: Dict[str, pd.DataFrame],
        test_labels: Dict[str, pd.Series],
    ) -> Tuple[List[Dict[str, float]], List[Dict[str, bool]]]:
        """Generate per-day predictions for the test period.

        Supports both the real EnsembleModel (predict_ensemble) and the
        SimpleEnsemble fallback (predict_proba).

        Returns:
            predictions: [{ticker: prob_up}, ...] one dict per day
            actuals:     [{ticker: went_up}, ...] one dict per day
        """
        use_full_ensemble = hasattr(ensemble, "predict_ensemble")

        # Collect all test dates (sorted)
        all_dates: set = set()
        for feat_df in test_feats.values():
            all_dates.update(feat_df.index)
        sorted_dates = sorted(all_dates)

        predictions: List[Dict[str, float]] = []
        actuals: List[Dict[str, bool]] = []

        for d in sorted_dates:
            day_preds: Dict[str, float] = {}
            day_actuals: Dict[str, bool] = {}

            if use_full_ensemble:
                # Batch prediction: build a DataFrame indexed by ticker
                day_rows: List[pd.Series] = []
                day_tickers: List[str] = []
                for ticker in test_feats:
                    feat_df = test_feats[ticker]
                    if d not in feat_df.index:
                        continue
                    row = feat_df.loc[d].copy()
                    row.name = ticker
                    day_rows.append(row)
                    day_tickers.append(ticker)

                if day_rows:
                    feat_batch = pd.DataFrame(day_rows, index=day_tickers)
                    meta_batch = pd.DataFrame({"ticker": day_tickers})
                    try:
                        probs, _ = ensemble.predict_ensemble(feat_batch, meta_batch)
                        for i, ticker in enumerate(day_tickers):
                            day_preds[ticker] = float(probs[i])
                    except Exception as e:
                        logger.debug("Ensemble batch predict failed for day %s: %s", d, e)

                # Collect actuals
                for ticker in day_tickers:
                    label_s = test_labels[ticker]
                    if d in label_s.index:
                        day_actuals[ticker] = bool(label_s.loc[d])
            else:
                # SimpleEnsemble fallback: row-by-row predict_proba
                for ticker in test_feats:
                    feat_df = test_feats[ticker]
                    label_s = test_labels[ticker]
                    if d not in feat_df.index:
                        continue
                    try:
                        X_row = feat_df.loc[[d]].values
                        prob = float(ensemble.predict_proba(X_row)[0])
                        day_preds[ticker] = prob
                        if d in label_s.index:
                            day_actuals[ticker] = bool(label_s.loc[d])
                    except Exception:
                        continue

            if day_preds:
                predictions.append(day_preds)
                actuals.append(day_actuals)

        return predictions, actuals

    # ------------------------------------------------------------------
    # Internal: trade simulation
    # ------------------------------------------------------------------

    def _simulate_trades(
        self,
        split: WalkForwardSplit,
        predictions: List[Dict[str, float]],
        test_feats: Dict[str, pd.DataFrame],
        universe_data: Dict[str, pd.DataFrame],
    ) -> Tuple[List[TradeRecord], List[DailySnapshot]]:
        """Run day-by-day trade simulation for one fold."""
        # Get price data for the test period
        price_data = get_price_data_for_dates(universe_data, split.test_start, split.test_end)

        # Get sorted test dates
        all_dates: set = set()
        for feat_df in test_feats.values():
            idx = feat_df.index
            dates = idx.date if hasattr(idx, 'date') else idx
            for d in dates:
                if split.test_start <= (d if isinstance(d, date) else d.date()) <= split.test_end:
                    all_dates.add(d if isinstance(d, date) else d.date())
        sorted_dates = sorted(all_dates)

        if not sorted_dates:
            return [], []

        # -- Per-ticker strategy overrides (regime-aware) -------------------
        per_ticker_overrides: Dict[str, Dict[str, float]] | None = None

        if self._config.use_strategy_selector:
            try:
                from strategy_selector import StrategySelector
                from strategy_profiles import DEFAULT_PROFILES, REGIME_DEFAULT_MAPPING
                from types_shared import RegimeState, ConsensusResult

                # Detect regime from training-period data
                regime_str = self._detect_simple_regime(universe_data, split.train_end)
                # Map range_bound -> mean_reverting for consistency with types_shared
                if regime_str == "range_bound":
                    regime_str = "mean_reverting"

                regime_state = RegimeState(
                    regime=regime_str,
                    confidence=0.6,  # moderate confidence for backtest regime detection
                    vix_proxy=0.0,
                    breadth=0.0,
                    trend_strength=0.0,
                )

                # Build synthetic ConsensusResult per ticker from test predictions
                consensus_dict: Dict[str, ConsensusResult] = {}
                for ticker in test_feats:
                    probs = [
                        day_preds.get(ticker, 0.5)
                        for day_preds in predictions
                        if ticker in day_preds
                    ]
                    avg_prob = sum(probs) / len(probs) if probs else 0.5
                    consensus_dict[ticker] = ConsensusResult(
                        ticker=ticker,
                        probability=avg_prob,
                        consensus_pct=avg_prob * 100,
                        confidence=0.5,
                        signal_strength=abs(avg_prob - 0.5) * 2,
                        disagreement=0.2,
                        bull_count=5 if avg_prob > 0.5 else 2,
                        bear_count=2 if avg_prob > 0.5 else 5,
                    )

                selector = StrategySelector(
                    profiles=DEFAULT_PROFILES,
                    capital=self._config.initial_capital,
                )
                assignments = selector.select_strategies(regime_state, consensus_dict)

                per_ticker_overrides = {}
                for ticker, assignment in assignments.items():
                    p = assignment.profile
                    per_ticker_overrides[ticker] = {
                        "threshold_buy": p.threshold_buy,
                        "threshold_sell": p.threshold_sell,
                        "position_size_fraction": p.position_size_fraction,
                        "atr_stop_multiplier": p.atr_stop_multiplier,
                        "atr_profit_multiplier": p.atr_profit_multiplier,
                        "max_positions": p.max_positions,
                        "strategy_profile": p.name,
                    }

            except Exception as e:
                logger.warning("Strategy selector failed in fold %d: %s", split.fold_id, e)
                per_ticker_overrides = None

        sim = TradeSimulator(self._config, per_ticker_overrides=per_ticker_overrides)

        for day_idx, day_date in enumerate(sorted_dates):
            if day_idx >= len(predictions):
                break

            day_signals = predictions[day_idx]

            # Build price dict for this day
            day_prices: Dict[str, Dict[str, float]] = {}
            atr_values: Dict[str, float] = {}

            for ticker in day_signals:
                if ticker not in price_data:
                    continue

                ticker_df = price_data[ticker]
                # Find this date's row
                day_mask = _date_mask(ticker_df.index, day_date)
                day_rows = ticker_df.loc[day_mask]

                if day_rows.empty:
                    continue

                row = day_rows.iloc[0]
                try:
                    day_prices[ticker] = {
                        "open": float(pd.to_numeric(row["Open"], errors="coerce")),
                        "high": float(pd.to_numeric(row["High"], errors="coerce")),
                        "low": float(pd.to_numeric(row["Low"], errors="coerce")),
                        "close": float(pd.to_numeric(row["Close"], errors="coerce")),
                    }
                except (ValueError, TypeError):
                    continue  # Skip corrupted price data

                # ATR from recent data
                atr = _compute_atr(ticker_df, day_date, period=14)
                atr_values[ticker] = atr

            if day_prices:
                sim.process_day(day_date, day_prices, day_signals, atr_values)

        # Close remaining positions at end of fold
        last_prices: Dict[str, Dict[str, float]] = {}
        for ticker in price_data:
            df = price_data[ticker]
            if not df.empty:
                last_row = df.iloc[-1]
                try:
                    last_prices[ticker] = {
                        "open": float(pd.to_numeric(last_row["Open"], errors="coerce")),
                        "high": float(pd.to_numeric(last_row["High"], errors="coerce")),
                        "low": float(pd.to_numeric(last_row["Low"], errors="coerce")),
                        "close": float(pd.to_numeric(last_row["Close"], errors="coerce")),
                    }
                except (ValueError, TypeError):
                    continue  # Skip tickers with corrupted price data
        if last_prices:
            sim.close_all_positions(sorted_dates[-1], last_prices)

        return sim.trades, sim.snapshots


    @staticmethod
    def _detect_simple_regime(
        universe_data: Dict[str, pd.DataFrame],
        as_of: date,
    ) -> str:
        """Simple regime detection from price data (no RegimeDetector dependency).

        Looks at a broad market proxy or average of all tickers to classify
        the regime as trending_up, trending_down, or range_bound.
        """
        returns_all: List[float] = []
        for df in universe_data.values():
            idx = df.index
            if hasattr(idx, 'date'):
                mask = idx.date <= as_of
            else:
                mask = idx <= pd.Timestamp(as_of)
            sliced = df.loc[mask]
            if len(sliced) < 60:
                continue
            closes = pd.to_numeric(sliced["Close"], errors="coerce").dropna().values[-60:]
            if len(closes) < 10:
                continue
            rets = np.diff(closes) / np.maximum(closes[:-1], 1e-8)
            returns_all.extend(rets.tolist())

        if not returns_all:
            return "unknown"

        avg_return = float(np.mean(returns_all))
        vol = float(np.std(returns_all))

        if avg_return > 0.001 and vol < 0.025:
            return "trending_up"
        elif avg_return < -0.001 and vol < 0.025:
            return "trending_down"
        elif vol >= 0.025:
            return "high_volatility"
        else:
            return "range_bound"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_mask(index: pd.Index, target: date) -> pd.Series:
    """Create a boolean mask matching a specific date in a DatetimeIndex."""
    if hasattr(index, 'date'):
        return index.date == target
    return index == pd.Timestamp(target)


def _compute_atr(df: pd.DataFrame, up_to_date: date, period: int = 14) -> float:
    """Compute ATR for a ticker up to a given date."""
    mask = _date_mask(df.index, up_to_date)
    idx = df.index.get_indexer(df.index[mask])
    if len(idx) == 0:
        fallback = pd.to_numeric(df["Close"].iloc[-1], errors="coerce")
        return (float(fallback) * 0.02) if pd.notna(fallback) else 0.0

    end_pos = idx[0]
    start_pos = max(0, end_pos - period)
    sub = df.iloc[start_pos:end_pos + 1]

    if len(sub) < 2:
        fallback = pd.to_numeric(df["Close"].iloc[-1], errors="coerce")
        return (float(fallback) * 0.02) if pd.notna(fallback) else 0.0

    highs = pd.to_numeric(sub["High"], errors="coerce").values
    lows = pd.to_numeric(sub["Low"], errors="coerce").values
    closes = pd.to_numeric(sub["Close"], errors="coerce").values

    # Skip if any NaNs from coercion
    if np.isnan(highs).any() or np.isnan(lows).any() or np.isnan(closes).any():
        return float(np.nanmean(closes)) * 0.02 if len(closes) > 0 else 0.0

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    return float(np.mean(tr)) if len(tr) > 0 else float(closes[-1]) * 0.02


def _empty_fold(split: WalkForwardSplit) -> FoldResult:
    """Return an empty fold result when data is insufficient."""
    return FoldResult(
        fold_id=split.fold_id,
        split=split,
        trades=[],
        daily_snapshots=[],
        predictions=[],
        actuals=[],
    )
