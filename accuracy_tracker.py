from __future__ import annotations

import logging
from typing import Dict

import pandas as pd

from database import HistoryManager

logger = logging.getLogger(__name__)


class AccuracyTracker:
    """Tracks prediction accuracy and computes optimal weights for self-improvement."""

    # Sources we log separately from signals_df columns
    SOURCES = ["final", "sklearn", "ensemble", "statistical", "deep"]

    def __init__(self, history_manager: HistoryManager) -> None:
        self._db = history_manager

    def log_predictions(self, signals_df: pd.DataFrame) -> None:
        """Log all predictions from the current pipeline run."""
        for _, row in signals_df.iterrows():
            ticker = str(row.get("ticker", ""))
            signal = str(row.get("signal", "hold"))

            # Log each source's probability separately
            source_cols = {
                "final": "p_up_final",
                "sklearn": "p_up_sklearn",
                "ensemble": "p_up_ensemble",
                "statistical": "p_up_statistical",
                "deep": "p_up_deep",
            }
            for source_name, col_name in source_cols.items():
                prob = float(row.get(col_name, 0.5))
                try:
                    self._db.log_prediction(ticker, source_name, prob, signal)
                except Exception as e:
                    logger.warning("Failed to log prediction for %s/%s: %s", ticker, source_name, e)

    def resolve_outcomes(self, ticker: str, actual_close_today: float, actual_close_yesterday: float) -> None:
        """Compare yesterday's predictions against today's actual close."""
        if actual_close_yesterday <= 0:
            return

        actual_return = (actual_close_today - actual_close_yesterday) / actual_close_yesterday
        actual_direction = 1 if actual_close_today > actual_close_yesterday else 0

        count = self._db.resolve_predictions(ticker, actual_direction, actual_return)
        if count > 0:
            logger.debug(
                "Resolved %d predictions for %s (direction=%d, return=%.4f)",
                count, ticker, actual_direction, actual_return,
            )

    def get_rolling_accuracy(self, source: str = "all", window_days: int = 30) -> float:
        """Rolling accuracy for a given source over the last N days."""
        stats = self._db.get_accuracy_stats(source, window_days)
        return stats.get("hit_rate", 0.0)

    def get_accuracy_breakdown(self) -> Dict[str, float]:
        """Per-source accuracy over the last 30 days."""
        breakdown: Dict[str, float] = {}
        for source in self.SOURCES:
            stats = self._db.get_accuracy_stats(source, window_days=30)
            if stats["total"] > 0:
                breakdown[source] = stats["hit_rate"]
        return breakdown

    def get_optimal_weights(self, lookback_days: int = 60) -> Dict[str, float]:
        """Compute optimal family weights based on recent accuracy.

        Uses inverse-error weighting: better accuracy -> higher weight.
        Maps source names to family names for meta-ensemble tuning.
        """
        source_to_family = {
            "ensemble": "ml",
            "statistical": "statistical",
            "deep": "deep_learning",
        }

        accuracies: Dict[str, float] = {}
        for source, family in source_to_family.items():
            stats = self._db.get_accuracy_stats(source, lookback_days)
            if stats["total"] >= 5:  # Need minimum data
                accuracies[family] = max(stats["hit_rate"], 0.01)  # Floor to avoid division by zero

        if not accuracies:
            return {}

        # Inverse-error weighting
        total_acc = sum(accuracies.values())
        if total_acc == 0:
            return {}

        return {family: round(acc / total_acc, 3) for family, acc in accuracies.items()}
