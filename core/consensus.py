"""Consensus engine — the 'investment committee' that aggregates all signal
sources (ML specialist models + Claude persona analysts) into a single
ConsensusResult per ticker.

Weighted averaging favours ML signals slightly over LLM signals, penalises
disagreement, and exposes gating helpers so the strategy layer can decide
whether and how much to trade.
"""

from __future__ import annotations

from typing import Dict, List

from types_shared import (
    ConsensusResult,
    PersonaSignal,
    ModelSignal,
    RegimeState,
)

# Claude persona signals are discounted relative to ML models to reflect the
# generally higher reliability of quantitative predictions.
_PERSONA_WEIGHT_DISCOUNT: float = 0.8


class ConsensusEngine:
    """Aggregates heterogeneous prediction signals into a unified consensus."""

    def __init__(self, config: Dict[str, float | int] | None = None) -> None:
        cfg: Dict[str, float | int] = config or {}
        self._min_consensus_pct: float = float(cfg.get("min_consensus_pct", 60.0))
        self._disagreement_penalty: float = float(cfg.get("disagreement_penalty", 0.5))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_consensus(
        self,
        ticker: str,
        model_signals: List[ModelSignal],
        persona_signals: List[PersonaSignal],
        regime: RegimeState | None = None,
        horizon_probs: Dict[int, float] | None = None,
    ) -> ConsensusResult:
        """Combine all signal sources into a single consensus for *ticker*."""

        all_probs: List[float] = [s.probability for s in model_signals] + [
            s.probability for s in persona_signals
        ]

        # Bull / bear tallies
        bull_count: int = sum(1 for p in all_probs if p > 0.5)
        bear_count: int = len(all_probs) - bull_count

        # Agreement percentage
        consensus_pct: float = self._agreement_percentage(all_probs)

        # Confidence-weighted probability ----------------------------------
        weighted_sum: float = 0.0
        weight_total: float = 0.0

        for sig in model_signals:
            w = sig.confidence
            weighted_sum += sig.probability * w
            weight_total += w

        for sig in persona_signals:
            w = sig.confidence * _PERSONA_WEIGHT_DISCOUNT
            weighted_sum += sig.probability * w
            weight_total += w

        probability: float = weighted_sum / weight_total if weight_total > 0.0 else 0.5

        # Average confidence across every signal
        all_confidences: List[float] = [s.confidence for s in model_signals] + [
            s.confidence for s in persona_signals
        ]
        confidence: float = (
            sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
        )

        strength: float = self._signal_strength(probability)
        disagreement: float = self._compute_disagreement(all_probs)

        return ConsensusResult(
            ticker=ticker,
            probability=probability,
            consensus_pct=consensus_pct,
            confidence=confidence,
            signal_strength=strength,
            disagreement=disagreement,
            bull_count=bull_count,
            bear_count=bear_count,
            regime=regime.regime if regime is not None else "unknown",
            horizon_breakdown=dict(horizon_probs) if horizon_probs else {},
        )

    def compute_all(
        self,
        all_signals: Dict[str, List[ModelSignal]],
        all_personas: Dict[str, List[PersonaSignal]],
        regime: RegimeState | None = None,
        all_horizon_probs: Dict[str, Dict[int, float]] | None = None,
    ) -> Dict[str, ConsensusResult]:
        """Batch version: compute consensus for every ticker present in either
        signal dict."""

        tickers: set[str] = set(all_signals.keys()) | set(all_personas.keys())
        results: Dict[str, ConsensusResult] = {}

        for ticker in sorted(tickers):
            model_sigs = all_signals.get(ticker, [])
            persona_sigs = all_personas.get(ticker, [])
            h_probs = (all_horizon_probs or {}).get(ticker)
            results[ticker] = self.compute_consensus(
                ticker=ticker,
                model_signals=model_sigs,
                persona_signals=persona_sigs,
                regime=regime,
                horizon_probs=h_probs,
            )

        return results

    def should_trade(self, result: ConsensusResult) -> bool:
        """Gatekeeper: only allow trades when agreement exceeds threshold."""

        return result.consensus_pct >= self._min_consensus_pct

    def position_size_modifier(self, result: ConsensusResult) -> float:
        """Return a 0.0–1.0 multiplier reflecting consensus strength.

        50 % consensus  -> 0.0  (no position)
        75 % consensus  -> 0.5  (half size)
        100 % consensus -> 1.0  (full size)
        """

        return min(1.0, max(0.0, (result.consensus_pct - 50.0) / 50.0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _agreement_percentage(self, probabilities: List[float]) -> float:
        """Percentage of signals predicting P(up) > 0.5."""

        if not probabilities:
            return 50.0

        bulls: int = sum(1 for p in probabilities if p > 0.5)
        return bulls / len(probabilities) * 100.0

    def _compute_disagreement(self, probabilities: List[float]) -> float:
        """Scaled variance of probability estimates, clamped to [0, 1].

        Maximum possible variance for values in [0, 1] is 0.25 (half at 0,
        half at 1), so multiplying by 4 normalises the result to [0, 1].
        """

        if len(probabilities) < 2:
            return 0.0

        mean: float = sum(probabilities) / len(probabilities)
        variance: float = sum((p - mean) ** 2 for p in probabilities) / len(
            probabilities
        )

        # Scale so that theoretical maximum variance (0.25) maps to 1.0
        scaled: float = variance * 4.0
        return min(1.0, max(0.0, scaled))

    def _signal_strength(self, consensus_probability: float) -> float:
        """Distance from the indecision midpoint (0.5).

        Returns a value in [0.0, 0.5] — higher means stronger conviction.
        """

        return abs(consensus_probability - 0.5)
