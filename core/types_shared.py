from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal


RegimeType = Literal["trending_up", "trending_down", "mean_reverting", "high_volatility", "unknown"]
AssetClass = Literal["stocks", "crypto", "polymarket"]


@dataclass
class ModelSignal:
    """One model's prediction for one ticker."""

    model_name: str
    ticker: str
    probability: float
    confidence: float
    feature_group: str
    horizon_days: int = 1
    asset_class: AssetClass = "stocks"


@dataclass
class ConsensusResult:
    """Aggregated result per ticker from the investment committee."""

    ticker: str
    probability: float
    consensus_pct: float
    confidence: float
    signal_strength: float
    disagreement: float
    bull_count: int
    bear_count: int
    regime: RegimeType = "unknown"
    horizon_breakdown: Dict[int, float] = field(default_factory=dict)
    asset_class: AssetClass = "stocks"


@dataclass
class RiskAssessment:
    """Risk manager output for a single proposed position."""

    ticker: str
    position_size_dollars: float
    position_size_shares: float
    stop_loss: float
    take_profit: float
    kelly_fraction: float
    risk_score: float
    reason: str = ""
    asset_class: AssetClass = "stocks"


@dataclass
class PersonaSignal:
    """One analyst persona's output for one ticker."""

    persona: str
    ticker: str
    probability: float
    recommendation: str
    confidence: float
    reasoning: str
    asset_class: AssetClass = "stocks"



@dataclass
class FeatureGroup:
    """Metadata about a group of feature columns used by specialist models."""

    name: str
    columns: List[str]
    description: str = ""


@dataclass
class RegimeState:
    """Current market regime classification."""

    regime: RegimeType
    confidence: float
    vix_proxy: float
    breadth: float
    trend_strength: float


# ── Strategy selection types ──────────────────────────────────────────

StrategyProfileName = Literal[
    "conservative", "day_trader", "swing", "crisis_alpha", "trend_follower",
    "scalper", "intraday_momentum",
]


@dataclass(frozen=True)
class StrategyProfile:
    """Complete strategy configuration for one trading style."""

    name: StrategyProfileName
    threshold_buy: float
    threshold_sell: float
    max_positions: int
    position_size_fraction: float
    atr_stop_multiplier: float
    atr_profit_multiplier: float
    min_signal_strength: float
    min_consensus_pct: float
    description: str = ""

    # Model hyperparams — defaults match BacktestConfig defaults
    ensemble_n_models: int = 12
    ensemble_stacking: bool = True
    rf_n_estimators: int = 300
    rf_max_depth: int = 10
    xgb_n_estimators: int = 200
    xgb_max_depth: int = 6
    xgb_learning_rate: float = 0.1
    lgbm_n_estimators: int = 200
    lgbm_num_leaves: int = 31
    knn_n_neighbors: int = 20

    # Prediction horizons
    horizons: tuple[int, ...] = (1, 5)
    horizon_weights: tuple[float, ...] = (0.7, 0.3)

    # Which regimes this profile targets (empty = all)
    target_regimes: tuple[str, ...] = ()

    # Intraday fields (dormant — used when intraday trading is activated)
    bar_interval: str = "1d"
    data_source: str = "yfinance"
    max_holding_bars: int | None = None
    is_intraday: bool = False


@dataclass
class StrategyAssignment:
    """Records which strategy was selected for a ticker and why."""

    ticker: str
    profile: StrategyProfile
    reason: str
    regime: RegimeType
    confidence: float
    asset_class: AssetClass = "stocks"


# Default feature group definitions — populated by features_advanced on import,
# but declared here so other modules can reference the structure.
FEATURE_GROUP_NAMES: List[str] = [
    "trend",
    "momentum",
    "volatility",
    "volume",
    "multi_tf",
    "price",
]


@dataclass
class EnsembleConfig:
    """Configuration for the multi-model ensemble."""

    n_models: int = 6
    stacking_enabled: bool = True
    performance_lookback_days: int = 60
    min_model_weight: float = 0.02
    model_dir: str = "models/ensemble"


@dataclass
class ModelSpec:
    """Specification for a single model in the ensemble."""

    name: str
    model_type: str
    feature_group: str
    hyperparams: Dict[str, float | int | str | bool] = field(default_factory=dict)


# ── Forecaster types ──────────────────────────────────────────────────


@dataclass
class ForecasterSignal:
    """One forecaster family's prediction for one ticker."""

    family: str  # "ml_ensemble" | "statistical" | "deep_learning"
    ticker: str
    probability: float  # P(up) in [0.0, 1.0]
    confidence: float  # [0.0, 1.0]
    forecast_return: float  # Expected return over horizon
    horizon_days: int = 1
    model_name: str = ""  # e.g. "arima", "ets", "nbeats"
    asset_class: AssetClass = "stocks"


# ── Pipeline tracking types ───────────────────────────────────────────

from typing import Any


@dataclass
class PipelineStage:
    """Progress state for one stage of the AI pipeline."""

    name: str
    display_name: str
    status: str = "pending"  # "pending" | "running" | "done" | "error" | "skipped"
    progress: float = 0.0  # 0.0 to 1.0
    current: int = 0
    total: int = 0
    detail: str = ""
    elapsed_seconds: float = 0.0


@dataclass
class PipelineState:
    """Full pipeline progress snapshot for the TUI."""

    stages: List[PipelineStage] = field(default_factory=list)
    is_running: bool = False
    total_elapsed: float = 0.0
    current_stage: str = ""
    # Dashboard stats (shown when idle)
    last_run_duration: float = 0.0
    model_family_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    accuracy_history: List[float] = field(default_factory=list)
