"""Conditional strategy backtesting tools.

Lets the agent test indicator-based entry/exit rules over historical
OHLCV before committing capital. Entry and exit conditions are
structured dicts with an indicator, field, operator, and value — Claude
composes these from its trading thesis and gets back hard metrics
(Sharpe, win rate, profit factor, max drawdown).

This replaces the need for the deleted ML pipeline: instead of 12
models voting on a signal, Claude reasons about the setup, tests it
here, and decides whether the numbers support the thesis.

Stop/target resolution is pessimistic (same as ``backtest_tools.py``):
if a bar's low hits the stop *and* its high hits the target, the stop
fired first.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from core.agent._sdk import tool

from core.agent.context import get_agent_context
from core.agent.tools.indicator_tools import _INDICATOR_REGISTRY


# ── shared helpers ───────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(tool_name: str, payload: Dict[str, Any], tags: str = "backtest") -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, ?)",
                (ctx.iteration_id, tool_name, json.dumps(payload, default=str), tags),
            )
    except Exception:
        pass


def _clip_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(value or default)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))


def _clip_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        n = float(value if value is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))


def _fetch_daily(ticker: str, lookback_days: int) -> pd.DataFrame:
    from data_loader import fetch_ticker_data  # type: ignore

    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days + 10)
    df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()
    return df


# ── condition evaluation ─────────────────────────────────────────────

def _resolve_value(
    df: pd.DataFrame,
    value: Any,
    row_idx: int,
) -> Optional[float]:
    """Resolve a condition value — literal number or column reference."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value in df.columns:
        val = df.iloc[row_idx][value]
        return float(val) if pd.notna(val) else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _eval_condition(
    df: pd.DataFrame,
    cond: Dict[str, Any],
    row_idx: int,
) -> bool:
    """Evaluate a single condition at row_idx. Returns False on any error."""
    field = str(cond.get("field", ""))
    operator = str(cond.get("operator", "")).lower()
    value = cond.get("value")

    if field not in df.columns:
        return False

    current = df.iloc[row_idx][field]
    if pd.isna(current):
        return False
    current = float(current)

    target = _resolve_value(df, value, row_idx)
    if target is None:
        return False

    if operator == "gt":
        return current > target
    if operator == "lt":
        return current < target
    if operator == "gte":
        return current >= target
    if operator == "lte":
        return current <= target

    # Cross operators need the previous bar.
    if row_idx < 1:
        return False
    prev = df.iloc[row_idx - 1][field]
    if pd.isna(prev):
        return False
    prev = float(prev)
    prev_target = _resolve_value(df, value, row_idx - 1)
    if prev_target is None:
        return False

    if operator == "crosses_above":
        return prev <= prev_target and current > target
    if operator == "crosses_below":
        return prev >= prev_target and current < target

    return False


def _all_conditions_met(
    df: pd.DataFrame,
    conditions: List[Dict[str, Any]],
    row_idx: int,
) -> bool:
    """All conditions must be True (AND logic)."""
    if not conditions:
        return False
    return all(_eval_condition(df, c, row_idx) for c in conditions)


# ── backtest engine ──────────────────────────────────────────────────

