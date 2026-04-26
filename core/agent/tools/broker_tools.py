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
    "these are the only gates. ``order_type`` accepts ``market``, ``limit``, "
    "or ``stop``. A stop SELL fires as a market order once price crosses "
    "``stop_price`` downward (stop-loss); a stop BUY fires when price "
    "crosses upward (breakout entry). Paper broker monitors live prices "
    "every second so stops execute without waiting on the agent. Supply "
    "a short ``reason``; it is written to the agent journal.",
    {
        "ticker": str,
        "side": str,
        "quantity": float,
        "order_type": str,
        "limit_price": float,
        "stop_price": float,
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
    stop_price = args.get("stop_price")
    reason = str(args.get("reason", "") or "")

    # ── input validation ─────────────────────────────────────────────
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    if side_raw not in {"buy", "sell"}:
        return _text_result({"status": "rejected", "reason": f"side must be buy or sell, got {side_raw}"})
    if quantity <= 0:
        return _text_result({"status": "rejected", "reason": f"quantity must be positive, got {quantity}"})
    if order_type not in {"market", "limit", "stop"}:
        return _text_result({"status": "rejected", "reason": f"order_type must be market, limit, or stop, got {order_type}"})
    if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
        return _text_result({"status": "rejected", "reason": "limit order requires a positive limit_price"})
    if order_type == "stop" and (stop_price is None or float(stop_price) <= 0):
        return _text_result({"status": "rejected", "reason": "stop order requires a positive stop_price"})

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

    # ── smart-limit interception (market orders only) ────────────────
    smart_summary: Dict[str, Any] | None = None
    if order_type == "market":
        try:
            from core.agent.tools._smart_execution import (
                attempt_smart_market,
            )
            smart_summary = await attempt_smart_market(
                svc=svc,
                ticker=ticker,
                side=side_raw,
                quantity=quantity,
                config=ctx.config,
            )
        except Exception:
            smart_summary = None

    # ── submit ────────────────────────────────────────────────────────
    if smart_summary and smart_summary.get("filled") is True:
        # Smart helper already filled via limit order — reuse its response.
        resp = smart_summary.get("broker_response", {})
    else:
        try:
            resp = svc.submit_order(
                ticker=ticker,
                side=side_raw.upper(),
                quantity=quantity,
                order_type=order_type,
                limit_price=float(limit_price) if limit_price else None,
                stop_price=float(stop_price) if stop_price else None,
            )
        except Exception as e:
            _journal(
                "order_error",
                {"tool": "place_order", "ticker": ticker, "side": side_raw,
                 "quantity": quantity, "error": str(e), "reason": reason},
                tags=["error"],
            )
            return _text_result({"status": "error", "reason": str(e)})

    journal_tags = ["trade"]
    if smart_summary is not None:
        journal_tags.append("smart_exec")
        if smart_summary.get("filled") is True:
            journal_tags.append("limit_first")
        elif smart_summary.get("path") == "market_fallback":
            journal_tags.append("market_fallback")
    _journal(
        "order_placed",
        {"tool": "place_order", "ticker": ticker, "side": side_raw,
         "quantity": quantity, "order_type": order_type,
         "limit_price": limit_price, "reason": reason, "broker_response": resp,
         "smart_summary": smart_summary},
        tags=journal_tags,
    )

    # Auto-add the ticker to the active watchlist on any successful order.
    # A traded ticker that isn't on the watchlist falls out of the research
    # swarm and the information panel — a sell still wants ongoing coverage
    # (the model may want to re-enter, or track the thesis post-exit).
    # add_to_watchlist_sync is a noop if the ticker is already tracked.
    # Never let a watchlist-add failure block the trade.
    watchlist_add: Dict[str, Any] | None = None
    try:
        from core.agent.tools.watchlist_tools import add_to_watchlist_sync
        side_label = side_raw.upper()
        watchlist_add = add_to_watchlist_sync(
            ticker,
            reason=f"auto-added after {side_label}: {reason}" if reason else f"auto-added after {side_label}",
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
    if smart_summary is not None:
        result["smart_execution"] = smart_summary
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


@tool(
    "modify_order",
    "Adjust an open pending order's limit_price and/or stop_price without "
    "cancelling and re-submitting. Use this to tighten a trailing stop or "
    "move a take-profit target. Paper mode supports live-stop adjustment; "
    "live brokers may reject if the order is already in-flight.",
    {
        "order_id": str,
        "limit_price": float,
        "stop_price": float,
    },
)
async def modify_order(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    order_id = str(args.get("order_id", "")).strip()
    if not order_id:
        return _text_result({"status": "rejected", "reason": "order_id is required"})
    limit_price = args.get("limit_price")
    stop_price = args.get("stop_price")
    if limit_price is None and stop_price is None:
        return _text_result({
            "status": "rejected",
            "reason": "supply at least one of limit_price or stop_price",
        })
    try:
        result = ctx.broker_service.modify_order(
            order_id=order_id,
            limit_price=float(limit_price) if limit_price is not None else None,
            stop_price=float(stop_price) if stop_price is not None else None,
        )
    except Exception as e:
        _journal(
            "order_error",
            {"tool": "modify_order", "order_id": order_id, "error": str(e)},
            tags=["error"],
        )
        return _text_result({"status": "error", "reason": str(e)})
    _journal(
        "order_modified",
        {"tool": "modify_order", "order_id": order_id,
         "limit_price": limit_price, "stop_price": stop_price, "result": result},
        tags=["order"],
    )
    return _text_result(result)


def _pending_stops_for(ticker: str) -> List[Dict[str, Any]]:
    """Return every pending order on ``ticker`` that's a stop or a limit SELL.

    A limit SELL is treated as a take-profit here because that's the
    role it plays from a risk-management angle — the agent uses
    ``set_take_profit`` to create them and expects the same tools to
    find them again for adjustment.
    """
    ctx = get_agent_context()
    orders = ctx.broker_service.get_pending_orders() or []
    matches: List[Dict[str, Any]] = []
    for o in orders:
        if str(o.get("ticker", "")) != ticker:
            continue
        otype = str(o.get("order_type", "")).lower()
        side = str(o.get("side", "")).upper()
        if otype == "stop":
            matches.append(o)
        elif otype == "limit" and side == "SELL":
            matches.append(o)
    return matches


@tool(
    "set_stop_loss",
    "Protective stop-loss on a held position. Queues a stop SELL that "
    "the broker's 1-second price monitor will fire automatically when "
    "price crosses ``stop_price`` downward — no agent iteration needed. "
    "If ``quantity`` is omitted, defaults to the full current holding. "
    "Use ``adjust_stop`` to ratchet the level up as price moves in your "
    "favour; use ``cancel_stop`` to remove. A short ``reason`` is written "
    "to the agent journal.",
    {
        "ticker": str,
        "stop_price": float,
        "quantity": float,
        "reason": str,
    },
)
async def set_stop_loss(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    stop_price = args.get("stop_price")
    quantity_arg = args.get("quantity")
    reason = str(args.get("reason", "") or "")

    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    if stop_price is None or float(stop_price) <= 0:
        return _text_result({"status": "rejected", "reason": "stop_price must be positive"})

    positions = ctx.broker_service.get_positions()
    held = _held_qty(positions, ticker)
    if held <= 0:
        return _text_result({
            "status": "rejected",
            "reason": f"cannot set stop on {ticker}: no open position",
        })
    quantity = float(quantity_arg) if quantity_arg else held
    if quantity <= 0:
        return _text_result({"status": "rejected", "reason": f"quantity must be positive, got {quantity}"})
    if quantity > held + 1e-9:
        return _text_result({
            "status": "rejected",
            "reason": f"quantity {quantity} exceeds held {held} for {ticker}",
        })

    try:
        resp = ctx.broker_service.submit_order(
            ticker=ticker,
            side="SELL",
            quantity=quantity,
            order_type="stop",
            stop_price=float(stop_price),
        )
    except Exception as e:
        _journal(
            "order_error",
            {"tool": "set_stop_loss", "ticker": ticker, "stop_price": stop_price,
             "quantity": quantity, "error": str(e), "reason": reason},
            tags=["error"],
        )
        return _text_result({"status": "error", "reason": str(e)})
    _journal(
        "stop_loss_set",
        {"tool": "set_stop_loss", "ticker": ticker, "stop_price": stop_price,
         "quantity": quantity, "reason": reason, "broker_response": resp},
        tags=["risk", "stop"],
    )
    return _text_result({"status": "queued", "broker_response": resp, "reason": reason})


@tool(
    "set_take_profit",
    "Take-profit on a held position. Queues a limit SELL that fires "
    "when price rises to ``limit_price`` — monitored every second. "
    "Defaults to the full holding when ``quantity`` is omitted. Use "
    "``adjust_stop`` with ``limit_price`` to move the target, or "
    "``cancel_stop`` to remove it. A short ``reason`` is journalled.",
    {
        "ticker": str,
        "limit_price": float,
        "quantity": float,
        "reason": str,
    },
)
async def set_take_profit(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    limit_price = args.get("limit_price")
    quantity_arg = args.get("quantity")
    reason = str(args.get("reason", "") or "")

    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    if limit_price is None or float(limit_price) <= 0:
        return _text_result({"status": "rejected", "reason": "limit_price must be positive"})

    positions = ctx.broker_service.get_positions()
    held = _held_qty(positions, ticker)
    if held <= 0:
        return _text_result({
            "status": "rejected",
            "reason": f"cannot set take-profit on {ticker}: no open position",
        })
    quantity = float(quantity_arg) if quantity_arg else held
    if quantity <= 0:
        return _text_result({"status": "rejected", "reason": f"quantity must be positive, got {quantity}"})
    if quantity > held + 1e-9:
        return _text_result({
            "status": "rejected",
            "reason": f"quantity {quantity} exceeds held {held} for {ticker}",
        })

    try:
        resp = ctx.broker_service.submit_order(
            ticker=ticker,
            side="SELL",
            quantity=quantity,
            order_type="limit",
            limit_price=float(limit_price),
        )
    except Exception as e:
        _journal(
            "order_error",
            {"tool": "set_take_profit", "ticker": ticker, "limit_price": limit_price,
             "quantity": quantity, "error": str(e), "reason": reason},
            tags=["error"],
        )
        return _text_result({"status": "error", "reason": str(e)})
    _journal(
        "take_profit_set",
        {"tool": "set_take_profit", "ticker": ticker, "limit_price": limit_price,
         "quantity": quantity, "reason": reason, "broker_response": resp},
        tags=["risk", "take_profit"],
    )
    return _text_result({"status": "queued", "broker_response": resp, "reason": reason})


@tool(
    "adjust_stop",
    "Move an existing stop-loss or take-profit level on a ticker. "
    "Supply ``stop_price`` to ratchet a stop, or ``limit_price`` to "
    "shift a take-profit. If the ticker has multiple protective orders, "
    "the tool modifies ALL matching ones (most common case: one stop + "
    "one take-profit, both get the same adjustment to their own field).",
    {
        "ticker": str,
        "stop_price": float,
        "limit_price": float,
        "reason": str,
    },
)
async def adjust_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    stop_price = args.get("stop_price")
    limit_price = args.get("limit_price")
    reason = str(args.get("reason", "") or "")

    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    if stop_price is None and limit_price is None:
        return _text_result({
            "status": "rejected",
            "reason": "supply at least one of stop_price or limit_price",
        })
    matches = _pending_stops_for(ticker)
    if not matches:
        return _text_result({
            "status": "rejected",
            "reason": f"no pending stop or take-profit on {ticker}",
        })

    results: List[Dict[str, Any]] = []
    for o in matches:
        order_id = str(o.get("id") or o.get("order_id") or "")
        if not order_id:
            continue
        otype = str(o.get("order_type", "")).lower()
        # Only apply the field relevant to this order type so an
        # adjust_stop(ticker=X, stop_price=S) doesn't accidentally
        # overwrite the take-profit's limit_price (and vice versa).
        kwargs: Dict[str, Any] = {}
        if otype == "stop" and stop_price is not None:
            kwargs["stop_price"] = float(stop_price)
        if otype == "limit" and limit_price is not None:
            kwargs["limit_price"] = float(limit_price)
        if not kwargs:
            continue
        try:
            res = ctx.broker_service.modify_order(order_id=order_id, **kwargs)
        except Exception as e:
            res = {"status": "error", "order_id": order_id, "reason": str(e)}
        results.append(res)

    _journal(
        "stop_adjusted",
        {"tool": "adjust_stop", "ticker": ticker, "stop_price": stop_price,
         "limit_price": limit_price, "reason": reason, "results": results},
        tags=["risk", "stop"],
    )
    status_str = "ok" if results and all(r.get("status") == "OK" for r in results) else "partial"
    return _text_result({"status": status_str, "results": results, "reason": reason})


@tool(
    "cancel_stop",
    "Cancel every pending stop-loss and take-profit on a ticker. Use "
    "when the thesis changes (e.g. earnings news moved the picture) "
    "and the current levels no longer apply. The agent should typically "
    "follow up with ``set_stop_loss`` / ``set_take_profit`` at the new "
    "levels rather than leaving the position unhedged.",
    {
        "ticker": str,
        "reason": str,
    },
)
async def cancel_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    reason = str(args.get("reason", "") or "")
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is empty"})
    matches = _pending_stops_for(ticker)
    if not matches:
        return _text_result({"status": "ok", "cancelled": 0, "reason": "no matching orders"})

    cancelled: List[str] = []
    errors: List[Dict[str, Any]] = []
    for o in matches:
        order_id = str(o.get("id") or o.get("order_id") or "")
        if not order_id:
            continue
        try:
            ok = ctx.broker_service.cancel_order(order_id)
            if ok:
                cancelled.append(order_id)
            else:
                errors.append({"order_id": order_id, "reason": "broker refused"})
        except Exception as e:
            errors.append({"order_id": order_id, "reason": str(e)})

    _journal(
        "stop_cancelled",
        {"tool": "cancel_stop", "ticker": ticker, "cancelled": cancelled,
         "errors": errors, "reason": reason},
        tags=["risk", "stop"],
    )
    return _text_result({
        "status": "ok" if not errors else "partial",
        "cancelled": len(cancelled),
        "cancelled_ids": cancelled,
        "errors": errors,
        "reason": reason,
    })


@tool(
    "list_active_stops",
    "Return every pending stop-loss (stop SELL), breakout stop (stop BUY), "
    "and take-profit (limit SELL) currently armed at the broker, with "
    "their trigger levels. Use before adjusting levels so the agent "
    "knows what's already in place.",
    {},
)
async def list_active_stops(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    orders = ctx.broker_service.get_pending_orders() or []
    out: List[Dict[str, Any]] = []
    for o in orders:
        otype = str(o.get("order_type", "")).lower()
        side = str(o.get("side", "")).upper()
        if otype == "stop":
            kind = "stop_loss" if side == "SELL" else "stop_entry"
        elif otype == "limit" and side == "SELL":
            kind = "take_profit"
        else:
            continue  # regular pending BUY limit / queued market — not a protective order
        out.append({
            "kind": kind,
            "order_id": o.get("id") or o.get("order_id"),
            "ticker": o.get("ticker"),
            "side": side,
            "quantity": o.get("quantity"),
            "stop_price": o.get("stop_price"),
            "limit_price": o.get("limit_price"),
            "queue_reason": o.get("queue_reason"),
            "created_at": o.get("created_at"),
        })
    _journal("tool_call", {"tool": "list_active_stops", "count": len(out)})
    return _text_result(out)


@tool(
    "paper_deposit",
    "Credit the paper sandbox with simulated cash. Paper mode only — returns "
    "a REJECTED status when the stocks broker is live. Supply a positive "
    "``amount`` in the account currency. Deposits are *not* profit: they "
    "only move ``cash_free`` and the lifetime deposit counter; realised "
    "P&L (and therefore commission) is unaffected.",
    {"amount": float},
)
async def paper_deposit(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    amount = float(args.get("amount", 0) or 0)
    if amount <= 0:
        return _text_result({
            "status": "rejected",
            "reason": f"amount must be positive, got {amount}",
        })
    try:
        result = ctx.broker_service.deposit_paper(amount)
    except Exception as e:
        _journal(
            "deposit_error",
            {"tool": "paper_deposit", "amount": amount, "error": str(e)},
            tags=["error"],
        )
        return _text_result({"status": "error", "reason": str(e)})
    _journal(
        "paper_deposit",
        {"tool": "paper_deposit", "amount": amount, "result": result},
        tags=["deposit"],
    )
    return _text_result(result)


BROKER_TOOLS = [
    get_portfolio,
    get_pending_orders,
    get_order_history,
    place_order,
    cancel_order,
    modify_order,
    set_stop_loss,
    set_take_profit,
    adjust_stop,
    cancel_stop,
    list_active_stops,
    paper_deposit,
]
