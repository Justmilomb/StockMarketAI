"""Probability calibration and edge detection for prediction markets.

The core question is NOT "will price go up?" but "is the market's
probability estimate wrong?"  This module detects mispricings by
comparing AI-estimated probabilities against the market price (which
IS the probability).

For the MVP, edge detection uses heuristic signals:
- Volume momentum suggests informed trading
- Price trends suggest the market is still moving toward fair value
- Time-to-resolution affects how much edge is exploitable
- LLM probability estimation (future: Claude API integration)
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional

from polymarket.types import PolymarketEdge, PolymarketEvent

logger = logging.getLogger(__name__)


class EdgeDetector:
    """Detects mispriced prediction markets.

    Compares a heuristic AI probability estimate against the market
    price.  Markets where the absolute edge exceeds min_edge_pct are
    flagged as trading opportunities.
    """

    def __init__(self, config: Optional[Dict[str, float | str]] = None) -> None:
        cfg = config or {}
        self._min_edge_pct: float = float(cfg.get("min_edge_pct", 5.0))
        self._calibration_method: str = str(cfg.get("calibration_method", "heuristic"))

    def detect_edges(
        self,
        events: List[PolymarketEvent],
        features_list: List[Dict[str, float]],
        min_edge_pct: Optional[float] = None,
    ) -> List[PolymarketEdge]:
        """Scan a batch of events for probability mispricings.

        Args:
            events: List of market events with current prices.
            features_list: Pre-computed features for each event (same order).
            min_edge_pct: Override minimum edge threshold (percentage points).

        Returns:
            List of PolymarketEdge objects for events exceeding threshold,
            sorted by absolute edge descending.
        """
        threshold = (min_edge_pct if min_edge_pct is not None else self._min_edge_pct) / 100.0

        edges: List[PolymarketEdge] = []
        for event, features in zip(events, features_list):
            if not event.is_binary:
                logger.debug("Skipping non-binary market: %s", event.question[:60])
                continue

            ai_prob = self._estimate_probability(event, features)
            market_prob = event.market_probability
            edge = ai_prob - market_prob

            if abs(edge) < threshold:
                continue

            confidence = self._estimate_confidence(features, edge)
            recommended_side = "YES" if edge > 0 else "NO"

            # Kelly criterion for binary bets:
            # f* = (p * b - q) / b  where p=prob, q=1-p, b=odds
            kelly = self._compute_kelly(ai_prob, market_prob, recommended_side)

            edges.append(
                PolymarketEdge(
                    condition_id=event.condition_id,
                    question=event.question,
                    ai_probability=round(ai_prob, 4),
                    market_probability=round(market_prob, 4),
                    edge=round(edge, 4),
                    confidence=round(confidence, 4),
                    recommended_side=recommended_side,
                    kelly_size=round(kelly, 4),
                )
            )

        # Sort by absolute edge descending — biggest mispricings first
        edges.sort(key=lambda e: abs(e.edge), reverse=True)
        logger.info(
            "Detected %d edges from %d events (threshold=%.1f%%)",
            len(edges), len(events), threshold * 100,
        )
        return edges

    # ── Probability estimation ────────────────────────────────────────

    def _estimate_probability(
        self,
        event: PolymarketEvent,
        features: Dict[str, float],
    ) -> float:
        """Heuristic AI probability estimate for a binary event.

        Adjusts the market probability based on momentum, volume, and
        time signals that suggest the market hasn't yet reached fair
        value.  This is a starting point — future versions will use
        calibrated ML models and LLM reasoning.
        """
        market_prob = event.market_probability

        # Start from the market price (it's usually approximately right)
        adjustment = 0.0

        # 1. Momentum signal: if price is trending, the market may not
        #    have caught up yet — extrapolate slightly
        momentum_1d = features.get("price_momentum_1d", 0.0)
        momentum_7d = features.get("price_momentum_7d", 0.0)

        # Short-term momentum carries more weight than long-term
        momentum_signal = momentum_1d * 0.6 + momentum_7d * 0.2
        adjustment += momentum_signal * 0.3  # damped extrapolation

        # 2. Volume spike: high volume often precedes moves — lean
        #    in the direction of recent momentum
        volume_spike = features.get("volume_spike", 0.0)
        if volume_spike > 2.0:
            # High volume amplifies the momentum signal
            volume_boost = min((volume_spike - 2.0) / 8.0, 0.5)  # cap at 0.5
            adjustment += momentum_signal * volume_boost

        # 3. Orderbook imbalance: more bids → price likely to rise
        ob_imbalance = features.get("orderbook_imbalance", 0.0)
        adjustment += ob_imbalance * 0.05

        # 4. Time decay: as resolution approaches, reduce adjustment
        #    (market becomes more efficient near expiry)
        time_to_resolution = features.get("time_to_resolution", 30.0)
        if time_to_resolution < 7:
            time_dampener = time_to_resolution / 7.0
            adjustment *= time_dampener

        # 5. Extreme prices: avoid pushing near 0 or 1 (calibration)
        #    Markets at extreme prices are usually right
        extremity = abs(market_prob - 0.5) * 2.0  # 0 at 50%, 1 at 0%/100%
        adjustment *= (1.0 - extremity * 0.5)

        ai_prob = market_prob + adjustment
        # Clamp to [0.01, 0.99] — never predict certainty
        return max(0.01, min(0.99, ai_prob))

    def _estimate_confidence(
        self,
        features: Dict[str, float],
        edge: float,
    ) -> float:
        """Estimate confidence in the detected edge.

        Higher confidence when multiple signals agree and the market
        has sufficient liquidity for our estimate to be meaningful.
        """
        confidence = 0.3  # base confidence (we're always somewhat uncertain)

        # More liquidity = more informative market = need more evidence
        liquidity = features.get("liquidity", 0.0)
        if liquidity > 10000:
            confidence -= 0.1  # highly liquid market — harder to beat
        elif liquidity < 1000:
            confidence += 0.1  # thin market — more likely to be mispriced

        # Momentum alignment boosts confidence
        momentum_1d = features.get("price_momentum_1d", 0.0)
        if (edge > 0 and momentum_1d > 0) or (edge < 0 and momentum_1d < 0):
            confidence += 0.15  # momentum agrees with our edge direction

        # Volume spike boosts confidence (informed traders moving)
        volume_spike = features.get("volume_spike", 0.0)
        if volume_spike > 2.0:
            confidence += 0.1

        # Reasonable time horizon boosts confidence
        time_to_resolution = features.get("time_to_resolution", 30.0)
        if 7 <= time_to_resolution <= 90:
            confidence += 0.1
        elif time_to_resolution < 1:
            confidence -= 0.2  # about to resolve — very risky

        return max(0.05, min(0.95, confidence))

    # ── Kelly criterion ───────────────────────────────────────────────

    def _compute_kelly(
        self,
        ai_probability: float,
        market_probability: float,
        side: str,
    ) -> float:
        """Compute Kelly-optimal bet size for a binary prediction market.

        In prediction markets, the odds are derived from the market price:
        - Buying YES at price p costs p, pays 1 if correct → odds b = (1-p)/p
        - Buying NO at price (1-p), pays 1 if correct → odds b = p/(1-p)

        Kelly fraction: f* = (p*b - q) / b
        where p = our probability, q = 1-p, b = payout odds.
        """
        if side == "YES":
            p = ai_probability
            cost = market_probability
        else:
            p = 1.0 - ai_probability
            cost = 1.0 - market_probability

        if cost <= 0 or cost >= 1:
            return 0.0

        b = (1.0 - cost) / cost  # payout odds
        q = 1.0 - p

        kelly = (p * b - q) / b
        # Never bet more than 25% or negative amounts
        return max(0.0, min(kelly, 0.25))
