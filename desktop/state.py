"""App state + config helpers for the desktop app.

Historically this was a thin wrapper around ``terminal.state``; the
Textual TUI has now been retired, so the dataclass lives here directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

from types_shared import AssetClass


Mode = Literal["recommendation", "full_auto_limited"]


@dataclass
class AppState:
    """Shared in-memory state for the desktop trading terminal."""

    mode: Mode = "recommendation"
    refresh_interval_seconds: int = 15
    theme: str = "default"
    max_daily_loss: float = 0.05

    capital: float = 100_000.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0

    last_refresh: Optional[datetime] = None

    active_watchlist: str = ""
    selected_ticker: str = ""
    signals: Optional[pd.DataFrame] = None
    active_watchlist_tickers: List[str] = field(default_factory=list)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    position_notes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    history_manager: Any = None
    recent_orders: List[Dict[str, Any]] = field(default_factory=list)
    live_data: Dict[str, Dict[str, float]] = field(default_factory=dict)
    ai_insights: str = ""

    news_sentiment: Dict[str, Any] = field(default_factory=dict)
    market_news: List[Dict[str, Any]] = field(default_factory=list)
    research_findings: List[Dict[str, Any]] = field(default_factory=list)
    swarm_status: Dict[str, Any] = field(default_factory=dict)

    chart_data: List[float] = field(default_factory=list)
    chat_history: List[Dict[str, str]] = field(default_factory=list)

    account_info: Dict[str, Any] = field(default_factory=dict)
    account_metadata: Dict[str, Any] = field(default_factory=dict)

    order_history: List[Dict[str, Any]] = field(default_factory=list)
    dividend_history: List[Dict[str, Any]] = field(default_factory=list)
    transaction_history: List[Dict[str, Any]] = field(default_factory=list)

    pies: List[Dict[str, Any]] = field(default_factory=list)
    broker_is_live: bool = False
    protected_tickers: set[str] = field(default_factory=set)

    # Legacy carry-overs — kept so desktop/app.py's asset-switching and
    # polymarket panel keep working. Fields are written but the legacy
    # computation that populated them has been retired.
    consensus_data: Dict[str, Any] = field(default_factory=dict)
    current_regime: str = "unknown"
    regime_confidence: float = 0.0
    ensemble_model_count: int = 0
    statistical_model_count: int = 0
    pipeline_last_duration: float = 0.0
    ai_color_grades: Dict[str, str] = field(default_factory=dict)
    strategy_assignments: Dict[str, Any] = field(default_factory=dict)
    regime_strategy_map: Dict[str, str] = field(default_factory=dict)

    active_asset_class: AssetClass = "stocks"
    enabled_asset_classes: List[AssetClass] = field(default_factory=lambda: ["stocks"])

    signals_by_asset: Dict[AssetClass, Optional[pd.DataFrame]] = field(default_factory=dict)
    consensus_by_asset: Dict[AssetClass, Dict[str, Any]] = field(default_factory=dict)
    regime_by_asset: Dict[AssetClass, str] = field(default_factory=dict)
    positions_by_asset: Dict[AssetClass, List[Dict[str, Any]]] = field(default_factory=dict)

    polymarket_id_map: Dict[str, str] = field(default_factory=dict)

    # Agent runner state
    agent_running: bool = False
    agent_paper_mode: bool = True
    last_iteration_ts: Optional[datetime] = None
    last_summary: str = ""
    recent_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    agent_journal_tail: List[str] = field(default_factory=list)
    agent_cadence_seconds: int = 0
    agent_iteration_active: bool = False
    agent_wait_start_ts: Optional[datetime] = None

    def switch_asset_class(self, asset_class: AssetClass) -> None:
        """Switch the active asset class, swapping cached data in/out."""
        if asset_class == self.active_asset_class:
            return

        self.signals_by_asset[self.active_asset_class] = self.signals
        self.consensus_by_asset[self.active_asset_class] = self.consensus_data
        self.regime_by_asset[self.active_asset_class] = self.current_regime
        self.positions_by_asset[self.active_asset_class] = self.positions

        self.active_asset_class = asset_class
        self.signals = self.signals_by_asset.get(asset_class)
        self.consensus_data = self.consensus_by_asset.get(asset_class, {})
        self.current_regime = self.regime_by_asset.get(asset_class, "unknown")
        self.positions = self.positions_by_asset.get(asset_class, [])
        self.selected_ticker = ""
        self.chart_data = []


DEFAULT_CONFIG: Dict[str, Any] = {
    "watchlists": {"Default": []},
    "watchlists_paper": {"Default": []},
    "protected_tickers": [],
    "active_watchlist": "Default",
    "data_dir": "data",
    "capital": 10,
    "agent": {
        "enabled": False,
        "cadence_seconds": 45,
        "paper_mode": True,
        "daily_max_drawdown_pct": 3.0,
        "max_position_pct": 20.0,
        "max_trades_per_hour": 10,
        "max_chat_workers": 5,
        "chat_model": "sonnet",
    },
    "ai": {
        "model": "claude-opus-4-7",
        "model_complex": "claude-opus-4-7",
        "model_medium": "claude-sonnet-4-6",
        "model_simple": "claude-haiku-4-5-20251001",
        "model_assessor": "claude-sonnet-4-6",
        "effort_supervisor": "max",
        "effort_decision": "high",
        "effort_info": "medium",
        "effort_research_deep": "high",
        "effort_research_quick": "medium",
        "effort_assessor": "medium",
    },
    "news": {
        "refresh_interval_minutes": 2,
        "scraper_cadence_seconds": 120,
        "scraper_max_workers": 10,
    },
    "updates": {
        "auto_check": True,
        "check_interval_seconds": 60,
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
    """Create an AppState from a parsed config dict."""
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

    Frozen builds always read from ``%LOCALAPPDATA%\\blank\\config.json``
    (the durable per-user location owned by :mod:`desktop.paths`); source
    runs honour the caller's path so hot-reload works against the
    repo-local ``config.json``.
    """
    import sys

    if getattr(sys, "frozen", False):
        from desktop.paths import config_path as _user_config_path
        return _user_config_path()

    path = Path(config_path)
    if path.is_absolute() and path.exists():
        return path
    return path


