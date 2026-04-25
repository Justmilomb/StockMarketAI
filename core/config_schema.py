"""Pydantic schema for ``config.json``.

Validates the live subset of keys actually read by the agent loop, the
desktop app, and the server. Unknown keys are allowed (``extra="allow"``)
so legacy blocks in older config files don't break startup — they're
simply ignored by the code.

Usage:

    from core.config_schema import AppConfig
    raw = json.load(open("config.json"))
    cfg = AppConfig.model_validate(raw).model_dump()
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


EffortLevel = Literal["low", "medium", "high", "max"]


class AIConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str = "claude-opus-4-7"
    model_complex: str = "claude-opus-4-7"
    model_medium: str = "claude-sonnet-4-6"
    model_simple: str = "claude-haiku-4-5-20251001"
    model_assessor: str = "claude-sonnet-4-6"
    effort_supervisor: EffortLevel = "max"
    effort_decision: EffortLevel = "high"
    effort_info: EffortLevel = "medium"
    effort_research_deep: EffortLevel = "high"
    effort_research_quick: EffortLevel = "medium"
    effort_assessor: EffortLevel = "medium"


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    cadence_seconds: int = Field(default=45, ge=15)
    paper_mode: bool = True
    daily_max_drawdown_pct: float = 3.0
    max_position_pct: float = 20.0
    max_trades_per_hour: int = Field(default=10, ge=0)
    max_chat_workers: int = Field(default=5, ge=1)
    chat_model: str = "sonnet"
    # Path to the per-install trader personality JSON — stores the
    # agent's unique seed, self-authored rules and lesson log. Never
    # synced across installs.
    trader_personality_path: str = "data/trader_personality.json"


class BrokerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = "log"
    api_key_env: str = "T212_API_KEY"
    secret_key_env: str = "T212_SECRET_KEY"
    base_url: str = "https://live.trading212.com"
    practice: bool = True


class PaperBrokerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    state_path: str = "data/paper_state.json"
    audit_path: str = "logs/paper_orders.jsonl"
    starting_cash: float = 100.0
    currency: str = "GBP"
    # Maximum fraction the live price may diverge from a position's
    # entry before the broker refuses to fill a SELL. Guards against
    # bad yfinance ticks causing catastrophic fills (2026-04-20 BARC).
    fill_sanity_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    # ``get_live_price`` warns the agent when the broker-cached price
    # and a fresh yfinance fetch diverge by more than this fraction.
    divergence_warn_threshold: float = Field(default=0.05, ge=0.0, le=1.0)


class NewsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    refresh_interval_minutes: int = 2
    scraper_cadence_seconds: int = 120
    scraper_max_workers: int = 10


class ScraperVisionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    max_calls_per_day: int = Field(default=500, ge=0)


class ScrapersConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    youtube_live_vision: ScraperVisionConfig = Field(default_factory=ScraperVisionConfig)


class TerminalConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["recommendation", "full_auto_limited"] = "recommendation"
    refresh_interval_seconds: int = 30
    theme: str = "default"
    max_daily_loss: float = 0.05


class UpdatesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    auto_check: bool = True
    check_interval_seconds: int = 60
    skip_version: str = ""
    pending_install: Optional[Any] = None


class ForecastingConfig(BaseModel):
    """Forecasting ensemble toggles.

    Each backend is gated by an ``*_enabled`` flag so a machine that
    can't install (e.g.) TimesFM can still run the rest of the ensemble.
    """

    model_config = ConfigDict(extra="allow")

    ensemble_enabled: bool = True
    kronos_enabled: bool = True
    chronos_enabled: bool = True
    timesfm_enabled: bool = True
    tft_enabled: bool = False
    meta_model_path: str = "models/meta_learner.json"
    default_horizon_minutes: int = 60


class NlpConfig(BaseModel):
    """FinBERT + sentiment config."""

    model_config = ConfigDict(extra="allow")

    finbert_enabled: bool = True
    finbert_model_id: str = "ProsusAI/finbert"
    max_texts_per_call: int = 32


class ExecutionConfig(BaseModel):
    """Execution-strategy defaults for smart order routing."""

    model_config = ConfigDict(extra="allow")

    default_strategy: Literal["market", "vwap", "twap"] = "market"
    vwap_slices_per_hour: int = 4
    twap_slices_per_hour: int = 6


class AppConfig(BaseModel):
    """Top-level config shape. Unknown keys pass through untouched."""

    model_config = ConfigDict(extra="allow")

    watchlists: Dict[str, List[str]] = Field(default_factory=lambda: {"Default": []})
    watchlists_paper: Dict[str, List[str]] = Field(default_factory=lambda: {"Default": []})
    protected_tickers: List[str] = Field(default_factory=list)
    active_watchlist: str = "Default"
    data_dir: str = "data"
    capital: float = 10.0

    ai: AIConfig = Field(default_factory=AIConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    paper_broker: PaperBrokerConfig = Field(default_factory=PaperBrokerConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    scrapers: ScrapersConfig = Field(default_factory=ScrapersConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    updates: UpdatesConfig = Field(default_factory=UpdatesConfig)
    forecasting: ForecastingConfig = Field(default_factory=ForecastingConfig)
    nlp: NlpConfig = Field(default_factory=NlpConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    active_asset_class: str = "stocks"
    enabled_asset_classes: List[str] = Field(default_factory=lambda: ["stocks"])


def validate_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a raw config dict and return the normalised dict form."""
    return AppConfig.model_validate(raw or {}).model_dump()
