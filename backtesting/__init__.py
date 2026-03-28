"""Backtesting engine — walk-forward validation and trade simulation.

Replays historical signals against price data to measure real out-of-sample
performance.  Two modes:

    FastBacktest  — accuracy-only walk-forward (signal quality, minutes)
    FullBacktest  — day-by-day trade simulation with P&L (realistic, longer)

Public API:
    BacktestRunner       — parallel walk-forward executor
    BacktestEngine       — core engine (fast + full modes)
    compute_metrics      — performance calculation from trade records
"""

from backtesting.engine import BacktestEngine
from backtesting.metrics import compute_metrics
from backtesting.runner import BacktestRunner
from backtesting.types import BacktestConfig, BacktestResult, PerformanceMetrics

__all__ = [
    "BacktestEngine",
    "BacktestRunner",
    "compute_metrics",
    "BacktestConfig",
    "BacktestResult",
    "PerformanceMetrics",
]