def _ensure_dev_monitor_password(data: Dict[str, Any], path: Path) -> bool:
    """Back-fill a per-install UUID password for telemetry auth.

    Why: every client ships with dev_monitor enabled by default so the
    admin dashboard can see activity without manual setup, but the
    server rejects blank Bearer tokens. Generating a stable UUID on
    first load gives each install an auth token that persists across
    restarts.
    """
    import uuid

    dm = data.get("dev_monitor")
    if not isinstance(dm, dict):
        dm = {}
        data["dev_monitor"] = dm
    if not dm.get("password"):
        dm["password"] = str(uuid.uuid4())
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
        return True
    return False


def load_config(config_path: Path | str = "config.json") -> Dict[str, Any]:
    """Load config, creating a default if the file doesn't exist."""
    import sys

    path = resolve_config_path(config_path)

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        if getattr(sys, "frozen", False):
            seed = Path(getattr(sys, "_MEIPASS", "")) / "config.default.json"
        else:
            seed = Path(__file__).resolve().parent.parent / "config.default.json"
        if seed.exists():
            shutil.copy2(str(seed), str(path))
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            with path.open("w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            data = dict(DEFAULT_CONFIG)
        _ensure_dev_monitor_password(data, path)
        return data

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "watchlists_paper" not in data:
        data["watchlists_paper"] = {name: [] for name in data.get("watchlists", {})}
    _ensure_dev_monitor_password(data, path)
    try:
        from core.config_schema import AppConfig
        merged = AppConfig.model_validate(data).model_dump()
        merged.update(data)
        return merged
    except Exception:
        return data
