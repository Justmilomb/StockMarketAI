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
    "watchlists_paper": {"Default": []},
    "protected_tickers": [],
    "active_watchlist": "Default",
    "data_dir": "data",
    "capital": 10,
    "agent": {
        "enabled": False,
        "cadence_seconds": 90,
        "paper_mode": True,
        "daily_max_drawdown_pct": 3.0,
        "max_position_pct": 20.0,
        "max_trades_per_hour": 10,
        "max_chat_workers": 5,
        "chat_model": "sonnet",
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
    "updates": {
        "auto_check": True,
        "check_interval_minutes": 30,
        "skip_version": "",
        "pending_install": None,
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
    """Resolve config path for the desktop app.

    For frozen (PyInstaller) builds, the user's config **always** lives at
    ``%LOCALAPPDATA%\\blank\\config.json`` — the durable per-user location
    owned by :mod:`desktop.paths`. The ``config_path`` argument is ignored
    for frozen runs because the old "exe-adjacent" semantics meant user
    state lived inside ``C:\\Program Files\\blank\\``, which was read-only
    for unprivileged processes and got wiped by the v1 uninstaller.

    For source/dev runs we honour the caller's path (typically
    ``config.json`` resolved against cwd) so hot-reloading against the
    repo-local config keeps working.
    """
    import sys

    if getattr(sys, "frozen", False):
        from desktop.paths import config_path as _user_config_path
        return _user_config_path()

    path = Path(config_path)
    if path.is_absolute() and path.exists():
        return path
    return path


def load_config(config_path: Path | str = "config.json") -> Dict[str, Any]:
    """Load config, creating a default if the file doesn't exist.

    For frozen builds this reads from ``%LOCALAPPDATA%\\blank\\config.json``
    via :func:`resolve_config_path`. On first run (no migration source
    found), we prefer copying the PyInstaller-bundled seed config before
    falling back to :data:`DEFAULT_CONFIG`, so the shipped defaults win
    over the terser Python dict.
    """
    import sys

    path = resolve_config_path(config_path)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            bundle_seed = Path(getattr(sys, "_MEIPASS", "")) / "config.json"
            if bundle_seed.exists():
                import shutil
                shutil.copy2(str(bundle_seed), str(path))
                with path.open("r", encoding="utf-8") as f:
                    return json.load(f)
        with path.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return dict(DEFAULT_CONFIG)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Backfill paper watchlists if missing (migration for existing configs).
    if "watchlists_paper" not in data:
        data["watchlists_paper"] = {name: [] for name in data.get("watchlists", {})}
    return data
