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
    max_positions=5,
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
    max_positions=12,
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
    max_positions=10,
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
    max_positions=3,
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
    max_positions=15,
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

    Reads from ``config["strategy_profiles"]["profiles"]`` (nested format)
    and falls back to flat ``config["strategy_profiles"][profile_name]``
    for backward compatibility.  Each profile dict may contain:
      - Top-level fields (threshold_buy, etc.) — applied directly
      - ``"strategy"`` sub-dict — strategy fields applied
      - ``"risk"`` sub-dict — risk fields applied
      - ``"model"`` sub-dict — model hyperparams applied

    Args:
        config: Parsed config.json dict (or subset of it).

    Returns:
        A *new* dict of profiles — the originals are never mutated.
    """
    sp_section: Dict[str, object] = config.get("strategy_profiles", {})  # type: ignore[assignment]
    if not sp_section:
        return dict(DEFAULT_PROFILES)

    # New nested format: strategy_profiles.profiles.<name>
    nested: Dict[str, Dict[str, object]] = sp_section.get("profiles", {})  # type: ignore[assignment]

    valid_fields = {f.name for f in StrategyProfile.__dataclass_fields__.values()}
    merged: Dict[StrategyProfileName, StrategyProfile] = {}

    for name, default in DEFAULT_PROFILES.items():
        # Prefer nested format, fall back to flat
        profile_overrides = nested.get(name, {}) or sp_section.get(name, {})
        if not isinstance(profile_overrides, dict):
            merged[name] = default
            continue

        base = {k: getattr(default, k) for k in valid_fields}

        # Apply top-level fields directly
        for k, v in profile_overrides.items():
            if k in valid_fields and k != "name":
                base[k] = v

        # Apply nested strategy sub-dict
        strat = profile_overrides.get("strategy", {})
        if isinstance(strat, dict):
            for k, v in strat.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        # Apply nested risk sub-dict
        risk = profile_overrides.get("risk", {})
        if isinstance(risk, dict):
            for k, v in risk.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        # Apply nested model sub-dict
        model = profile_overrides.get("model", {})
        if isinstance(model, dict):
            for k, v in model.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        # Apply horizons and target_regimes (convert lists to tuples for frozen dataclass)
        horizons = profile_overrides.get("horizons")
        if horizons is not None:
            base["horizons"] = tuple(horizons) if isinstance(horizons, list) else horizons
        horizon_weights = profile_overrides.get("horizon_weights")
        if horizon_weights is not None and isinstance(horizon_weights, dict):
            base["horizon_weights"] = tuple(float(v) for v in horizon_weights.values())
        target_regimes = profile_overrides.get("target_regimes")
        if target_regimes is not None:
            base["target_regimes"] = tuple(target_regimes) if isinstance(target_regimes, list) else target_regimes

        merged[name] = StrategyProfile(**base)  # type: ignore[arg-type]

    return merged


def load_research_profiles(
    config: Dict[str, object],
) -> Dict[StrategyProfileName, StrategyProfile]:
    """Load profiles with research-proven best configs as highest priority.

    Priority chain: research best > config.json overrides > hardcoded defaults.
    Falls back to load_profiles_from_config if no research results exist.
    """
    import json
    from pathlib import Path

    profiles = load_profiles_from_config(config)

    research_dir = Path(__file__).parent / "research" / "profiles"
    if not research_dir.exists():
        return profiles

    valid_fields = {f.name for f in StrategyProfile.__dataclass_fields__.values()}

    for name in DEFAULT_PROFILES:
        best_file = research_dir / f"best_{name}.json"
        if not best_file.exists():
            continue

        try:
            data = json.loads(best_file.read_text(encoding="utf-8"))
            research_cfg = data.get("config", {})
        except (json.JSONDecodeError, OSError):
            continue

        if not research_cfg:
            continue

        # Start from config.json-merged profile, overlay research results
        base = {k: getattr(profiles[name], k) for k in valid_fields}

        strat = research_cfg.get("strategy", {})
        if isinstance(strat, dict):
            for k, v in strat.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        risk = research_cfg.get("risk", {})
        if isinstance(risk, dict):
            for k, v in risk.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        model = research_cfg.get("model", {})
        if isinstance(model, dict):
            for k, v in model.items():
                if k in valid_fields and k != "name":
                    base[k] = v

        profiles[name] = StrategyProfile(**base)  # type: ignore[arg-type]

    return profiles
