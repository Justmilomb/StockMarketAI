"""Market regime detection for prediction markets.

Unlike stock-market regime detection (which looks at SPY volatility,
breadth, and trend strength), Polymarket regimes are determined by
category distribution, overall activity levels, and volume patterns
across the platform.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Dict, List

from polymarket.types import PolymarketEvent
from types_shared import RegimeState, RegimeType

logger = logging.getLogger(__name__)

# Categories that map to specific regime interpretations
_POLITICAL_CATEGORIES = {"politics", "elections", "us-elections", "geopolitics"}
_CRYPTO_CATEGORIES = {"crypto", "bitcoin", "ethereum", "defi"}
_SPORTS_CATEGORIES = {"sports", "nfl", "nba", "soccer", "football"}


class PolymarketRegimeDetector:
    """Detects the current prediction-market regime.

    The regime classification maps Polymarket activity patterns to
    the existing RegimeType enum so downstream strategy selection
    can reuse the same logic.

    Mapping logic:
        - High activity + political dominance → trending_up
          (strong directional sentiment, momentum strategies work)
        - High activity + diverse categories → mean_reverting
          (many small markets, contrarian plays)
        - Low activity → mean_reverting with low confidence
          (thin markets, no clear trend)
        - Crypto-dominated + high volume → high_volatility
          (correlated with crypto market swings)
    """

    def __init__(self, config: Dict[str, float | str | int] | None = None) -> None:
        cfg = config or {}
        self._min_volume_threshold: float = float(cfg.get("min_volume_24h", 1000))
        self._high_activity_threshold: int = int(cfg.get("high_activity_count", 20))

    def detect(self, events: List[PolymarketEvent]) -> RegimeState:
        """Classify the current Polymarket regime.

        Args:
            events: Recent active markets from the platform.

        Returns:
            RegimeState with regime type, confidence, and supporting metrics.
        """
        if not events:
            return self._unknown_regime()

        # Filter to markets with meaningful volume
        active_events = [e for e in events if e.volume_24h >= self._min_volume_threshold]

        if not active_events:
            return RegimeState(
                regime="mean_reverting",
                confidence=0.2,
                vix_proxy=0.0,
                breadth=0.0,
                trend_strength=0.0,
            )

        # Category distribution
        category_counts = Counter(e.category.lower() for e in active_events)
        total_active = len(active_events)

        # Compute regime signals
        category_dominance = self._compute_category_dominance(category_counts, total_active)
        activity_level = self._compute_activity_level(active_events)
        volume_concentration = self._compute_volume_concentration(active_events)
        breadth = self._compute_breadth(active_events)

        # Classify
        regime, confidence = self._classify(
            category_dominance, activity_level, volume_concentration, total_active,
        )

        # vix_proxy: use volume volatility as a proxy for market stress
        vix_proxy = self._compute_volume_volatility(active_events)

        return RegimeState(
            regime=regime,
            confidence=confidence,
            vix_proxy=vix_proxy,
            breadth=breadth,
            trend_strength=activity_level,
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _compute_category_dominance(
        self,
        category_counts: Counter,
        total: int,
    ) -> Dict[str, float]:
        """Fraction of active markets in each category group."""
        if total == 0:
            return {"political": 0.0, "crypto": 0.0, "sports": 0.0, "other": 1.0}

        political = sum(
            category_counts.get(c, 0) for c in _POLITICAL_CATEGORIES
        ) / total
        crypto = sum(
            category_counts.get(c, 0) for c in _CRYPTO_CATEGORIES
        ) / total
        sports = sum(
            category_counts.get(c, 0) for c in _SPORTS_CATEGORIES
        ) / total
        other = max(0.0, 1.0 - political - crypto - sports)

        return {
            "political": political,
            "crypto": crypto,
            "sports": sports,
            "other": other,
        }

    def _compute_activity_level(self, events: List[PolymarketEvent]) -> float:
        """Overall activity score (0-100) based on volume and trader count."""
        if not events:
            return 0.0

        total_volume = sum(e.volume_24h for e in events)
        total_traders = sum(e.num_traders for e in events)

        # Normalise to a 0-100 scale using empirical thresholds
        volume_score = min(total_volume / 1_000_000, 1.0) * 50
        trader_score = min(total_traders / 10_000, 1.0) * 50

        return round(volume_score + trader_score, 2)

    def _compute_volume_concentration(self, events: List[PolymarketEvent]) -> float:
        """How concentrated volume is in the top markets (Herfindahl index).

        High concentration → a few dominant markets.
        Low concentration → many active markets.
        """
        total_volume = sum(e.volume_24h for e in events)
        if total_volume <= 0:
            return 0.0

        shares = [e.volume_24h / total_volume for e in events]
        hhi = sum(s * s for s in shares)
        return round(hhi, 4)

    def _compute_breadth(self, events: List[PolymarketEvent]) -> float:
        """Percentage of markets that moved (probability shift > 1%) recently.

        Without historical data, approximate by looking at how far
        prices are from 50% — extreme prices suggest recent movement.
        """
        if not events:
            return 50.0

        moved_count = sum(
            1 for e in events
            if abs(e.market_probability - 0.5) > 0.1  # >10pp from 50/50
        )
        return round((moved_count / len(events)) * 100.0, 2)

    def _compute_volume_volatility(self, events: List[PolymarketEvent]) -> float:
        """Volume dispersion as a proxy for market stress.

        High volume variance across markets → some markets are
        getting unusual attention, similar to high VIX.
        """
        if len(events) < 2:
            return 0.0

        volumes = [e.volume_24h for e in events]
        mean_vol = sum(volumes) / len(volumes)
        if mean_vol <= 0:
            return 0.0

        variance = sum((v - mean_vol) ** 2 for v in volumes) / len(volumes)
        cv = (variance ** 0.5) / mean_vol  # coefficient of variation

        # Scale to a 0-50 range similar to VIX
        return round(min(cv * 20, 50.0), 2)

    def _classify(
        self,
        category_dominance: Dict[str, float],
        activity_level: float,
        volume_concentration: float,
        total_active: int,
    ) -> tuple[RegimeType, float]:
        """Map Polymarket signals to a RegimeType."""
        is_high_activity = total_active >= self._high_activity_threshold

        # Crypto-dominated + high activity → high_volatility
        if category_dominance["crypto"] > 0.4 and is_high_activity:
            confidence = min(0.5 + category_dominance["crypto"], 0.9)
            return "high_volatility", round(confidence, 3)

        # Political dominance + high activity → trending_up
        # (strong directional sentiment across many markets)
        if category_dominance["political"] > 0.4 and is_high_activity:
            confidence = min(0.5 + category_dominance["political"], 0.9)
            return "trending_up", round(confidence, 3)

        # High activity but diverse → mean_reverting
        # (many markets, no single theme dominates)
        if is_high_activity and volume_concentration < 0.2:
            return "mean_reverting", 0.6

        # Low activity → mean_reverting with low confidence
        if not is_high_activity:
            confidence = max(0.2, 0.5 - (self._high_activity_threshold - total_active) * 0.02)
            return "mean_reverting", round(confidence, 3)

        # Concentrated volume → trending (few markets dominate attention)
        if volume_concentration > 0.4:
            return "trending_up", 0.5

        return "unknown", 0.3

    def _unknown_regime(self) -> RegimeState:
        """Default when no data is available."""
        return RegimeState(
            regime="unknown",
            confidence=0.0,
            vix_proxy=0.0,
            breadth=50.0,
            trend_strength=0.0,
        )