def _run_strategy_backtest(
    df: pd.DataFrame,
    entry_conditions: List[Dict[str, Any]],
    exit_conditions: List[Dict[str, Any]],
    stop_pct: float,
    target_pct: float,
    max_hold_days: int,
    initial_capital: float,
) -> Dict[str, Any]:
    """Walk-forward bar-by-bar strategy simulation."""
    if df.empty or len(df) < 5:
        return {"error": "not enough data", "n_trades": 0}

    closes = df["Close"].to_numpy(dtype=float)
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    n_bars = len(closes)

    stop_frac = stop_pct / 100.0
    target_frac = target_pct / 100.0

    trades: List[Dict[str, Any]] = []
    equity = initial_capital
    peak_equity = equity
    max_drawdown = 0.0

    equity_curve: List[Dict[str, Any]] = []
    in_position = False
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0
    target_price = 0.0

    for i in range(1, n_bars):
        if not in_position:
            # Check entry conditions.
            if _all_conditions_met(df, entry_conditions, i):
                entry_price = closes[i]
                if entry_price <= 0:
                    continue
                entry_idx = i
                stop_price = entry_price * (1.0 - stop_frac)
                target_price = entry_price * (1.0 + target_frac)
                in_position = True
        else:
            held_days = i - entry_idx
            exit_price: Optional[float] = None
            exit_reason = ""

            # Pessimistic: stop checked before target.
            if lows[i] <= stop_price:
                exit_price = stop_price
                exit_reason = "stop"
            elif highs[i] >= target_price:
                exit_price = target_price
                exit_reason = "target"
            elif exit_conditions and _all_conditions_met(df, exit_conditions, i):
                exit_price = closes[i]
                exit_reason = "exit_condition"
            elif held_days >= max_hold_days:
                exit_price = closes[i]
                exit_reason = "max_hold"

            if exit_price is not None:
                ret_pct = (exit_price / entry_price - 1.0) * 100.0
                shares = equity / entry_price
                pnl = shares * (exit_price - entry_price)
                equity += pnl

                trades.append({
                    "entry_date": str(df.index[entry_idx].date()) if hasattr(df.index[entry_idx], "date") else str(df.index[entry_idx]),
                    "exit_date": str(df.index[i].date()) if hasattr(df.index[i], "date") else str(df.index[i]),
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "return_pct": round(ret_pct, 3),
                    "hold_days": held_days,
                    "exit_reason": exit_reason,
                })

                peak_equity = max(peak_equity, equity)
                dd = (peak_equity - equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0
                max_drawdown = max(max_drawdown, dd)
                in_position = False

        # Sample equity curve (at most 50 points).
        equity_curve.append({"bar": i, "equity": round(equity, 2)})

    # Close any open position at last bar.
    if in_position:
        exit_price = closes[-1]
        ret_pct = (exit_price / entry_price - 1.0) * 100.0
        shares = equity / entry_price
        pnl = shares * (exit_price - entry_price)
        equity += pnl
        held_days = n_bars - 1 - entry_idx
        trades.append({
            "entry_date": str(df.index[entry_idx].date()) if hasattr(df.index[entry_idx], "date") else str(df.index[entry_idx]),
            "exit_date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
            "entry_price": round(entry_price, 4),
            "exit_price": round(float(exit_price), 4),
            "return_pct": round(ret_pct, 3),
            "hold_days": held_days,
            "exit_reason": "still_open",
        })

    n_trades = len(trades)
    if n_trades == 0:
        return {
            "n_trades": 0,
            "total_return_pct": 0.0,
            "win_rate": 0.0,
            "note": "no entry conditions were triggered in this period",
        }

    returns = [t["return_pct"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    total_return = (equity / initial_capital - 1.0) * 100.0
    win_rate = len(wins) / n_trades * 100.0
    avg_return = sum(returns) / n_trades
    avg_hold = sum(t["hold_days"] for t in trades) / n_trades

    # Annualised Sharpe (assuming 252 trading days).
    if len(returns) > 1:
        ret_std = float(np.std(returns, ddof=1))
        if ret_std > 0:
            trades_per_year = 252.0 / max(avg_hold, 1)
            sharpe = (avg_return / ret_std) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Downsample equity curve to at most 50 points.
    if len(equity_curve) > 50:
        step = len(equity_curve) // 50
        equity_curve = equity_curve[::step][:50]

    return {
        "n_trades": n_trades,
        "total_return_pct": round(total_return, 2),
        "win_rate": round(win_rate, 2),
        "avg_return_pct": round(avg_return, 3),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "avg_hold_days": round(avg_hold, 1),
        "best_trade_pct": round(max(returns), 3),
        "worst_trade_pct": round(min(returns), 3),
        "final_equity": round(equity, 2),
        "initial_capital": initial_capital,
        "trades": trades[-10:],  # last 10 trades to keep token cost down
        "equity_curve": equity_curve,
    }


# ── tool ─────────────────────────────────────────────────────────────

@tool(
    "backtest_strategy",
    (
        "Run a rule-based strategy over historical daily OHLCV and return "
        "performance metrics. Define entry and exit conditions using "
        "technical indicators (rsi, sma, ema, bbands, macd, stoch, adx, "
        "atr, obv). Each condition is a dict with 'indicator', 'field', "
        "'operator' (gt/lt/gte/lte/crosses_above/crosses_below), and "
        "'value' (a number or another indicator field name as a string). "
        "Multiple conditions are AND-joined. Example entry: "
        "[{\"indicator\": \"rsi\", \"field\": \"rsi\", \"operator\": \"lt\", \"value\": 30}]. "
        "Returns total_return_pct, win_rate, sharpe_ratio, max_drawdown_pct, "
        "profit_factor, n_trades, avg_hold_days, best/worst trade. "
        "Use this to validate a trading thesis before committing capital."
    ),
    {
        "ticker": str,
        "entry_conditions": list,
        "exit_conditions": list,
        "stop_pct": float,
        "target_pct": float,
        "max_hold_days": int,
        "lookback_days": int,
        "initial_capital": float,
    },
)
async def backtest_strategy(args: Dict[str, Any]) -> Dict[str, Any]:
    # Preserve original case — Trading 212 LSE tickers use a lowercase
    # `l` marker (e.g. ``RRl_EQ``) that case-normalisation would destroy.
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    entry_conditions = args.get("entry_conditions", [])
    exit_conditions = args.get("exit_conditions", [])
    if not entry_conditions:
        return _text_result({"error": "at least one entry_condition is required"})

    stop_pct = _clip_float(args.get("stop_pct"), 0.1, 50.0, 5.0)
    target_pct = _clip_float(args.get("target_pct"), 0.1, 200.0, 10.0)
    max_hold_days = _clip_int(args.get("max_hold_days"), 1, 120, 30)
    lookback_days = _clip_int(args.get("lookback_days"), 90, 730, 365)
    initial_capital = _clip_float(args.get("initial_capital"), 1.0, 1_000_000.0, 100.0)

    # Collect all referenced indicators from conditions.
    all_conditions = list(entry_conditions) + list(exit_conditions)
    needed_indicators: set[str] = set()
    for cond in all_conditions:
        ind = str(cond.get("indicator", "")).lower()
        if ind in _INDICATOR_REGISTRY:
            needed_indicators.add(ind)

    if not needed_indicators:
        return _text_result({
            "error": "no valid indicators referenced in conditions",
            "valid_indicators": sorted(_INDICATOR_REGISTRY.keys()),
        })

    try:
        df = _fetch_daily(ticker, lookback_days)
    except Exception as exc:
        _journal("backtest_strategy", {"ticker": ticker, "error": str(exc)}, "backtest,error")
        return _text_result({"error": f"data fetch failed: {exc}", "ticker": ticker})

    if df.empty:
        _journal("backtest_strategy", {"ticker": ticker, "error": "no data"}, "backtest,error")
        return _text_result({"error": "no historical data available", "ticker": ticker})

    df = df.tail(lookback_days)

    # Compute all needed indicators using the shared params dict.
    params = args.get("params") or {}
    for ind_name in needed_indicators:
        fn = _INDICATOR_REGISTRY[ind_name]
        df = fn(df, params)

    result = _run_strategy_backtest(
        df=df,
        entry_conditions=entry_conditions,
        exit_conditions=exit_conditions,
        stop_pct=stop_pct,
        target_pct=target_pct,
        max_hold_days=max_hold_days,
        initial_capital=initial_capital,
    )
    result["ticker"] = ticker
    result["lookback_days"] = lookback_days
    result["stop_pct"] = stop_pct
    result["target_pct"] = target_pct

    _journal("backtest_strategy", {
        "ticker": ticker,
        "n_trades": result.get("n_trades", 0),
        "win_rate": result.get("win_rate", 0),
        "total_return_pct": result.get("total_return_pct", 0),
        "sharpe": result.get("sharpe_ratio", 0),
    })
    return _text_result(result)


STRATEGY_BACKTEST_TOOLS = [backtest_strategy]
