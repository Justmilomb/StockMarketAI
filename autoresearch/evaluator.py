"""
Evaluator for the autoresearch loop.

Two responsibilities:
  1. measure_accuracy  — read the prediction_log from SQLite and compute
                         per-source hit-rates over a sliding window.
  2. backtest          — run generate_signals() on historical data, simulate
                         simple long-only equity trades, and return accuracy +
                         simulated PnL metrics.
"""
from __future__ import annotations

import importlib
import importlib.util
import sqlite3
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AccuracyResult:
    """Per-source hit-rates from the live prediction log."""

    window_days: int
    sources: Dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    total_predictions: int = 0

    def __str__(self) -> str:
        source_lines = "\n".join(
            f"  {src}: {rate:.1%}" for src, rate in sorted(self.sources.items())
        )
        return (
            f"AccuracyResult(window={self.window_days}d, "
            f"overall={self.overall:.1%}, n={self.total_predictions})\n"
            f"{source_lines}"
        )


@dataclass
class BacktestResult:
    """Results from a simulated backtest of a strategy module."""

    accuracy: float
    sharpe_ratio: float
    total_pnl: float
    n_trades: int
    n_correct: int
    start_date: str = ""
    end_date: str = ""

    def __str__(self) -> str:
        return (
            f"BacktestResult(accuracy={self.accuracy:.1%}, "
            f"sharpe={self.sharpe_ratio:.2f}, pnl={self.total_pnl:+.2f}, "
            f"trades={self.n_trades}, correct={self.n_correct})"
        )


# ---------------------------------------------------------------------------
# measure_accuracy
# ---------------------------------------------------------------------------


def measure_accuracy(db_path: str, window_days: int = 7) -> AccuracyResult:
    """Read prediction_log from SQLite and compute per-source hit-rates.

    A prediction is "correct" when:
      - predicted_probability > 0.5 and actual_direction == 1  (called up, went up)
      - predicted_probability <= 0.5 and actual_direction == 0 (called down, went down)

    Only resolved predictions within the last `window_days` are considered.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        return AccuracyResult(window_days=window_days)

    cutoff = (datetime.utcnow() - timedelta(days=window_days)).isoformat()

    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT source, predicted_probability, actual_direction
            FROM prediction_log
            WHERE resolved_at IS NOT NULL
              AND resolved_at >= ?
            """,
            (cutoff,),
        ).fetchall()

    if not rows:
        return AccuracyResult(window_days=window_days)

    # Aggregate per source
    per_source: Dict[str, list] = {}
    for source, prob, direction in rows:
        if direction is None:
            continue
        if source not in per_source:
            per_source[source] = []
        correct = int(
            (prob > 0.5 and direction == 1) or (prob <= 0.5 and direction == 0)
        )
        per_source[source].append(correct)

    source_rates: Dict[str, float] = {}
    all_correct: list[int] = []
    for src, outcomes in per_source.items():
        source_rates[src] = sum(outcomes) / len(outcomes)
        all_correct.extend(outcomes)

    overall = sum(all_correct) / len(all_correct) if all_correct else 0.0

    return AccuracyResult(
        window_days=window_days,
        sources=source_rates,
        overall=overall,
        total_predictions=len(all_correct),
    )


# ---------------------------------------------------------------------------
# backtest helpers
# ---------------------------------------------------------------------------


