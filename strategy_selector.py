"""Regime-aware strategy selector — picks the best trading profile per ticker.

Combines the current market regime, per-ticker consensus quality, recent
volatility, and historical trade performance to assign each ticker the
strategy profile most likely to produce positive expectancy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from strategy import StrategyConfig
from strategy_profiles import (
    DEFAULT_PROFILES,
    REGIME_DEFAULT_MAPPING,
    load_profiles_from_config,
)
from types_shared import (
    ConsensusResult,
    RegimeState,
    RegimeType,
    StrategyAssignment,
    StrategyProfile,
    StrategyProfileName,
)


# ── Internal bookkeeping ─────────────────────────────────────────────

_MAX_HISTORY = 500

# Thresholds governing per-ticker overrides
_HIGH_STRENGTH_THRESHOLD = 0.15
_HIGH_CONSENSUS_THRESHOLD = 70.0
_LOW_STRENGTH_THRESHOLD = 0.06
_LOW_CONSENSUS_THRESHOLD = 50.0
_HIGH_DISAGREEMENT_THRESHOLD = 0.30
_HIGH_VOL_THRESHOLD = 0.05  # ATR / price ratio

# Adaptation: need this many trades before switching profile
_MIN_TRADES_FOR_ADAPTATION = 20
_ADAPTATION_EDGE_PCT = 5.0  # must beat current profile by 5 pp


@dataclass
class _TradeRecord:
    """Lightweight record for performance tracking."""

    regime: RegimeType
    profile_name: StrategyProfileName
    ticker: str
    pnl_pct: float


class StrategySelector:
    """Assigns the best ``StrategyProfile`` to each ticker every refresh.

    The selection cascade:
    1. Regime default mapping (broad market context).
    2. Per-ticker consensus quality override (signal conviction).
    3. Per-ticker volatility override (tail-risk guard).
    4. Historical performance adaptation (learning from outcomes).
    5. Small-capital adjustment (reduce sizing when capital is tiny).
    """

    def __init__(
        self,
        profiles: Dict[StrategyProfileName, StrategyProfile] | None = None,
        regime_mapping: Dict[RegimeType, StrategyProfileName] | None = None,
        capital: float = 100_000,
    ) -> None:
        self._profiles = profiles or dict(DEFAULT_PROFILES)
        self._regime_mapping = regime_mapping or dict(REGIME_DEFAULT_MAPPING)
        self._capital = capital
        self._history: List[_TradeRecord] = []

    # ── Public API ────────────────────────────────────────────────────

    def select_strategies(
        self,
        regime: RegimeState,
        consensus: Dict[str, ConsensusResult],
        volatility: Dict[str, float] | None = None,
    ) -> Dict[str, StrategyAssignment]:
        """Select a strategy profile for every ticker in *consensus*.

        Args:
            regime: Current market regime state.
            consensus: Per-ticker consensus results from the investment
                committee.
            volatility: Optional per-ticker normalised volatility
                (ATR / price).  When provided, high-vol tickers are
                shifted towards conservative / crisis_alpha profiles.

        Returns:
            Mapping of ticker -> ``StrategyAssignment``.
        """
        vol_map = volatility or {}
        assignments: Dict[str, StrategyAssignment] = {}

        for ticker, cr in consensus.items():
            profile_name, reason = self._select_single(
                regime=regime,
                cr=cr,
                ticker_vol=vol_map.get(ticker),
            )
            profile = self._profiles[profile_name]

            # Small-capital guard: scale sizing down proportionally
            if self._capital < 100_000:
                profile = self._apply_capital_adjustment(profile)

            assignments[ticker] = StrategyAssignment(
                ticker=ticker,
                profile=profile,
                reason=reason,
                regime=regime.regime,
                confidence=cr.confidence,
            )

        return assignments

    def record_trade_outcome(
        self,
        regime: RegimeType,
        profile_name: StrategyProfileName,
        ticker: str,
        pnl_pct: float,
    ) -> None:
        """Record one completed trade for future adaptation.

        Args:
            regime: Regime that was active when the trade was opened.
            profile_name: Profile used for the trade.
            ticker: Instrument ticker.
            pnl_pct: Realised PnL as a decimal fraction (e.g. 0.03 = +3%).
        """
        self._history.append(
            _TradeRecord(
                regime=regime,
                profile_name=profile_name,
                ticker=ticker,
                pnl_pct=pnl_pct,
            )
        )
        # Bounded buffer
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]

    def get_regime_performance_summary(
        self,
    ) -> Dict[str, Dict[str, Dict[str, float]]]:
        """Aggregate trade history into a regime x profile summary.

        Returns:
            ``{regime: {profile: {"win_rate": float, "avg_pnl": float,
            "count": float}}}``
        """
        buckets: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for rec in self._history:
            buckets[rec.regime][rec.profile_name].append(rec.pnl_pct)

        summary: Dict[str, Dict[str, Dict[str, float]]] = {}
        for regime, profiles in buckets.items():
            summary[regime] = {}
            for pname, pnls in profiles.items():
                count = len(pnls)
                wins = sum(1 for p in pnls if p > 0)
                summary[regime][pname] = {
                    "win_rate": wins / count if count else 0.0,
                    "avg_pnl": sum(pnls) / count if count else 0.0,
                    "count": float(count),
                }
        return summary

    @staticmethod
    def to_strategy_config(profile: StrategyProfile) -> StrategyConfig:
        """Convert a ``StrategyProfile`` to the legacy ``StrategyConfig``.

        This bridges the new profile system with the existing
        ``generate_signals()`` function.

        Args:
            profile: The strategy profile to convert.

        Returns:
            A ``StrategyConfig`` with matching thresholds and sizing.
        """
        return StrategyConfig(
            threshold_buy=profile.threshold_buy,
            threshold_sell=profile.threshold_sell,
            max_positions=profile.max_positions,
            position_size_fraction=profile.position_size_fraction,
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _select_single(
        self,
        regime: RegimeState,
        cr: ConsensusResult,
        ticker_vol: float | None,
    ) -> tuple[StrategyProfileName, str]:
        """Run the selection cascade for one ticker.

        Returns:
            (profile_name, human-readable reason string)
        """
        reasons: List[str] = []

        # Step 1: regime default
        base_name = self._regime_mapping.get(regime.regime, "swing")
        reasons.append(f"regime={regime.regime}")

        # Step 2: consensus quality override
        chosen = self._override_by_consensus(base_name, cr, reasons)

        # Step 3: volatility override
        chosen = self._override_by_volatility(chosen, ticker_vol, reasons)

        # Step 4: historical adaptation
        chosen = self._override_by_performance(chosen, regime.regime, reasons)

        return chosen, "; ".join(reasons)

    def _override_by_consensus(
        self,
        current: StrategyProfileName,
        cr: ConsensusResult,
        reasons: List[str],
    ) -> StrategyProfileName:
        """Shift profile based on signal strength and agreement."""
        # High conviction + strong agreement => allow more aggressive profile
        if (
            cr.signal_strength >= _HIGH_STRENGTH_THRESHOLD
            and cr.consensus_pct >= _HIGH_CONSENSUS_THRESHOLD
        ):
            aggressive = self._more_aggressive(current)
            if aggressive != current:
                reasons.append(
                    f"high conviction (str={cr.signal_strength:.2f}, "
                    f"cons={cr.consensus_pct:.0f}%) -> {aggressive}"
                )
                return aggressive

        # Low conviction => step towards conservative
        if (
            cr.signal_strength < _LOW_STRENGTH_THRESHOLD
            or cr.consensus_pct < _LOW_CONSENSUS_THRESHOLD
        ):
            conservative = self._more_conservative(current)
            if conservative != current:
                reasons.append(
                    f"low conviction (str={cr.signal_strength:.2f}, "
                    f"cons={cr.consensus_pct:.0f}%) -> {conservative}"
                )
                return conservative

        # High disagreement => step towards conservative
        if cr.disagreement >= _HIGH_DISAGREEMENT_THRESHOLD:
            conservative = self._more_conservative(current)
            if conservative != current:
                reasons.append(
                    f"high disagreement ({cr.disagreement:.2f}) -> {conservative}"
                )
                return conservative

        return current

    def _override_by_volatility(
        self,
        current: StrategyProfileName,
        ticker_vol: float | None,
        reasons: List[str],
    ) -> StrategyProfileName:
        """Shift to defensive profile when normalised volatility is high."""
        if ticker_vol is None:
            return current

        if ticker_vol > _HIGH_VOL_THRESHOLD:
            # Jump straight to crisis_alpha or conservative
            target: StrategyProfileName = (
                "crisis_alpha" if ticker_vol > _HIGH_VOL_THRESHOLD * 2 else "conservative"
            )
            if target != current:
                reasons.append(f"high vol ({ticker_vol:.3f}) -> {target}")
            return target

        return current

    def _override_by_performance(
        self,
        current: StrategyProfileName,
        regime: RegimeType,
        reasons: List[str],
    ) -> StrategyProfileName:
        """Switch profile if historical data proves another is better.

        Only activates after ``_MIN_TRADES_FOR_ADAPTATION`` trades have
        been recorded in the same regime.
        """
        regime_records = [r for r in self._history if r.regime == regime]
        if len(regime_records) < _MIN_TRADES_FOR_ADAPTATION:
            return current

        # Compute average PnL per profile in this regime
        profile_pnls: Dict[StrategyProfileName, List[float]] = defaultdict(list)
        for rec in regime_records:
            profile_pnls[rec.profile_name].append(rec.pnl_pct)

        current_avg = _safe_avg(profile_pnls.get(current, []))

        best_name = current
        best_avg = current_avg
        for pname, pnls in profile_pnls.items():
            if len(pnls) < _MIN_TRADES_FOR_ADAPTATION:
                continue
            avg = _safe_avg(pnls)
            if avg > best_avg:
                best_name = pname
                best_avg = avg

        # Only switch if the improvement is material
        edge = (best_avg - current_avg) * 100  # convert to percentage points
        if best_name != current and edge >= _ADAPTATION_EDGE_PCT:
            reasons.append(
                f"perf adaptation: {best_name} beats {current} "
                f"by {edge:.1f}pp in {regime}"
            )
            return best_name

        return current

    def _apply_capital_adjustment(
        self, profile: StrategyProfile
    ) -> StrategyProfile:
        """Scale position sizing down when capital is small.

        Returns a new profile with reduced ``position_size_fraction`` and
        ``max_positions``, preserving all other fields.
        """
        ratio = max(self._capital / 100_000, 0.1)
        adjusted_size = round(profile.position_size_fraction * ratio, 4)
        adjusted_max = max(1, int(profile.max_positions * ratio))

        # Reconstruct — StrategyProfile is frozen, so we replace via dict
        fields = {
            f.name: getattr(profile, f.name)
            for f in profile.__dataclass_fields__.values()
        }
        fields["position_size_fraction"] = adjusted_size
        fields["max_positions"] = adjusted_max
        return StrategyProfile(**fields)  # type: ignore[arg-type]

    # ── Aggression ladder ─────────────────────────────────────────────

    _AGGRESSION_ORDER: List[StrategyProfileName] = [
        "conservative",
        "crisis_alpha",
        "day_trader",
        "swing",
        "trend_follower",
    ]

    def _more_aggressive(
        self, current: StrategyProfileName
    ) -> StrategyProfileName:
        """Step one rung up the aggression ladder."""
        idx = self._index_of(current)
        return self._AGGRESSION_ORDER[min(idx + 1, len(self._AGGRESSION_ORDER) - 1)]

    def _more_conservative(
        self, current: StrategyProfileName
    ) -> StrategyProfileName:
        """Step one rung down the aggression ladder."""
        idx = self._index_of(current)
        return self._AGGRESSION_ORDER[max(idx - 1, 0)]

    def _index_of(self, name: StrategyProfileName) -> int:
        """Position on the aggression ladder (0 = most conservative)."""
        try:
            return self._AGGRESSION_ORDER.index(name)
        except ValueError:
            return 2  # default to middle (day_trader)


def _safe_avg(values: List[float]) -> float:
    """Average that returns 0.0 for empty lists."""
    return sum(values) / len(values) if values else 0.0
