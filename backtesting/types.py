"""Dataclasses for the backtesting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    """Full configuration for a backtest run."""

    # -- Data range -----------------------------------------------------------
    start_date: str = "2018-01-01"
    end_date: str = "2026-03-27"
    tickers: List[str] = field(default_factory=list)

    # -- Walk-forward ---------------------------------------------------------
    min_train_days: int = 252         # Minimum training window (~1 year)
    test_window_days: int = 20        # Out-of-sample test period per fold
    step_days: int = 20               # How far to slide the window each fold
    expanding_window: bool = True     # True = expanding, False = rolling

    # -- Trade simulation -----------------------------------------------------
    initial_capital: float = 100_000.0
    max_positions: int = 8
    position_size_fraction: float = 0.12
    threshold_buy: float = 0.55
    threshold_sell: float = 0.45
    slippage_pct: float = 0.001       # 0.1% slippage per trade
    commission_per_trade: float = 0.0  # Flat commission (T212 is zero)

    # -- Stop-loss / take-profit ----------------------------------------------
    use_stops: bool = True
    atr_stop_multiplier: float = 1.5
    atr_profit_multiplier: float = 2.0

    # -- Signal sources -------------------------------------------------------
    use_ensemble: bool = True
    use_statistical: bool = True
    use_mirofish: bool = False        # Kept for backward compat with existing database records
    mirofish_n_sims: int = 8          # Fewer sims in backtest for speed

    # -- Ensemble hyperparameters (agent-tuneable) ----------------------------
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

    # -- Execution ------------------------------------------------------------
    n_processes: int | None = None    # None = all cores
    mode: Literal["fast", "full"] = "full"

    # -- Multi-capital tiers ---------------------------------------------------
    capital_tiers: List[float] = field(default_factory=list)  # e.g. [10, 100, 1000]

    # -- Strategy selection ----------------------------------------------------
    use_strategy_selector: bool = False
    strategy_profiles_override: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardSplit:
    """One train/test window in the walk-forward sequence."""

    fold_id: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_days: int
    test_days: int


# ---------------------------------------------------------------------------
# Trade tracking
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """An open position in the simulated portfolio."""

    ticker: str
    entry_date: date
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    signal_prob: float               # P(up) when entry was triggered
    strategy_profile: str = ""


@dataclass
class TradeRecord:
    """A completed (closed) trade."""

    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    hold_days: int
    exit_reason: str                 # "signal" | "stop_loss" | "take_profit" | "end_of_fold"
    signal_prob: float               # P(up) at entry
    strategy_profile: str = ""
    capital_tier: float = 0.0        # Starting capital for this simulation run


@dataclass
class DailySnapshot:
    """Portfolio state at end of one trading day."""

    date: date
    equity: float                    # Cash + position market value
    cash: float
    n_positions: int
    daily_return: float              # % change from previous day
    drawdown: float                  # % below peak equity


# ---------------------------------------------------------------------------
# Fold result
# ---------------------------------------------------------------------------

@dataclass
class FoldResult:
    """Result from one walk-forward fold."""

    fold_id: int
    split: WalkForwardSplit
    trades: List[TradeRecord]
    daily_snapshots: List[DailySnapshot]
    predictions: List[Dict[str, float]]   # [{ticker: prob_up}, ...]
    actuals: List[Dict[str, bool]]        # [{ticker: went_up}, ...]

    # Fast-mode metrics (signal quality)
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    n_predictions: int = 0
    n_correct: int = 0


# ---------------------------------------------------------------------------
# Aggregate result
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """Complete backtest output."""

    config: BacktestConfig
    folds: List[FoldResult]
    metrics: Optional[PerformanceMetrics] = None
    total_duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

@dataclass
class PerformanceMetrics:
    """Computed performance statistics from a backtest."""

    # -- Returns --------------------------------------------------------------
    total_return_pct: float = 0.0
    annualised_return_pct: float = 0.0
    buy_and_hold_return_pct: float = 0.0   # Benchmark comparison

    # -- Risk-adjusted --------------------------------------------------------
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0              # Annual return / max drawdown

    # -- Drawdown -------------------------------------------------------------
    max_drawdown_pct: float = 0.0
    avg_drawdown_pct: float = 0.0
    max_drawdown_days: int = 0             # Longest time underwater

    # -- Trade statistics -----------------------------------------------------
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0            # Gross profit / gross loss
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    avg_hold_days: float = 0.0

    # -- Signal quality -------------------------------------------------------
    signal_accuracy: float = 0.0          # Overall hit rate
    signal_precision: float = 0.0         # Precision for buy signals
    signal_recall: float = 0.0

    # -- Attribution ----------------------------------------------------------
    per_source_accuracy: Dict[str, float] = field(default_factory=dict)

    # -- Equity curve data (for plotting) ------------------------------------
    equity_curve: List[float] = field(default_factory=list)
    equity_dates: List[str] = field(default_factory=list)
    drawdown_curve: List[float] = field(default_factory=list)
