"""Trading performance review tools.

Closes the learning loop: lets the agent compute aggregate statistics
on its own trading record (win rate, Sharpe, per-ticker breakdown) and
review individual round-trip trades. In paper mode, reads from the
``logs/paper_orders.jsonl`` audit trail; in live mode, reads from the
broker's order history API.

Round-trip pairing: a BUY followed by a SELL of the same ticker forms
one round trip. Partial sells split the position proportionally.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from core.agent._sdk import tool

from core.agent.context import get_agent_context


# ── shared helpers ───────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(tool_name: str, payload: Dict[str, Any], tags: str = "performance") -> None:
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


# ── audit trail parsing ─────────────────────────────────────────────

def _read_paper_audit(since_days: int, ticker_filter: str) -> List[Dict[str, Any]]:
    """Read FILLED records from ``logs/paper_orders.jsonl``."""
    audit_path = Path("logs") / "paper_orders.jsonl"
    if not audit_path.exists():
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=since_days)
    records: List[Dict[str, Any]] = []

    try:
        with audit_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("status") != "FILLED":
                    continue
                ts = rec.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except Exception:
                    continue
                if ticker_filter and rec.get("ticker", "").upper() != ticker_filter:
                    continue
                records.append(rec)
    except Exception:
        return []

    return records


def _pair_round_trips(fills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pair BUY/SELL fills into round-trip trades.

    Uses FIFO matching: earliest buy is closed by the next sell of the
    same ticker. Partial sells split proportionally.
    """
    # Group buys by ticker (FIFO queue).
    open_buys: Dict[str, List[Dict[str, Any]]] = {}
    trades: List[Dict[str, Any]] = []

    for fill in fills:
        ticker = fill.get("ticker", "")
        side = str(fill.get("side", "")).upper()
        qty = float(fill.get("quantity", 0))
        price = float(fill.get("fill_price", 0))
        ts = fill.get("timestamp", "")

        if side == "BUY":
            open_buys.setdefault(ticker, []).append({
                "price": price,
                "qty": qty,
                "timestamp": ts,
            })
        elif side == "SELL" and ticker in open_buys and open_buys[ticker]:
            sell_remaining = qty
            while sell_remaining > 0 and open_buys[ticker]:
                buy = open_buys[ticker][0]
                match_qty = min(sell_remaining, buy["qty"])
                entry_price = buy["price"]
                exit_price = price
                ret_pct = (exit_price / entry_price - 1.0) * 100.0 if entry_price > 0 else 0.0

                # Parse dates for hold time.
                hold_days = 0
                try:
                    entry_dt = datetime.fromisoformat(buy["timestamp"].replace("Z", "+00:00"))
                    exit_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    hold_days = max(1, (exit_dt - entry_dt).days)
                except Exception:
                    pass

                trades.append({
                    "ticker": ticker,
                    "entry_date": buy["timestamp"][:10],
                    "exit_date": ts[:10],
                    "entry_price": round(entry_price, 4),
                    "exit_price": round(exit_price, 4),
                    "quantity": round(match_qty, 4),
                    "return_pct": round(ret_pct, 3),
                    "pnl": round(match_qty * (exit_price - entry_price), 4),
                    "hold_days": hold_days,
                })

                buy["qty"] -= match_qty
                sell_remaining -= match_qty
                if buy["qty"] <= 1e-9:
                    open_buys[ticker].pop(0)

    return trades


