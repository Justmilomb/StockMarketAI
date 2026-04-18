"""Broker tools for the AI agent.

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

from core.agent._sdk import tool

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

_CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$", "GBP": "£", "EUR": "€", "CHF": "CHF ",
    "JPY": "¥", "NOK": "kr ", "SEK": "kr ", "DKK": "kr ",
    "CAD": "C$", "AUD": "A$", "HKD": "HK$", "ILS": "₪",
}


def _currency_symbol(code: str) -> str:
    return _CURRENCY_SYMBOLS.get((code or "USD").upper(), "$")


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
    currency = str(account.get("currency", "USD") or "USD").upper()

    # Compute hold age per position so the prompt's min-hold floor
    # has real data to reason against. Only the paper broker exposes
    # position_entry_time today; live T212 will return None and the
    # model should treat the field as unknown.
    entry_lookup = getattr(getattr(svc, "broker", None), "position_entry_time", None)

    def _hold_minutes(ticker: str) -> Any:
        if not callable(entry_lookup):
            return None
        try:
            ts = entry_lookup(ticker)
        except Exception:
            return None
        if ts is None:
            return None
        from datetime import datetime, timezone
        age = datetime.now(tz=timezone.utc) - ts
        return round(age.total_seconds() / 60, 1)

    result = {
        "cash_free": float(account.get("free", 0.0)),
        "invested": float(account.get("invested", 0.0)),
        "equity": float(account.get("total", 0.0)),
        "unrealised_pnl": float(account.get("result", 0.0)),
        # Attribution: how much of the P&L came from price moves vs FX
        "unrealised_trading_pnl": float(account.get("unrealised_trading_pnl", 0.0) or 0.0),
        "unrealised_fx_pnl": float(account.get("unrealised_fx_pnl", 0.0) or 0.0),
        "realised_pnl": float(account.get("realised_pnl", 0.0) or 0.0),
        "realised_trading_pnl": float(account.get("realised_trading_pnl", 0.0) or 0.0),
        "realised_fx_pnl": float(account.get("realised_fx_pnl", 0.0) or 0.0),
        "currency": currency,
        "currency_symbol": _currency_symbol(currency),
        "positions": [
            {
                "ticker": str(p.get("ticker", "")),
                "quantity": float(p.get("quantity", 0.0) or 0.0),
                "avg_price": float(p.get("avg_price", 0.0) or 0.0),
                "current_price": float(p.get("current_price", 0.0) or 0.0),
                "native_currency": str(p.get("currency", "USD") or "USD").upper(),
                "fx_rate": float(p.get("fx_rate", 1.0) or 1.0),
                "cost_basis_acct": float(p.get("cost_basis_acct", 0.0) or 0.0),
                "market_value_acct": float(p.get("market_value", 0.0) or 0.0),
                "unrealised_pnl": float(p.get("unrealised_pnl", 0.0) or 0.0),
                "unrealised_trading_pnl": float(p.get("unrealised_trading_pnl", 0.0) or 0.0),
                "unrealised_fx_pnl": float(p.get("unrealised_fx_pnl", 0.0) or 0.0),
                "hold_minutes": _hold_minutes(str(p.get("ticker", ""))),
            }
            for p in positions
        ],
        "is_live": svc.is_live,
        "paper_mode_flag": ctx.paper_mode,
    }
    _journal("tool_call", {"tool": "get_portfolio", "result_summary": {
        "equity": result["equity"], "currency": currency,
        "positions": len(result["positions"])}})
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
    "refuses sells when quantity > held and buys when cost > free cash — "
    "these are the only gates. Supply a short `reason`; it is written to "
    "the agent journal.",
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
        # Price hint is in the ticker's native currency; free cash is
        # in the account's currency. Convert before comparing or a
        # £100 GBP account will silently reject a £70-equivalent
        # $100 TSLA trade because 100 > 100 by the naked number.
        account_ccy = str(account.get("currency", "USD") or "USD").upper()
        from fx import fx_rate, ticker_currency
        native_ccy = ticker_currency(ticker, default="USD")
        rate = fx_rate(native_ccy, account_ccy)
        est_cost_native = (px_hint or 0.0) * quantity
        est_cost_acct = est_cost_native * rate
        free_cash = float(account.get("free", 0.0))
        if px_hint is not None and est_cost_acct > free_cash + 1e-6:
            sym = _currency_symbol(account_ccy)
            msg = (
                f"refused: buy cost ~{sym}{est_cost_acct:.2f} "
                f"exceeds free cash {sym}{free_cash:.2f}"
            )
            _journal(
                "order_refused",
                {"tool": "place_order", "ticker": ticker, "side": side_raw,
                 "quantity": quantity, "est_cost_acct": est_cost_acct,
                 "free": free_cash, "reason": reason},
                tags=["safety", "cash"],
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

    # Auto-add the ticker to the active watchlist on a successful BUY.
    # A position that isn't tracked on the watchlist falls out of the
    # research swarm and the information panel — which is exactly what
    # broke for the user on the first live iteration (HOOD bought but
    # never watched). Never let a watchlist-add failure block the trade.
    watchlist_add: Dict[str, Any] | None = None
    if side_raw == "buy":
        try:
            from core.agent.tools.watchlist_tools import add_to_watchlist_sync
            watchlist_add = add_to_watchlist_sync(
                ticker,
                reason=f"auto-added after BUY: {reason}" if reason else "auto-added after BUY",
                tool_tag="place_order",
            )
        except Exception as e:
            watchlist_add = {"status": "error", "reason": str(e)}

    result: Dict[str, Any] = {
        "status": "submitted",
        "broker_response": resp,
        "reason": reason,
    }
    if watchlist_add is not None:
        result["watchlist_add"] = watchlist_add
    return _text_result(result)


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
