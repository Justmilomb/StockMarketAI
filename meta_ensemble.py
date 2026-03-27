"""Three-family meta-ensemble: ML + Statistical + Deep Learning.

Combines predictions from the existing ML ensemble, ARIMA/ETS statistical
baselines, and N-BEATS deep learning forecasters into a single blended
probability per ticker. Handles graceful degradation when a family is
unavailable by redistributing weights proportionally.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from types_shared import ForecasterSignal, MetaEnsembleResult, ModelSignal

logger = logging.getLogger(__name__)


class MetaEnsemble:
    """Weighted combination of three model families into one probability."""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        cfg = config or {}
        weights = cfg.get("family_weights", {})
        self._base_weights: Dict[str, float] = {
            "ml": float(weights.get("ml", 0.50)),
            "statistical": float(weights.get("statistical", 0.25)),
            "deep_learning": float(weights.get("deep_learning", 0.25)),
        }

    def combine(
        self,
        ml_probs: Dict[str, float],
        stat_signals: Dict[str, List[ForecasterSignal]],
        deep_signals: Dict[str, List[ForecasterSignal]],
        horizons: List[int],
    ) -> Dict[str, MetaEnsembleResult]:
        """Weighted combination of three model families.

        Args:
            ml_probs: ML ensemble probability per ticker (already horizon-aggregated).
            stat_signals: Statistical forecaster signals per ticker.
            deep_signals: Deep learning forecaster signals per ticker (empty if unavailable).
            horizons: List of horizon days used (e.g. [1, 5, 20]).

        Returns:
            Dict mapping ticker to MetaEnsembleResult.
        """
        has_deep = len(deep_signals) > 0
        weights = self._resolve_weights(has_deep)

        results: Dict[str, MetaEnsembleResult] = {}
        all_tickers = set(ml_probs.keys())

        for ticker in all_tickers:
            ml_p = ml_probs.get(ticker, 0.5)
            stat_p = self._average_probability(stat_signals.get(ticker, []))
            deep_p = self._average_probability(deep_signals.get(ticker, [])) if has_deep else 0.5

            blended = (
                weights["ml"] * ml_p
                + weights["statistical"] * stat_p
                + weights["deep_learning"] * deep_p
            )
            blended = max(0.0, min(1.0, blended))

            # Confidence: average of component confidences weighted similarly
            stat_conf = self._average_confidence(stat_signals.get(ticker, []))
            deep_conf = self._average_confidence(deep_signals.get(ticker, [])) if has_deep else 0.0
            ml_conf = min(1.0, abs(ml_p - 0.5) * 4)
            confidence = (
                weights["ml"] * ml_conf
                + weights["statistical"] * stat_conf
                + weights["deep_learning"] * deep_conf
            )

            results[ticker] = MetaEnsembleResult(
                ticker=ticker,
                probability=blended,
                confidence=confidence,
                ml_probability=ml_p,
                stat_probability=stat_p,
                deep_probability=deep_p,
                family_weights=dict(weights),
            )

        logger.info(
            "Meta-ensemble combined %d tickers (weights: ML=%.0f%% Stat=%.0f%% Deep=%.0f%%)",
            len(results),
            weights["ml"] * 100,
            weights["statistical"] * 100,
            weights["deep_learning"] * 100,
        )
        return results

    def to_model_signals(
        self,
        stat_signals: Dict[str, List[ForecasterSignal]],
        deep_signals: Dict[str, List[ForecasterSignal]],
    ) -> Dict[str, List[ModelSignal]]:
        """Convert ForecasterSignals to ModelSignals for the consensus engine.

        The consensus engine expects ModelSignal objects. This adapter lets
        statistical and deep learning predictions participate in the
        investment committee vote alongside the existing ML models.
        """
        result: Dict[str, List[ModelSignal]] = {}

        for signals_dict in (stat_signals, deep_signals):
            for ticker, signals in signals_dict.items():
                if ticker not in result:
                    result[ticker] = []
                for sig in signals:
                    result[ticker].append(
                        ModelSignal(
                            model_name=f"{sig.family}_{sig.model_name}",
                            ticker=ticker,
                            probability=sig.probability,
                            confidence=sig.confidence,
                            feature_group=sig.family,
                            horizon_days=sig.horizon_days,
                        )
                    )

        return result

    # ── Internals ─────────────────────────────────────────────────────

    def _resolve_weights(self, has_deep: bool) -> Dict[str, float]:
        """Redistribute weights when a family is unavailable."""
        if has_deep:
            return dict(self._base_weights)

        # Deep learning unavailable — redistribute its weight proportionally
        ml_w = self._base_weights["ml"]
        stat_w = self._base_weights["statistical"]
        deep_w = self._base_weights["deep_learning"]

        total_remaining = ml_w + stat_w
        if total_remaining <= 0:
            return {"ml": 0.5, "statistical": 0.5, "deep_learning": 0.0}

        scale = (total_remaining + deep_w) / total_remaining
        return {
            "ml": ml_w * scale,
            "statistical": stat_w * scale,
            "deep_learning": 0.0,
        }

    @staticmethod
    def _average_probability(signals: List[ForecasterSignal]) -> float:
        """Average probability across a list of forecaster signals."""
        if not signals:
            return 0.5
        return sum(s.probability for s in signals) / len(signals)

    @staticmethod
    def _average_confidence(signals: List[ForecasterSignal]) -> float:
        """Average confidence across a list of forecaster signals."""
        if not signals:
            return 0.0
        return sum(s.confidence for s in signals) / len(signals)
