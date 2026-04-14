"""Lean historical backtest tools.

This module intentionally does **not** revive the old
``backtesting/engine.py`` walk-forward pipeline — that engine had
runtime-only imports of ML modules that Phase 3 deleted
(``features_advanced``, ``ensemble``, ``strategy_selector``,
``strategy_profiles``). Dragging it back would mean undeleting half
the pipeline.

Instead, :func:`simulate_stop_target` is a small stop-target rule
simulator. It slides a long-only window over historical daily OHLCV
and, for each bar, simulates a "buy at the close" entry with a fixed
percentage stop and a fixed percentage target. Results come back as
win rate, average return, expectancy, and number of trades.

The tool is purely a sanity check — a way to ask "if I'd taken every
setup with a 2% stop and 4% target over the last year, would it have
paid me?" It is not an equity curve, not a position sizer, not a
replacement for actually reading the chart.

Stop vs. target resolution on the same bar is pessimistic: if a bar's
low hits the stop *and* its high hits the target, we assume the stop
fired first. This matches every respectable backtester and avoids
overstating wins.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
from claude_agent_sdk import tool

from core.agent.context import get_agent_context


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
    """Pull daily OHLCV via ``core.data_loader`` — flat import because
    the agent context puts ``core/`` on ``sys.path``."""
    from data_loader import fetch_ticker_data  # type: ignore

    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days + 10)  # small pad for weekends
    df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def _simulate(
    df: pd.DataFrame,
    stop_pct: float,
    target_pct: float,
    hold_days: int,
) -> Dict[str, Any]:
    """Run the stop-target loop over a DataFrame and return summary stats."""
    if df.empty:
        return {
            "n_trades": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "expectancy_pct": 0.0,
            "best_trade_pct": 0.0,
            "worst_trade_pct": 0.0,
        }

    closes = df["Close"].to_numpy(dtype=float)
    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    n_bars = len(closes)

    stop_frac = stop_pct / 100.0
    target_frac = target_pct / 100.0

    returns: List[float] = []
    wins = 0
    losses = 0
    flats = 0

    # Need at least one forward bar to evaluate.
    last_entry = n_bars - hold_days - 1
    for i in range(last_entry + 1):
        entry = closes[i]
        if entry <= 0:
            continue
        stop_price = entry * (1.0 - stop_frac)
        target_price = entry * (1.0 + target_frac)

        outcome_pct: float | None = None
        # Walk forward up to hold_days bars.
        for j in range(i + 1, min(i + 1 + hold_days, n_bars)):
            hi = highs[j]
            lo = lows[j]
            # Pessimistic: if both touched, stop first.
            if lo <= stop_price:
                outcome_pct = -stop_pct
                break
            if hi >= target_price:
                outcome_pct = target_pct
                break

        if outcome_pct is None:
            # Exit at the close on the last held bar.
            exit_idx = min(i + hold_days, n_bars - 1)
            exit_price = closes[exit_idx]
            outcome_pct = (exit_price / entry - 1.0) * 100.0
            flats += 1
        elif outcome_pct > 0:
            wins += 1
        else:
            losses += 1

        returns.append(outcome_pct)

    n_trades = len(returns)
    if n_trades == 0:
        return {
            "n_trades": 0, "wins": 0, "losses": 0, "flats": 0,
            "win_rate": 0.0, "avg_return_pct": 0.0, "expectancy_pct": 0.0,
            "best_trade_pct": 0.0, "worst_trade_pct": 0.0,
        }

    avg_return = sum(returns) / n_trades
    win_rate = (wins / n_trades) * 100.0
    return {
        "n_trades": n_trades,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(win_rate, 2),
        "avg_return_pct": round(avg_return, 3),
        "expectancy_pct": round(avg_return, 3),
        "best_trade_pct": round(max(returns), 3),
        "worst_trade_pct": round(min(returns), 3),
    }


@tool(
    "simulate_stop_target",
    (
        "Slide a long-only stop/target rule over a ticker's daily OHLCV "
        "history and report win rate, expectancy, and trade count. Entry "
        "is simulated at each day's close; exit is the first of stop, "
        "target, or `hold_days` bars (close at that point). Pessimistic "
        "on same-bar stop/target collisions. `stop_pct` and `target_pct` "
        "are positive percentages (e.g. 2 means 2%). `hold_days` clamps "
        "to [1, 30]; `lookback_days` clamps to [30, 730]. Use this for "
        "quick sanity checks on a trading idea — not a full backtest."
    ),
    {
        "ticker": str,
        "stop_pct": float,
        "target_pct": float,
        "hold_days": int,
        "lookback_days": int,
    },
)
async def simulate_stop_target(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    stop_pct = _clip_float(args.get("stop_pct"), 0.1, 50.0, 2.0)
    target_pct = _clip_float(args.get("target_pct"), 0.1, 200.0, 4.0)
    hold_days = _clip_int(args.get("hold_days"), 1, 30, 5)
    lookback_days = _clip_int(args.get("lookback_days"), 30, 730, 365)

    try:
        df = _fetch_daily(ticker, lookback_days)
    except Exception as exc:
        _journal("simulate_stop_target", {"ticker": ticker, "error": str(exc)}, "backtest,error")
        return _text_result({
            "error": f"data fetch failed: {exc}",
            "ticker": ticker,
        })

    if df.empty:
        _journal("simulate_stop_target", {"ticker": ticker, "error": "no data"}, "backtest,error")
        return _text_result({
            "error": "no historical data available",
            "ticker": ticker,
        })

    # Truncate to the requested lookback (data_loader pads a little).
    df = df.tail(lookback_days + hold_days)

    stats = _simulate(df, stop_pct=stop_pct, target_pct=target_pct, hold_days=hold_days)

    result: Dict[str, Any] = {
        "ticker": ticker,
        "stop_pct": stop_pct,
        "target_pct": target_pct,
        "hold_days": hold_days,
        "lookback_days": lookback_days,
        "bars_used": int(len(df)),
        "first_bar": df.index[0].isoformat() if len(df) else None,
        "last_bar": df.index[-1].isoformat() if len(df) else None,
        **stats,
    }
    _journal("simulate_stop_target", {
        "ticker": ticker,
        "n_trades": stats["n_trades"],
        "win_rate": stats["win_rate"],
        "expectancy_pct": stats["expectancy_pct"],
    })
    return _text_result(result)


BACKTEST_TOOLS = [simulate_stop_target]
