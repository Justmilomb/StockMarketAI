"""Core backtest engine — runs one walk-forward fold.

Two modes:
    fast — train ensemble, predict test period, measure accuracy (no trades)
    full — same + day-by-day trade simulation with P&L and stops

Each fold is self-contained and can run in a separate process.
Optionally runs MiroFish multi-agent simulation per fold for realistic
signal blending that matches the live terminal pipeline.
"""

from __future__ import annotations

import json
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

        # -- MiroFish blending (if enabled) ---------------------------------
        if self._config.use_mirofish and predictions:
            if on_progress:
                on_progress(f"Fold {split.fold_id}: running per-day MiroFish")

            predictions = self._run_mirofish_per_day(
                split, test_feats, universe_data, predictions, on_progress,
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
            if on_progress:
                on_progress(f"Fold {split.fold_id}: simulating trades")

            trades, snapshots = self._simulate_trades(
                split, predictions, test_feats, universe_data,
            )

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

            ens_config = EnsembleConfig(n_models=12, stacking_enabled=True, model_dir="")
            model = EnsembleModel(ens_config)
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
                    RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42, n_jobs=-1),
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
                day_prices[ticker] = {
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                }

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
                last_prices[ticker] = {
                    "open": float(last_row["Open"]),
                    "high": float(last_row["High"]),
                    "low": float(last_row["Low"]),
                    "close": float(last_row["Close"]),
                }
        if last_prices:
            sim.close_all_positions(sorted_dates[-1], last_prices)

        return sim.trades, sim.snapshots


    # ------------------------------------------------------------------
    # Internal: MiroFish integration
    # ------------------------------------------------------------------

    def _run_mirofish_per_day(
        self,
        split: WalkForwardSplit,
        test_feats: Dict[str, pd.DataFrame],
        universe_data: Dict[str, pd.DataFrame],
        predictions: List[Dict[str, float]],
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, float]]:
        """Run MiroFish per test day, blending each day's signal individually.

        Instead of running once per fold with static blending, this runs
        MiroFish for each test day using that day's ensemble predictions
        as seed and universe data sliced up to that day (no lookahead).
        """
        try:
            from mirofish.orchestrator import MiroFishOrchestrator
            from mirofish.types import SimulationConfig
        except ImportError:
            logger.warning("MiroFish not available — skipping")
            return predictions

        # Load mirofish config from config.json
        mf_raw: dict = {}
        try:
            with open("config.json") as f:
                mf_raw = json.load(f).get("mirofish", {})
        except Exception:
            pass

        n_sims = self._config.mirofish_n_sims
        sim_config = SimulationConfig(
            n_agents=int(mf_raw.get("n_agents", 1000)),
            n_ticks=int(mf_raw.get("n_ticks", 80)),
            n_simulations=n_sims,
            n_processes=1,  # Serial within fold — folds already run in parallel
            price_impact_factor=float(mf_raw.get("price_impact_factor", 0.001)),
            base_volatility=float(mf_raw.get("base_volatility", 0.02)),
            liquidity=float(mf_raw.get("liquidity", 1.0)),
            influence_radius=int(mf_raw.get("influence_radius", 15)),
            information_decay=float(mf_raw.get("information_decay", 0.92)),
            consensus_weight=float(mf_raw.get("consensus_weight", 0.25)),
        )
        dist_raw = mf_raw.get("agent_distribution")
        if dist_raw:
            sim_config.agent_distribution = {k: int(v) for k, v in dist_raw.items()}

        mf_weight = sim_config.consensus_weight
        ens_weight = 1.0 - mf_weight

        # Collect sorted test dates for universe slicing
        all_dates: set = set()
        for feat_df in test_feats.values():
            all_dates.update(feat_df.index)
        sorted_dates = sorted(all_dates)

        regime = self._detect_simple_regime(universe_data, split.train_end)

        blended: List[Dict[str, float]] = []
        orchestrator = MiroFishOrchestrator(sim_config)

        for day_idx, day_preds in enumerate(predictions):
            # Determine the date for this prediction day
            if day_idx < len(sorted_dates):
                current_date = sorted_dates[day_idx]
                if hasattr(current_date, 'date'):
                    current_date = current_date.date()
            else:
                # Past available dates — use last known
                current_date = split.test_end

            # Slice universe data up to this day (no lookahead)
            sliced_universe: Dict[str, pd.DataFrame] = {}
            for ticker, df in universe_data.items():
                idx = df.index
                if hasattr(idx, 'date'):
                    mask = idx.date <= current_date
                else:
                    mask = idx <= pd.Timestamp(current_date)
                sliced = df.loc[mask]
                if len(sliced) >= 20:
                    sliced_universe[ticker] = sliced

            if not sliced_universe:
                blended.append(day_preds)
                continue

            # Build per-day features from test_feats at this day
            features_df = self._build_features_for_day(test_feats, day_idx)

            try:
                mf_signals = orchestrator.run_universe(
                    universe_data=sliced_universe,
                    features_df=features_df,
                    regime=regime,
                    ensemble_probs=day_preds,
                    news_data={},
                )

                # Blend this day's predictions with MiroFish
                day_blended: Dict[str, float] = {}
                for ticker, ens_prob in day_preds.items():
                    if ticker in mf_signals:
                        mf_prob = mf_signals[ticker].probability
                        day_blended[ticker] = (
                            ens_weight * ens_prob + mf_weight * mf_prob
                        )
                    else:
                        day_blended[ticker] = ens_prob
                blended.append(day_blended)

            except Exception as e:
                logger.debug("MiroFish day %d failed: %s", day_idx, e)
                blended.append(day_preds)

        return blended

    def _build_features_for_day(
        self,
        test_feats: Dict[str, pd.DataFrame],
        day_idx: int,
    ) -> pd.DataFrame:
        """Build a features DataFrame indexed by ticker for a specific test day.

        Uses the row at day_idx for each ticker (no lookahead beyond that day).
        """
        rows: List[pd.Series] = []
        tickers: List[str] = []

        for ticker, feat_df in test_feats.items():
            if feat_df.empty or day_idx >= len(feat_df):
                continue
            row = feat_df.iloc[day_idx].copy()
            row.name = ticker
            rows.append(row)
            tickers.append(ticker)

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows, index=tickers)

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
            closes = sliced["Close"].values[-60:]
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
        return float(df["Close"].iloc[-1]) * 0.02

    end_pos = idx[0]
    start_pos = max(0, end_pos - period)
    sub = df.iloc[start_pos:end_pos + 1]

    if len(sub) < 2:
        return float(df["Close"].iloc[-1]) * 0.02

    highs = sub["High"].values
    lows = sub["Low"].values
    closes = sub["Close"].values

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
