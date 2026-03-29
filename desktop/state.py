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
    )


def load_config(config_path: Path | str = "config.json") -> Dict[str, Any]:
    """Load and return the JSON config file.

    Checks the PyInstaller bundle dir first (frozen .exe), then the
    current working directory.
    """
    import sys

    path = Path(config_path)

    # In a frozen PyInstaller build, bundled data lives in sys._MEIPASS
    if not path.is_absolute() and getattr(sys, "frozen", False):
        bundle_path = Path(sys._MEIPASS) / path
        if bundle_path.exists():
            path = bundle_path

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