def _load_strategy_module(strategy_path: Path) -> types.ModuleType:
    """Dynamically load strategy.py from an arbitrary path."""
    mod_name = "_ar_strategy"
    spec = importlib.util.spec_from_file_location(mod_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    # Python 3.14 dataclass decorator needs the module in sys.modules
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def _simple_features(close_series: pd.Series) -> np.ndarray:
    """Produce a naive proxy for prob_up from recent price momentum.

    This is used during backtesting when the full ML pipeline is not available.
    We compute a 5-day return z-score and map it to [0, 1] via sigmoid so the
    strategy logic has a meaningful probability to work with.
    """
    if len(close_series) < 10:
        return np.array([0.5])

    ret_5 = close_series.pct_change(5).iloc[-1]
    std_20 = close_series.pct_change().rolling(20).std().iloc[-1]

    if std_20 == 0 or np.isnan(std_20):
        return np.array([0.5])

    z = ret_5 / std_20
    # sigmoid centred on 0
    prob = float(1.0 / (1.0 + np.exp(-z)))
    return np.array([max(0.01, min(0.99, prob))])


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def backtest(
    strategy_module: types.ModuleType,
    universe_data: Dict[str, pd.DataFrame],
    config: Dict,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """Simulate a simple long-only strategy on historical OHLCV data.

    The simulation walks forward day-by-day over the common date range present
    in `universe_data`.  At each step it:
      1. Builds a `meta_latest` DataFrame with one row per ticker (using the
         close prices up to that day as the feature proxy).
      2. Calls `strategy_module.generate_signals()` with a `StrategyConfig`
         derived from `config["strategy"]`.
      3. Executes BUY signals by allocating `position_size_fraction` of current
         equity to each ticker (up to `max_positions`).
      4. Executes SELL signals by closing that position at today's close.
      5. At the end, closes all open positions at the last available close.

    Returns a `BacktestResult` with accuracy (directional), Sharpe ratio,
    total PnL, number of trades, and number of directionally correct trades.
    """
    if not universe_data:
        return BacktestResult(
            accuracy=0.0, sharpe_ratio=0.0, total_pnl=0.0, n_trades=0, n_correct=0
        )

    strategy_cfg_dict = config.get("strategy", {})
    StrategyConfig = getattr(strategy_module, "StrategyConfig")
    strategy_cfg = StrategyConfig(
        threshold_buy=float(strategy_cfg_dict.get("threshold_buy", 0.55)),
        threshold_sell=float(strategy_cfg_dict.get("threshold_sell", 0.45)),
        max_positions=int(strategy_cfg_dict.get("max_positions", 8)),
        position_size_fraction=float(
            strategy_cfg_dict.get("position_size_fraction", 0.12)
        ),
    )

    generate_signals = getattr(strategy_module, "generate_signals")

    # Build a unified date index (intersection of all ticker dates)
    all_dates: Optional[pd.DatetimeIndex] = None
    for df in universe_data.values():
        idx = pd.DatetimeIndex(df.index)
        all_dates = idx if all_dates is None else all_dates.intersection(idx)

    if all_dates is None or len(all_dates) < 20:
        return BacktestResult(
            accuracy=0.0, sharpe_ratio=0.0, total_pnl=0.0, n_trades=0, n_correct=0
        )

    all_dates = all_dates.sort_values()
    tickers = list(universe_data.keys())

    # Simulation state
    cash = initial_capital
    positions: Dict[str, float] = {}   # ticker -> number of shares held
    entry_prices: Dict[str, float] = {}  # ticker -> price paid
    daily_equity: list[float] = []

    trade_log: list[Dict] = []  # {ticker, entry, exit, direction_correct}

    start_idx = 20  # warm-up for feature computation

    for i, date in enumerate(all_dates[start_idx:], start=start_idx):
        close_today: Dict[str, float] = {}
        for ticker, df in universe_data.items():
            try:
                close_today[ticker] = float(df.loc[date, "Close"])
            except (KeyError, TypeError):
                close_today[ticker] = 0.0

        # --- Build meta_latest and prob_up for this date ---
        rows = []
        prob_arr = []
        for ticker in tickers:
            df = universe_data[ticker]
            history = df["Close"].loc[: date]
            prob = _simple_features(history)[0]
            rows.append({"ticker": ticker, "date": date})
            prob_arr.append(prob)

        if not rows:
            continue

        meta_latest = pd.DataFrame(rows)
        prob_up = np.array(prob_arr)

        held = list(positions.keys())
        signals_df = generate_signals(
            prob_up=prob_up,
            meta_latest=meta_latest,
            config=strategy_cfg,
            held_tickers=held,
        )

        # --- Execute sells first ---
        for _, row in signals_df.iterrows():
            ticker = str(row["ticker"])
            signal = str(row["signal"])
            price = close_today.get(ticker, 0.0)
            if signal == "sell" and ticker in positions and price > 0:
                shares = positions.pop(ticker)
                entry = entry_prices.pop(ticker)
                proceeds = shares * price
                cash += proceeds

                # Was the trade directionally correct?
                # Correct = we bought and it went up, or we shorted (n/a here — just log)
                direction_correct = price >= entry
                trade_log.append(
                    {
                        "ticker": ticker,
                        "entry": entry,
                        "exit": price,
                        "direction_correct": direction_correct,
                    }
                )

        # --- Execute buys ---
        current_equity = cash + sum(
            positions.get(t, 0) * close_today.get(t, 0.0) for t in positions
        )
        for _, row in signals_df.iterrows():
            ticker = str(row["ticker"])
            signal = str(row["signal"])
            price = close_today.get(ticker, 0.0)
            if (
                signal == "buy"
                and ticker not in positions
                and price > 0
                and len(positions) < strategy_cfg.max_positions
            ):
                alloc = current_equity * strategy_cfg.position_size_fraction
                if cash >= alloc:
                    shares = alloc / price
                    positions[ticker] = shares
                    entry_prices[ticker] = price
                    cash -= alloc

        # --- Mark equity ---
        invested = sum(
            positions.get(t, 0) * close_today.get(t, 0.0) for t in positions
        )
        daily_equity.append(cash + invested)

    # --- Close all open positions at last date ---
    last_date = all_dates[-1]
    for ticker, shares in list(positions.items()):
        df = universe_data[ticker]
        try:
            price = float(df.loc[last_date, "Close"])
        except (KeyError, TypeError):
            price = entry_prices.get(ticker, 0.0)
        proceeds = shares * price
        cash += proceeds
        entry = entry_prices.get(ticker, price)
        direction_correct = price >= entry
        trade_log.append(
            {
                "ticker": ticker,
                "entry": entry,
                "exit": price,
                "direction_correct": direction_correct,
            }
        )

    total_pnl = cash - initial_capital
    n_trades = len(trade_log)
    n_correct = sum(1 for t in trade_log if t["direction_correct"])
    accuracy = n_correct / n_trades if n_trades > 0 else 0.0

    # --- Sharpe ratio from daily equity curve ---
    sharpe = _compute_sharpe(daily_equity)

    start_str = str(all_dates[start_idx]) if len(all_dates) > start_idx else ""
    end_str = str(all_dates[-1])

    return BacktestResult(
        accuracy=accuracy,
        sharpe_ratio=sharpe,
        total_pnl=total_pnl,
        n_trades=n_trades,
        n_correct=n_correct,
        start_date=start_str,
        end_date=end_str,
    )


def _compute_sharpe(equity_curve: List[float], risk_free_daily: float = 0.0) -> float:
    """Annualised Sharpe ratio from a list of daily equity values."""
    if len(equity_curve) < 2:
        return 0.0

    eq = np.array(equity_curve, dtype=float)
    returns = np.diff(eq) / eq[:-1]
    excess = returns - risk_free_daily
    std = np.std(excess)
    if std == 0:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(252))
