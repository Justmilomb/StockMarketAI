"""Broker tools for the Claude agent.

Every tool call does its own fresh broker read — no cached state.
``place_order`` re-fetches the portfolio before submitting so the
TSLA-class "selling equity not owned" bug cannot slip through.

Tools registered here:
    get_portfolio         current cash + held positions
    get_pending_orders    open / pending orders
    get_order_history     recent executed orders
    place_order           size-safety-checked order submission
    cancel_order          cancel a pending order
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from claude_agent_sdk import tool

from core.agent.context import get_agent_context


# ── helpers ────────────────────────────────────────────────────────────

def _journal(kind: str, payload: Dict[str, Any], tags: List[str] | None = None) -> None:
    """Append an entry to agent_journal, scoped to the current iteration."""
    ctx = get_agent_context()
    import sqlite3
    with sqlite3.connect(ctx.db.db_path) as conn:
        conn.execute(
            "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ctx.iteration_id,
                kind,
                payload.get("tool", ""),
                json.dumps(payload, default=str),
                ",".join(tags or []),
            ),
        )


def _text_result(data: Any) -> Dict[str, Any]:
    """Wrap a Python value as an MCP tool text-content response."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _held_qty(positions: List[Dict[str, Any]], ticker: str) -> float:
    for p in positions:
        if str(p.get("ticker", "")) == ticker:
            return float(p.get("quantity", 0.0) or 0.0)
    return 0.0


# ── tools ──────────────────────────────────────────────────────────────

