from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import pandas as pd


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

    # Meta-ensemble / forecaster data
    meta_ensemble_data: Dict[str, Any] = field(default_factory=dict)
    statistical_model_count: int = 0
    deep_model_available: bool = False
    pipeline_last_duration: float = 0.0

    # AI-assigned colour grades override the computed verdict ("GREEN"/"RED"/"ORANGE")
    ai_color_grades: Dict[str, str] = field(default_factory=dict)

    # MiroFish multi-agent simulation data
    mirofish_signals: Dict[str, Any] = field(default_factory=dict)
    mirofish_agent_count: int = 0
    mirofish_sim_count: int = 0

    # Strategy selector — per-ticker profile assignments
    strategy_assignments: Dict[str, Any] = field(default_factory=dict)
    regime_strategy_map: Dict[str, str] = field(default_factory=dict)
