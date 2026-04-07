from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import pandas as pd

from types_shared import AssetClass


Mode = Literal["recommendation", "full_auto_limited"]


@dataclass
class AppState:
    """
    Shared in-memory state for the trading terminal.
    """

    mode: Mode = "recommendation"
    refresh_interval_seconds: int = 15
    theme: str = "default"
    max_daily_loss: float = 0.05  # 5% of capital

    capital: float = 100_000.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0

    last_refresh: Optional[datetime] = None

    active_watchlist: str = ""
    selected_ticker: str = ""
    signals: Optional[pd.DataFrame] = None
    positions: List[Dict[str, Any]] = field(default_factory=list)
    position_notes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    history_manager: Any = None
    recent_orders: List[Dict[str, Any]] = field(default_factory=list)
    live_data: Dict[str, Dict[str, float]] = field(default_factory=dict)
    ai_insights: str = "Press 'i' to generate AI portfolio insights."

    # News agent data
    news_sentiment: Dict[str, Any] = field(default_factory=dict)

    # Chart data (list of close prices for selected ticker)
    chart_data: List[float] = field(default_factory=list)

    # Chat history
    chat_history: List[Dict[str, str]] = field(default_factory=list)

    # Account info from broker
    account_info: Dict[str, Any] = field(default_factory=dict)
    account_metadata: Dict[str, Any] = field(default_factory=dict)

    # History data (cached from broker API)
    order_history: List[Dict[str, Any]] = field(default_factory=list)
    dividend_history: List[Dict[str, Any]] = field(default_factory=list)
    transaction_history: List[Dict[str, Any]] = field(default_factory=list)

    # Pies data
    pies: List[Dict[str, Any]] = field(default_factory=list)

    # Broker connection status
    broker_is_live: bool = False

    # Protected tickers (never-trade list)
    protected_tickers: set[str] = field(default_factory=set)

    # Consensus / ensemble data
    consensus_data: Dict[str, Any] = field(default_factory=dict)
    current_regime: str = "unknown"
    regime_confidence: float = 0.0
    ensemble_model_count: int = 0

    # Forecaster data
    statistical_model_count: int = 0
    pipeline_last_duration: float = 0.0

    # AI-assigned colour grades override the computed verdict ("GREEN"/"RED"/"ORANGE")
    ai_color_grades: Dict[str, str] = field(default_factory=dict)

    # Strategy selector — per-ticker profile assignments
    strategy_assignments: Dict[str, Any] = field(default_factory=dict)
    regime_strategy_map: Dict[str, str] = field(default_factory=dict)

    # ── Multi-asset state ────────────────────────────────────────────
    active_asset_class: AssetClass = "stocks"
    enabled_asset_classes: List[AssetClass] = field(default_factory=lambda: ["stocks"])

    # ── Research / AutoResearch state ──────────────────────────────────
    research_experiments: List[Dict[str, Any]] = field(default_factory=list)
    research_best_score: float = 0.0
    research_total_experiments: int = 0
    research_current_config: Dict[str, Any] = field(default_factory=dict)
    research_is_running: bool = False
    research_live_progress: Dict[str, Any] = field(default_factory=dict)

    # Polymarket: maps truncated question text → condition_id for chart lookups
    polymarket_id_map: Dict[str, str] = field(default_factory=dict)

    # Per-asset caches — the active asset's data lives in the fields above
    # (signals, consensus_data, etc.). These dicts store background data
    # for inactive asset classes so switching is instant.
    signals_by_asset: Dict[AssetClass, Optional[pd.DataFrame]] = field(default_factory=dict)
    consensus_by_asset: Dict[AssetClass, Dict[str, Any]] = field(default_factory=dict)
    regime_by_asset: Dict[AssetClass, str] = field(default_factory=dict)
    positions_by_asset: Dict[AssetClass, List[Dict[str, Any]]] = field(default_factory=dict)

    def switch_asset_class(self, asset_class: AssetClass) -> None:
        """Switch the active asset class, swapping cached data in/out."""
        if asset_class == self.active_asset_class:
            return

        # Save current asset's live data to cache
        self.signals_by_asset[self.active_asset_class] = self.signals
        self.consensus_by_asset[self.active_asset_class] = self.consensus_data
        self.regime_by_asset[self.active_asset_class] = self.current_regime
        self.positions_by_asset[self.active_asset_class] = self.positions

        # Load new asset's data from cache
        self.active_asset_class = asset_class
        self.signals = self.signals_by_asset.get(asset_class)
        self.consensus_data = self.consensus_by_asset.get(asset_class, {})
        self.current_regime = self.regime_by_asset.get(asset_class, "unknown")
        self.positions = self.positions_by_asset.get(asset_class, [])
        self.selected_ticker = ""
        self.chart_data = []
