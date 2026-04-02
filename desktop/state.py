"""App state wrapper for the PySide6 desktop app.

Reuses the existing AppState dataclass from terminal/state.py unchanged.
This module provides a thin wrapper that can be extended with Qt-specific
signalling if needed in future.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from terminal.state import AppState

# Minimal valid config — enough to boot the app without crashing.
# User is prompted to import their real config on first launch.
DEFAULT_CONFIG: Dict[str, Any] = {
    "watchlists": {"Default": []},
    "protected_tickers": [],
    "active_watchlist": "Default",
    "start_date": "2018-01-01",
    "end_date": "2026-12-31",
    "data_dir": "data",
    "model_path": "models/rf_tomorrow_up.joblib",
    "strategy": {
        "threshold_buy": 0.58,
        "threshold_sell": 0.42,
        "max_positions": 8,
        "position_size_fraction": 0.12,
    },
    "capital": 10,
    "ai": {
        "sklearn_weight": 0.5,
        "ai_weight": 0.3,
        "news_weight": 0.2,
        "retrain_on_start": True,
        "retrain_interval_hours": 24,
    },
    "claude": {
        "model": "claude-sonnet-4-20250514",
        "model_complex": "claude-opus-4-6",
        "model_medium": "claude-sonnet-4-20250514",
        "model_simple": "claude-haiku-4-5-20251001",
    },
    "news": {"refresh_interval_minutes": 5},
    "broker": {
        "type": "log",
        "api_key_env": "T212_API_KEY",
        "secret_key_env": "T212_SECRET_KEY",
        "base_url": "https://live.trading212.com",
        "practice": True,
    },
    "ensemble": {
        "n_models": 12,
        "stacking_enabled": True,
        "performance_lookback_days": 90,
        "min_model_weight": 0.02,
    },
    "timeframes": {"horizons": [1, 5, 20], "weights": {"1": 0.7, "5": 0.2, "20": 0.1}},
    "regime": {"lookback_days": 60, "spy_ticker": "SPY", "regime_weight_adjustment": 0.3},
    "risk": {
        "kelly_fraction_cap": 0.35,
        "max_position_pct": 0.20,
        "atr_stop_multiplier": 1.8,
        "atr_profit_multiplier": 2.5,
        "drawdown_threshold": 0.15,
        "drawdown_size_reduction": 0.5,
        "min_position_dollars": 1.0,
        "fractional_shares": True,
    },
    "strategy_profiles": {
        "enabled": True,
        "regime_mapping": {
            "trending_up": "trend_follower",
            "trending_down": "conservative",
            "mean_reverting": "day_trader",
            "high_volatility": "crisis_alpha",
            "unknown": "swing",
        },
    },
    "claude_personas": {
        "enabled": True,
        "personas": ["technical", "fundamental", "momentum", "contrarian", "risk"],
    },
    "consensus": {"min_consensus_pct": 60, "disagreement_penalty": 0.5},
    "forecasters": {
        "statistical": {"enabled": True, "arima_order": [1, 1, 1], "cache_dir": "models/statistical"},
    },
    "pipeline": {"show_progress": True},
    "terminal": {
        "mode": "recommendation", "refresh_interval_seconds": 30,
        "theme": "default", "max_daily_loss": 0.05,
    },
    "active_asset_class": "stocks",
    "enabled_asset_classes": ["stocks"],
}


def init_state(config: Dict[str, Any]) -> AppState:
    """Create an AppState from a parsed config dict.

    Mirrors TradingTerminalApp._init_state() so the desktop app
    initialises identically to the Textual TUI.
    """
    t_cfg = config.get("terminal", {})
    return AppState(
        mode=t_cfg.get("mode", "recommendation"),
        refresh_interval_seconds=t_cfg.get("refresh_interval_seconds", 30),
        capital=t_cfg.get("capital", 10000.0),
        max_daily_loss=t_cfg.get("max_daily_loss", 0.05),
        active_watchlist=config.get("active_watchlist", "Default"),
        protected_tickers=set(config.get("protected_tickers", [])),
        active_asset_class=config.get("active_asset_class", "stocks"),
        enabled_asset_classes=config.get("enabled_asset_classes", ["stocks"]),
    )


def resolve_config_path(config_path: Path | str = "config.json") -> Path:
    """Resolve config path, preferring exe-adjacent file for frozen builds."""
    import sys

    path = Path(config_path)
    if path.is_absolute() and path.exists():
        return path

    # Frozen exe: look next to the exe first, then _MEIPASS bundle
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        exe_adjacent = exe_dir / path.name
        if exe_adjacent.exists():
            return exe_adjacent
        bundle_path = Path(sys._MEIPASS) / path.name
        if bundle_path.exists():
            return bundle_path
        # Neither exists — will create next to exe
        return exe_adjacent

    # Source: resolve relative to cwd
    return path


def load_config(config_path: Path | str = "config.json") -> Dict[str, Any]:
    """Load config, creating a default if the file doesn't exist.

    For frozen builds: looks next to the exe first, then the bundle.
    Creates a default config.json if nothing is found.
    """
    path = resolve_config_path(config_path)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return dict(DEFAULT_CONFIG)

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
