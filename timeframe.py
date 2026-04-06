"""Multi-timeframe analysis — separate ensembles for 1-day, 5-day, and 20-day horizons.

Trains independent EnsembleModel instances per prediction horizon, then
combines their outputs via a weighted average to produce a single probability
that incorporates short-, medium-, and long-term market views.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from ensemble import EnsembleModel
from features_advanced import FEATURE_COLUMNS_V2, engineer_features_v2
from types_shared import EnsembleConfig, ModelSignal

logger = logging.getLogger(__name__)

_DEFAULT_HORIZONS: List[int] = [1, 5]
_DEFAULT_WEIGHTS: Dict[int, float] = {1: 0.7, 5: 0.3}


# ---------------------------------------------------------------------------
# Horizon label builder
# ---------------------------------------------------------------------------


def build_horizon_labels(
    universe_data: Dict[str, pd.DataFrame],
    horizon_days: int,
) -> Dict[str, pd.DataFrame]:
    """Re-label engineered feature DataFrames for a given prediction horizon.

    For each ticker's raw OHLCV DataFrame:
      1. Run engineer_features_v2() to compute all V2 features.
      2. Overwrite the ``target_up`` column so that the target reflects whether
         the close price rises over *horizon_days* rather than the default 1 day.
      3. Drop rows where the new target is NaN (the last *horizon_days* rows).

    Args:
        universe_data: Mapping of ticker symbol to raw OHLCV DataFrame.
        horizon_days: Number of trading days into the future for the label.

    Returns:
        Dict mapping ticker to the modified DataFrame containing V2 features
        and the horizon-adjusted ``target_up`` column.
    """
    result: Dict[str, pd.DataFrame] = {}

    for ticker, raw_df in universe_data.items():
        if len(raw_df) <= horizon_days:
            logger.warning(
                "Ticker '%s' has only %d rows — fewer than horizon %d; skipping",
                ticker,
                len(raw_df),
                horizon_days,
            )
            continue

        engineered = engineer_features_v2(raw_df)
        if engineered.empty:
            logger.warning(
                "Ticker '%s' produced empty features — skipping", ticker,
            )
            continue

        # Overwrite the 1-day target with the horizon-specific target
        engineered["target_up"] = (
            engineered["close"].shift(-horizon_days) > engineered["close"]
        ).astype(float)

        # Drop rows where the new target is NaN (tail rows without a future close)
        engineered = engineered.dropna(subset=["target_up"]).copy()

        if engineered.empty:
            logger.warning(
                "Ticker '%s' has no valid rows after horizon-%d labelling — skipping",
                ticker,
                horizon_days,
            )
            continue

        result[ticker] = engineered

    logger.info(
        "build_horizon_labels(horizon=%d): %d/%d tickers usable",
        horizon_days,
        len(result),
        len(universe_data),
    )
    return result


# ---------------------------------------------------------------------------
# Multi-timeframe ensemble
# ---------------------------------------------------------------------------


class MultiTimeframeEnsemble:
    """Manages per-horizon EnsembleModel instances and aggregates their predictions.

    Each horizon gets its own independently trained ensemble.  At prediction
    time the per-horizon probabilities are combined via a configurable weighted
    average to produce a single final probability per ticker.
    """

    def __init__(
        self,
        horizons: List[int] | None = None,
        weights: Dict[int, float] | None = None,
        ensemble_config: EnsembleConfig | None = None,
    ) -> None:
        self._horizons: List[int] = horizons if horizons is not None else list(_DEFAULT_HORIZONS)
        self._weights: Dict[int, float] = weights if weights is not None else dict(_DEFAULT_WEIGHTS)
        self._config: EnsembleConfig = ensemble_config or EnsembleConfig()
        self._ensembles: Dict[int, EnsembleModel] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train_all_horizons(self, universe_data: Dict[str, pd.DataFrame]) -> None:
        """Train a separate ensemble for each prediction horizon.

        For each horizon the method builds horizon-specific labels, extracts
        the feature matrix and target vector, creates an ``EnsembleModel``,
        trains it, and stores it internally.
        """
        for horizon in self._horizons:
            logger.info("Training ensemble for %d-day horizon ...", horizon)

            labelled_data = build_horizon_labels(universe_data, horizon)
            if not labelled_data:
                logger.warning(
                    "No usable data for horizon %d — skipping", horizon,
                )
                continue

            # Stack all tickers into X, y, meta arrays
            frames: List[pd.DataFrame] = []
            for ticker, df in labelled_data.items():
                frame = df.copy()
                frame["ticker"] = ticker
                frame["date"] = frame.index
                frames.append(frame)

            combined = pd.concat(frames, axis=0).sort_values("date")

            X = combined[FEATURE_COLUMNS_V2].values.astype(float)
            y = combined["target_up"].values.astype(int)
            meta = combined[["ticker", "date"]].reset_index(drop=True)

            ensemble = EnsembleModel(config=self._config)
            ensemble.train(X, y, meta, columns=list(FEATURE_COLUMNS_V2))
            self._ensembles[horizon] = ensemble

            logger.info(
                "Horizon %d-day ensemble trained — %d models, %d samples",
                horizon,
                ensemble.n_models,
                len(y),
            )

        logger.info(
            "Multi-timeframe training complete: horizons trained = %s",
            sorted(self._ensembles.keys()),
        )

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        features_df: pd.DataFrame,
        meta_df: pd.DataFrame,
    ) -> Dict[int, Tuple[np.ndarray, Dict[str, List[ModelSignal]]]]:
        """Run prediction through each trained horizon ensemble.

        Returns a dict mapping horizon days to a tuple of
        (probability_array, per_ticker_signals).  Each ``ModelSignal``
        has its ``horizon_days`` field set to the corresponding horizon.
        """
        results: Dict[int, Tuple[np.ndarray, Dict[str, List[ModelSignal]]]] = {}

        for horizon in self._horizons:
            ensemble = self._ensembles.get(horizon)
            if ensemble is None:
                logger.debug("No trained ensemble for horizon %d — skipping", horizon)
                continue

            probs, per_ticker_signals = ensemble.predict_ensemble(features_df, meta_df)

            # Tag every signal with the horizon
            for signals in per_ticker_signals.values():
                for sig in signals:
                    sig.horizon_days = horizon

            results[horizon] = (probs, per_ticker_signals)

        return results

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        horizon_results: Dict[int, Tuple[np.ndarray, Dict[str, List[ModelSignal]]]],
    ) -> Tuple[np.ndarray, Dict[str, Dict[int, float]]]:
        """Weighted combination of per-horizon probabilities.

        Args:
            horizon_results: Output of :meth:`predict`.

        Returns:
            final_probs: 1-D array of weighted-average probabilities, one per
                ticker (same order as the arrays in *horizon_results*).
            horizon_breakdown: Per-ticker dict mapping horizon days to that
                horizon's probability, e.g. ``{"AAPL": {1: 0.62, 5: 0.58, 20: 0.71}}``.
        """
        if not horizon_results:
            return np.array([], dtype=np.float64), {}

        # Determine array length from the first available result
        first_probs = next(iter(horizon_results.values()))[0]
        n_tickers = len(first_probs)

        weighted_sum = np.zeros(n_tickers, dtype=np.float64)
        total_weight = 0.0

        # Per-ticker horizon breakdown: index -> {horizon: prob}
        breakdown_by_idx: Dict[int, Dict[int, float]] = {
            i: {} for i in range(n_tickers)
        }

        for horizon, (probs, per_ticker_signals) in horizon_results.items():
            w = self._weights.get(horizon, 0.0)
            weighted_sum += w * probs
            total_weight += w

            for i in range(n_tickers):
                breakdown_by_idx[i][horizon] = float(probs[i])

        if total_weight > 0.0:
            final_probs = weighted_sum / total_weight
        else:
            final_probs = np.full(n_tickers, 0.5, dtype=np.float64)

        # Convert index-based breakdown to ticker-keyed breakdown
        # Recover ticker names from the per_ticker_signals keys (insertion-ordered)
        all_tickers: List[str] = []
        for _, (_, per_ticker_signals) in horizon_results.items():
            all_tickers = list(per_ticker_signals.keys())
            if all_tickers:
                break

        horizon_breakdown: Dict[str, Dict[int, float]] = {}
        for i, ticker in enumerate(all_tickers):
            horizon_breakdown[ticker] = breakdown_by_idx.get(i, {})

        return final_probs, horizon_breakdown

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get_all_signals(
        self,
        features_df: pd.DataFrame,
        meta_df: pd.DataFrame,
    ) -> Tuple[np.ndarray, Dict[str, List[ModelSignal]], Dict[str, Dict[int, float]]]:
        """Predict across all horizons, aggregate, and return a flat signal dict.

        Returns:
            final_probs: Weighted-average probabilities (1-D array).
            all_signals_flat: Per-ticker list of ``ModelSignal`` objects from
                all horizons merged together.
            horizon_breakdown: Per-ticker dict of horizon-specific probabilities.
        """
        horizon_results = self.predict(features_df, meta_df)
        final_probs, horizon_breakdown = self.aggregate(horizon_results)

        # Merge all per-ticker signal lists across horizons
        all_signals_flat: Dict[str, List[ModelSignal]] = {}
        for _, (_, per_ticker_signals) in horizon_results.items():
            for ticker, signals in per_ticker_signals.items():
                all_signals_flat.setdefault(ticker, []).extend(signals)

        return final_probs, all_signals_flat, horizon_breakdown

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, base_dir: Path) -> None:
        """Save each horizon's ensemble to a separate file under *base_dir*."""
        base_dir = Path(base_dir)
        base_dir.mkdir(parents=True, exist_ok=True)

        for horizon, ensemble in self._ensembles.items():
            path = base_dir / f"horizon_{horizon}.joblib"
            ensemble.save(path)
            logger.info("Saved horizon %d-day ensemble to %s", horizon, path)

    def load(self, base_dir: Path) -> None:
        """Load each horizon's ensemble from *base_dir*.

        Missing files are skipped with a warning rather than raising.
        """
        base_dir = Path(base_dir)
        self._ensembles = {}

        for horizon in self._horizons:
            path = base_dir / f"horizon_{horizon}.joblib"
            if not path.exists():
                logger.warning(
                    "Ensemble file for horizon %d not found at %s — skipping",
                    horizon,
                    path,
                )
                continue

            self._ensembles[horizon] = EnsembleModel.load(path)
            logger.info("Loaded horizon %d-day ensemble from %s", horizon, path)

        logger.info(
            "Multi-timeframe load complete: horizons available = %s",
            sorted(self._ensembles.keys()),
        )
