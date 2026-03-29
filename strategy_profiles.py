"""Immutable strategy profiles and regime-to-profile mapping.

Each profile encodes a complete trading style: entry/exit thresholds,
position sizing, stop/take-profit distances, and minimum conviction
filters.  The regime mapping provides a sensible default profile for
each detected market regime.
"""
from __future__ import annotations

from typing import Dict

from types_shared import RegimeType, StrategyProfile, StrategyProfileName


# ── Canonical profiles ───────────────────────────────────────────────

CONSERVATIVE = StrategyProfile(
    name="conservative",
    threshold_buy=0.68,
    threshold_sell=0.35,
    max_positions=3,
    position_size_fraction=0.08,
    atr_stop_multiplier=1.2,
    atr_profit_multiplier=1.8,
    min_signal_strength=0.15,
    min_consensus_pct=65,
    description="High-vol / tiny-capital regime — tight risk, small bets",
)

DAY_TRADER = StrategyProfile(
    name="day_trader",
    threshold_buy=0.60,
    threshold_sell=0.42,
    max_positions=6,
    position_size_fraction=0.15,
    atr_stop_multiplier=1.5,
    atr_profit_multiplier=2.5,
    min_signal_strength=0.10,
    min_consensus_pct=60,
    description="Normal mean-reverting conditions — moderate risk",
)

SWING = StrategyProfile(
    name="swing",
    threshold_buy=0.55,
    threshold_sell=0.40,
    max_positions=5,
    position_size_fraction=0.18,
    atr_stop_multiplier=2.0,
    atr_profit_multiplier=3.0,
    min_signal_strength=0.08,
    min_consensus_pct=55,
    description="Trending market with breadth — patient entries",
)

CRISIS_ALPHA = StrategyProfile(
    name="crisis_alpha",
    threshold_buy=0.72,
    threshold_sell=0.30,
    max_positions=2,
    position_size_fraction=0.10,
    atr_stop_multiplier=1.0,
    atr_profit_multiplier=2.0,
    min_signal_strength=0.20,
    min_consensus_pct=75,
    description="Contrarian plays during panic — very selective",
)

TREND_FOLLOWER = StrategyProfile(
    name="trend_follower",
    threshold_buy=0.52,
    threshold_sell=0.45,
    max_positions=8,
    position_size_fraction=0.20,
    atr_stop_multiplier=2.5,
    atr_profit_multiplier=4.0,
    min_signal_strength=0.05,
    min_consensus_pct=50,
    description="Strong trend riding — wide stops, many positions",
)

DEFAULT_PROFILES: Dict[StrategyProfileName, StrategyProfile] = {
    "conservative": CONSERVATIVE,
    "day_trader": DAY_TRADER,
    "swing": SWING,
    "crisis_alpha": CRISIS_ALPHA,
    "trend_follower": TREND_FOLLOWER,
}

REGIME_DEFAULT_MAPPING: Dict[RegimeType, StrategyProfileName] = {
    "trending_up": "trend_follower",
    "trending_down": "conservative",
    "mean_reverting": "day_trader",
    "high_volatility": "crisis_alpha",
    "unknown": "swing",
}


def load_profiles_from_config(
    config: Dict[str, object],
) -> Dict[StrategyProfileName, StrategyProfile]:
    """Merge config.json overrides into the default profile set.

    Expects an optional ``"strategy_profiles"`` key whose value is a
    dict of ``{profile_name: {field: value, ...}}``.  Only recognised
    profile names and valid ``StrategyProfile`` fields are applied;
    everything else is silently ignored so a bad config key cannot crash
    the pipeline.

    Args:
        config: Parsed config.json dict (or subset of it).

    Returns:
        A *new* dict of profiles — the originals are never mutated.
    """
    overrides: Dict[str, Dict[str, object]] = config.get("strategy_profiles", {})  # type: ignore[assignment]
    if not overrides:
        return dict(DEFAULT_PROFILES)

    valid_fields = {f.name for f in StrategyProfile.__dataclass_fields__.values()}
    merged: Dict[StrategyProfileName, StrategyProfile] = {}

    for name, default in DEFAULT_PROFILES.items():
        profile_overrides = overrides.get(name, {})
        if not isinstance(profile_overrides, dict):
            merged[name] = default
            continue
        # Build kwargs from the frozen default, then overlay config values
        base = {k: getattr(default, k) for k in valid_fields}
        for k, v in profile_overrides.items():
            if k in valid_fields and k != "name":
                base[k] = v
        merged[name] = StrategyProfile(**base)  # type: ignore[arg-type]

    return merged
