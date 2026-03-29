"""Bridge between autoconfig experiments and the strategy profile system.

Converts a named strategy profile into config overrides suitable for
passing to ``experiment.run_experiment(overrides=...)``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategy_profiles import DEFAULT_PROFILES


def get_profile(name: str) -> Dict[str, Any] | None:
    """Return config overrides dict for a named strategy profile.

    Translates a ``StrategyProfile`` into the nested dict format that
    ``experiment._deep_merge`` expects, so autoconfig can test each
    profile's parameters as a backtest override.

    Returns None if the profile name is unknown.
    """
    profile = DEFAULT_PROFILES.get(name)  # type: ignore[arg-type]
    if profile is None:
        return None

    return {
        "strategy": {
            "threshold_buy": profile.threshold_buy,
            "threshold_sell": profile.threshold_sell,
            "max_positions": profile.max_positions,
            "position_size_fraction": profile.position_size_fraction,
        },
        "risk": {
            "atr_stop_multiplier": profile.atr_stop_multiplier,
            "atr_profit_multiplier": profile.atr_profit_multiplier,
        },
    }


def get_all_profile_names() -> list[str]:
    """Return all available strategy profile names."""
    return list(DEFAULT_PROFILES.keys())