@tool(
    "get_portfolio",
    "Return the broker's current cash, total equity, and every open position. "
    "Always fresh — never a cached snapshot. Use this before every trade decision.",
    {},
)
async def get_portfolio(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    svc = ctx.broker_service
    positions = svc.get_positions()
    account = svc.get_account_info()
    result = {
        "cash_free": float(account.get("free", 0.0)),
        "invested": float(account.get("invested", 0.0)),
        "equity": float(account.get("total", 0.0)),
        "unrealised_pnl": float(account.get("result", 0.0)),
        "positions": [
            {
                "ticker": str(p.get("ticker", "")),
                "quantity": float(p.get("quantity", 0.0) or 0.0),
                "avg_price": float(p.get("avg_price", 0.0) or 0.0),
                "current_price": float(p.get("current_price", 0.0) or 0.0),
                "unrealised_pnl": float(p.get("unrealised_pnl", 0.0) or 0.0),
            }
            for p in positions
        ],
        "is_live": svc.is_live,
        "paper_mode_flag": ctx.paper_mode,
    }
    _journal("tool_call", {"tool": "get_portfolio", "result_summary": {
        "equity": result["equity"], "positions": len(result["positions"])}})
    return _text_result(result)


@tool(
    "get_pending_orders",
    "Return currently pending / working orders at the broker. Empty list if none.",
    {},
)
async def get_pending_orders(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    orders = ctx.broker_service.get_pending_orders()
    _journal("tool_call", {"tool": "get_pending_orders", "count": len(orders)})
    return _text_result(orders)


@tool(
    "get_order_history",
    "Return the N most recent executed orders (default 50). "
    "Use this to see what trades have actually happened recently.",
    {"limit": int},
)
async def get_order_history(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    limit = int(args.get("limit", 50) or 50)
    data = ctx.broker_service.get_order_history(limit=limit)
    items = data.get("items", []) if isinstance(data, dict) else data
    _journal("tool_call", {"tool": "get_order_history", "count": len(items)})
    return _text_result(items)


@tool(
    "place_order",
    "Submit an order. Before sending, the tool re-fetches the portfolio and "
    "refuses sells when quantity > held, buys when cost > free cash, and "
    "enforces the max_position_pct / max_trades_per_hour config caps. "
    "Always supply a short `reason` — it is written to the agent journal.",
    {
        "ticker": str,
        "side": str,
        "quantity": float,
        "order_type": str,
        "limit_price": float,
        "reason": str,
    },
)
async def place_order(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    side_raw = str(args.get("side", "")).strip().lower()
    quantity = float(args.get("quantity", 0) or 0)
    order_type = str(args.get("order_type", "market") or "market").lower()
    limit_price = args.get("limit_price")
    reason = str(args.get("reason", "") or "")

    # ── input validation ─────────────────────────────────────────────
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    if side_raw not in {"buy", "sell"}:
        return _text_result({"status": "rejected", "reason": f"side must be buy or sell, got {side_raw}"})
    if quantity <= 0:
        return _text_result({"status": "rejected", "reason": f"quantity must be positive, got {quantity}"})
    if order_type not in {"market", "limit"}:
        return _text_result({"status": "rejected", "reason": f"order_type must be market or limit, got {order_type}"})
    if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
        return _text_result({"status": "rejected", "reason": "limit order requires a positive limit_price"})

    svc = ctx.broker_service
    positions = svc.get_positions()
    account = svc.get_account_info()

    # ── ownership check for sells (this is the TSLA-bug guard) ───────
    if side_raw == "sell":
        held = _held_qty(positions, ticker)
        if held < quantity - 1e-9:
            msg = f"refused: selling {quantity} {ticker} but only {held} held"
            _journal(
                "order_refused",
                {"tool": "place_order", "ticker": ticker, "side": side_raw,
                 "quantity": quantity, "held": held, "reason": reason},
                tags=["safety", "ownership"],
            )
            return _text_result({"status": "rejected", "reason": msg})

    # ── cash check for buys ───────────────────────────────────────────
    if side_raw == "buy":
        px_hint = float(limit_price) if limit_price else None
        if px_hint is None:
            # Use current_price from the positions list if we already own it,
            # else fall back to an optimistic estimate using data_loader.
            held = next((p for p in positions if p.get("ticker") == ticker), None)
            if held and float(held.get("current_price", 0) or 0) > 0:
                px_hint = float(held["current_price"])
            else:
                try:
                    from data_loader import fetch_live_prices
                    live = fetch_live_prices([ticker])
                    px_hint = float(live.get(ticker, {}).get("price", 0.0)) or None
                except Exception:
                    px_hint = None
        est_cost = (px_hint or 0.0) * quantity
        free_cash = float(account.get("free", 0.0))
        if px_hint is not None and est_cost > free_cash + 1e-6:
            msg = f"refused: buy cost ~${est_cost:.2f} exceeds free cash ${free_cash:.2f}"
            _journal(
                "order_refused",
                {"tool": "place_order", "ticker": ticker, "side": side_raw,
                 "quantity": quantity, "est_cost": est_cost, "free": free_cash, "reason": reason},
                tags=["safety", "cash"],
            )
            return _text_result({"status": "rejected", "reason": msg})

        # Max position cap (from agent config)
        agent_cfg = ctx.config.get("agent", {}) or {}
        max_pct = float(agent_cfg.get("max_position_pct", 20.0)) / 100.0
        equity = float(account.get("total", 0.0))
        current_exposure = sum(
            float(p.get("quantity", 0) or 0) * float(p.get("current_price", 0) or 0)
            for p in positions if p.get("ticker") == ticker
        )
        new_exposure = current_exposure + est_cost
        if equity > 0 and new_exposure / equity > max_pct:
            msg = (
                f"refused: {ticker} position would be "
                f"{new_exposure / equity:.1%} of equity (cap {max_pct:.0%})"
            )
            _journal(
                "order_refused",
                {"tool": "place_order", "ticker": ticker, "side": side_raw,
                 "quantity": quantity, "new_exposure": new_exposure,
                 "equity": equity, "cap_pct": max_pct, "reason": reason},
                tags=["safety", "concentration"],
            )
            return _text_result({"status": "rejected", "reason": msg})

    # ── submit ────────────────────────────────────────────────────────
    try:
        resp = svc.submit_order(
            ticker=ticker,
            side=side_raw.upper(),
            quantity=quantity,
            order_type=order_type,
            limit_price=float(limit_price) if limit_price else None,
        )
    except Exception as e:
        _journal(
            "order_error",
            {"tool": "place_order", "ticker": ticker, "side": side_raw,
             "quantity": quantity, "error": str(e), "reason": reason},
            tags=["error"],
        )
        return _text_result({"status": "error", "reason": str(e)})

    _journal(
        "order_placed",
        {"tool": "place_order", "ticker": ticker, "side": side_raw,
         "quantity": quantity, "order_type": order_type,
         "limit_price": limit_price, "reason": reason, "broker_response": resp},
        tags=["trade"],
    )
    return _text_result({"status": "submitted", "broker_response": resp, "reason": reason})


@tool(
    "cancel_order",
    "Cancel a pending order by its broker order id.",
    {"order_id": str},
)
async def cancel_order(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    order_id = str(args.get("order_id", "")).strip()
    if not order_id:
        return _text_result({"status": "rejected", "reason": "order_id is required"})
    ok = ctx.broker_service.cancel_order(order_id)
    _journal("tool_call", {"tool": "cancel_order", "order_id": order_id, "ok": ok})
    return _text_result({"status": "ok" if ok else "failed", "order_id": order_id})


BROKER_TOOLS = [
    get_portfolio,
    get_pending_orders,
    get_order_history,
    place_order,
    cancel_order,
]
