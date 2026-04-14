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
# Phase 3: strategy / ensemble / regime / risk / strategy_profiles /
# claude_personas / consensus / forecasters / pipeline / timeframes sections
# are gone. The agent is the brain and owns its own risk rules.
DEFAULT_CONFIG: Dict[str, Any] = {
    "watchlists": {"Default": []},
    "protected_tickers": [],
    "active_watchlist": "Default",
    "data_dir": "data",
    "capital": 10,
    "agent": {
        "enabled": False,
        "cadence_seconds": 90,
        "max_tool_calls_per_iter": 40,
        "max_iter_seconds": 360,
        "paper_mode": True,
        "daily_max_drawdown_pct": 3.0,
        "max_position_pct": 20.0,
        "max_trades_per_hour": 10,
    },
    "claude": {
        "model": "claude-sonnet-4-20250514",
        "model_complex": "claude-opus-4-6",
        "model_medium": "claude-sonnet-4-20250514",
        "model_simple": "claude-haiku-4-5-20251001",
    },
    "news": {
        "refresh_interval_minutes": 5,
        "scraper_cadence_seconds": 300,
    },
    "broker": {
        "type": "log",
        "api_key_env": "T212_API_KEY",
        "secret_key_env": "T212_SECRET_KEY",
        "base_url": "https://live.trading212.com",
        "practice": True,
    },
    "terminal": {
        "mode": "recommendation",
        "refresh_interval_seconds": 30,
        "theme": "default",
        "max_daily_loss": 0.05,
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
    """Resolve config path, preferring exe-adjacent file for frozen builds.

    For frozen (PyInstaller) builds, always returns an exe-adjacent path so
    writes persist across restarts.  On first run the bundled seed config is
    copied next to the exe; subsequent runs use that copy directly.
    """
    import shutil
    import sys

    path = Path(config_path)
    if path.is_absolute() and path.exists():
        return path

    # Frozen exe: always write next to the exe so state persists
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        exe_adjacent = exe_dir / path.name
        if exe_adjacent.exists():
            return exe_adjacent
        # First run: copy bundled seed config to exe-adjacent
        bundle_path = Path(sys._MEIPASS) / path.name
        if bundle_path.exists():
            shutil.copy2(str(bundle_path), str(exe_adjacent))
            return exe_adjacent
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