def _compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute aggregate performance stats from round-trip trades."""
    if not trades:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "note": "no completed round-trip trades found",
        }

    n = len(trades)
    returns = [t["return_pct"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))

    win_rate = len(wins) / n * 100.0
    avg_return = sum(returns) / n
    avg_hold = sum(t["hold_days"] for t in trades) / n
    total_pnl = sum(pnls)

    # Sharpe ratio.
    if n > 1:
        ret_std = float(np.std(returns, ddof=1))
        if ret_std > 0:
            trades_per_year = 252.0 / max(avg_hold, 1)
            sharpe = (avg_return / ret_std) * math.sqrt(trades_per_year)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Per-ticker breakdown.
    ticker_stats: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        tk = t["ticker"]
        if tk not in ticker_stats:
            ticker_stats[tk] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
        ticker_stats[tk]["trades"] += 1
        if t["return_pct"] > 0:
            ticker_stats[tk]["wins"] += 1
        ticker_stats[tk]["total_pnl"] += t["pnl"]
    for tk, s in ticker_stats.items():
        s["win_rate"] = round(s["wins"] / s["trades"] * 100.0, 1)
        s["total_pnl"] = round(s["total_pnl"], 2)

    return {
        "n_trades": n,
        "win_rate": round(win_rate, 1),
        "avg_return_pct": round(avg_return, 3),
        "total_pnl": round(total_pnl, 2),
        "sharpe_ratio": round(sharpe, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "avg_hold_days": round(avg_hold, 1),
        "best_trade_pct": round(max(returns), 3),
        "worst_trade_pct": round(min(returns), 3),
        "per_ticker": ticker_stats,
    }


# ── tools ────────────────────────────────────────────────────────────

@tool(
    "review_performance",
    (
        "Compute aggregate performance statistics from your trading "
        "history. Returns win_rate, total_pnl, sharpe_ratio, "
        "profit_factor, avg_hold_time, best/worst trade, and a per-ticker "
        "breakdown. Use this to evaluate which of your strategies are "
        "working and which are not. Pass `since_days` to limit the window "
        "(default 30, max 365). Pass `ticker` to filter to one name."
    ),
    {
        "since_days": int,
        "ticker": str,
    },
)
async def review_performance(args: Dict[str, Any]) -> Dict[str, Any]:
    since_days = _clip_int(args.get("since_days"), 1, 365, 30)
    ticker = str(args.get("ticker", "") or "").strip().upper()

    fills = _read_paper_audit(since_days, ticker)
    if not fills:
        _journal("review_performance", {"since_days": since_days, "ticker": ticker, "result": "no fills"})
        return _text_result({
            "n_trades": 0,
            "note": "no filled orders found in the audit trail for this period",
            "since_days": since_days,
            "ticker_filter": ticker or "all",
        })

    trades = _pair_round_trips(fills)
    stats = _compute_stats(trades)
    stats["since_days"] = since_days
    stats["ticker_filter"] = ticker or "all"
    stats["total_fills_read"] = len(fills)

    _journal("review_performance", {
        "since_days": since_days,
        "ticker": ticker,
        "n_trades": stats.get("n_trades", 0),
        "win_rate": stats.get("win_rate", 0),
        "total_pnl": stats.get("total_pnl", 0),
    })
    return _text_result(stats)


@tool(
    "get_trade_log",
    (
        "Return your recent completed round-trip trades (buy then sell of "
        "the same ticker) with entry/exit prices, return, hold time, and "
        "PnL. Use this to review specific decisions and learn from them. "
        "Pass `limit` to control how many trades to return (default 20, "
        "max 50). Pass `ticker` to filter to one name."
    ),
    {
        "limit": int,
        "ticker": str,
    },
)
async def get_trade_log(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = _clip_int(args.get("limit"), 1, 50, 20)
    ticker = str(args.get("ticker", "") or "").strip().upper()

    # Read a generous window — trade log is about reviewing past trades.
    fills = _read_paper_audit(since_days=365, ticker_filter=ticker)
    if not fills:
        return _text_result({
            "trades": [],
            "note": "no filled orders found in the audit trail",
        })

    trades = _pair_round_trips(fills)
    # Most recent trades first.
    trades = list(reversed(trades))[:limit]

    _journal("get_trade_log", {
        "limit": limit,
        "ticker": ticker,
        "returned": len(trades),
    })
    return _text_result({
        "trades": trades,
        "count": len(trades),
        "ticker_filter": ticker or "all",
    })


PERFORMANCE_TOOLS = [review_performance, get_trade_log]
