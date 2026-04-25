"""MCP tools the agent uses to manage protective orders.

Six tools, one ``PROTECTIVE_TOOLS`` export. Every tool reads the
``ProtectiveStore`` instance the agent pool put on the context — there
is no per-tool state.

Distance fields in ``list_active_stops`` are signed:
  * negative -> trigger is below current price (typical stop_loss
    that's still in the money) — distance to the danger.
  * positive -> trigger is above current price (typical take_profit) —
    distance to the prize.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.protective_orders import ProtectiveStore, StopKind


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(kind: str, payload: Dict[str, Any], tags: Optional[List[str]] = None) -> None:
    ctx = get_agent_context()
    try:
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ctx.iteration_id, kind, payload.get("tool", ""),
                    json.dumps(payload, default=str), ",".join(tags or []),
                ),
            )
    except Exception:
        # Tests use a stub DB without the journal table — never crash a tool on logging.
        pass


def _store() -> ProtectiveStore:
    ctx = get_agent_context()
    if ctx.protective_store is None:
        raise RuntimeError(
            "protective_store missing from AgentContext — "
            "AgentPool didn't wire it before the iteration",
        )
    return ctx.protective_store


def _live_price(ticker: str, override: Optional[Dict[str, float]] = None) -> float:
    if override and ticker in override:
        return float(override[ticker])
    try:
        from data_loader import fetch_live_prices
        live = fetch_live_prices([ticker])
        return float((live.get(ticker) or {}).get("price", 0.0) or 0.0)
    except Exception:
        return 0.0


def _native_currency(ticker: str) -> str:
    try:
        from fx import ticker_currency
        return ticker_currency(ticker, default="USD")
    except Exception:
        return "USD"


# ── tools ──────────────────────────────────────────────────────────────

@tool(
    "set_stop_loss",
    "Place a stop-loss on a held ticker. Trigger price is in the same units "
    "as the live feed (USD for AAPL, pence for .L tickers). When the price "
    "hits or drops below trigger_price the broker fires a market SELL "
    "*immediately* — independent of the agent's wake cadence. Replaces any "
    "existing stop-loss on the same ticker.",
    {"ticker": str, "trigger_price": float, "quantity": float},
)
async def set_stop_loss(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    trigger_price = float(args.get("trigger_price", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    if not ticker or trigger_price <= 0 or quantity <= 0:
        return _text_result({
            "status": "rejected",
            "reason": "ticker, trigger_price>0, quantity>0 required",
        })
    o = _store().set_stop_loss(
        ticker=ticker, trigger_price=trigger_price, quantity=quantity,
        native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_stop_loss", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "set_take_profit",
    "Place a take-profit on a held ticker. When the price hits or exceeds "
    "trigger_price the broker fires a market SELL *immediately*. Replaces "
    "any existing take-profit on the same ticker.",
    {"ticker": str, "trigger_price": float, "quantity": float},
)
async def set_take_profit(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    trigger_price = float(args.get("trigger_price", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    if not ticker or trigger_price <= 0 or quantity <= 0:
        return _text_result({
            "status": "rejected",
            "reason": "ticker, trigger_price>0, quantity>0 required",
        })
    o = _store().set_take_profit(
        ticker=ticker, trigger_price=trigger_price, quantity=quantity,
        native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_take_profit", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "set_trailing_stop",
    "Place a trailing stop on a held ticker. distance_pct (e.g. 8 for 8%) is "
    "the gap between the running high and the trigger. As the price climbs, "
    "the trigger ratchets up; if the price drops by distance_pct from the "
    "running high the broker sells immediately. Anchors at the current live "
    "price unless an explicit anchor_price is supplied.",
    {"ticker": str, "distance_pct": float, "quantity": float, "anchor_price": float},
)
async def set_trailing_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    distance_pct = float(args.get("distance_pct", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    anchor_arg = args.get("anchor_price")
    if not ticker or distance_pct <= 0 or quantity <= 0:
        return _text_result({
            "status": "rejected",
            "reason": "ticker, distance_pct>0, quantity>0 required",
        })
    anchor = float(anchor_arg) if anchor_arg else _live_price(ticker)
    if anchor <= 0:
        return _text_result({
            "status": "rejected",
            "reason": "could not determine anchor price",
        })
    o = _store().set_trailing_stop(
        ticker=ticker, distance_pct=distance_pct, quantity=quantity,
        anchor_price=anchor, native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_trailing_stop", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "adjust_stop",
    "Move an existing stop's trigger price. order_type must be one of "
    "'stop_loss', 'take_profit', or 'trailing_stop'. For trailing stops, the "
    "new_price is interpreted as the new trigger and the implied anchor is "
    "back-solved from the original distance_pct.",
    {"ticker": str, "order_type": str, "new_price": float},
)
async def adjust_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    raw_kind = str(args.get("order_type", "")).strip().lower()
    new_price = float(args.get("new_price", 0.0) or 0.0)
    if not ticker or new_price <= 0:
        return _text_result({
            "status": "rejected",
            "reason": "ticker and new_price>0 required",
        })
    try:
        kind = StopKind(raw_kind)
    except ValueError:
        return _text_result({
            "status": "rejected",
            "reason": f"unknown order_type {raw_kind!r}",
        })
    n = _store().adjust(ticker, kind, new_price)
    _journal("tool_call",
             {"tool": "adjust_stop", "ticker": ticker,
              "order_type": kind.value, "new_price": new_price, "updated": n},
             tags=["protective"])
    return _text_result({"status": "ok" if n else "not_found", "updated": n})


@tool(
    "cancel_stop",
    "Remove an existing stop. order_type must be one of 'stop_loss', "
    "'take_profit', or 'trailing_stop'. Returns the number of orders removed.",
    {"ticker": str, "order_type": str},
)
async def cancel_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    raw_kind = str(args.get("order_type", "")).strip().lower()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker required"})
    try:
        kind = StopKind(raw_kind) if raw_kind else None
    except ValueError:
        return _text_result({
            "status": "rejected",
            "reason": f"unknown order_type {raw_kind!r}",
        })
    n = _store().cancel(ticker, kind)
    _journal("tool_call",
             {"tool": "cancel_stop", "ticker": ticker,
              "order_type": kind.value if kind else "all", "removed": n},
             tags=["protective"])
    return _text_result({"status": "ok" if n else "not_found", "removed": n})


@tool(
    "list_active_stops",
    "List every active protective order with its trigger price, current "
    "price, and percentage distance to the trigger (negative = below "
    "current price, positive = above). Use this before placing a new stop "
    "to see what's already in flight.",
    {},
)
async def list_active_stops(args: Dict[str, Any]) -> Dict[str, Any]:
    store = _store()
    orders = store.list_active()
    test_prices_arg = args.get("_test_prices") if isinstance(args, dict) else None
    test_prices = test_prices_arg if isinstance(test_prices_arg, dict) else None
    out: List[Dict[str, Any]] = []
    for o in orders:
        live = _live_price(o.ticker, override=test_prices)
        distance_pct_to_trigger = (
            (o.trigger_price - live) / live * 100.0 if live > 0 else None
        )
        out.append({
            **o.to_dict(),
            "current_price": live,
            "distance_pct_to_trigger": distance_pct_to_trigger,
        })
    _journal("tool_call",
             {"tool": "list_active_stops", "count": len(out)},
             tags=["protective"])
    return _text_result({"orders": out})


PROTECTIVE_TOOLS = [
    set_stop_loss,
    set_take_profit,
    set_trailing_stop,
    adjust_stop,
    cancel_stop,
    list_active_stops,
]
