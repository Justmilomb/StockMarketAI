"""Stop-loss / take-profit / trailing-stop tools.

These tools register, modify, and cancel stops monitored by the
``StopEngine`` daemon — independent of the agent's iteration cadence.
The engine polls live prices every second and submits the corresponding
market sell the instant a trigger fires, so a flash-crash that prints
through a stop between agent wake-ups still books at (or very close to)
the trigger.

Stops persist inside ``data/paper_state.json`` next to positions and
queued orders, so a session restart resumes monitoring without the
agent re-creating them.

GBX vs GBP. Yfinance quotes ``.L`` tickers in pence (GBX). Tool callers
can pass an optional ``unit`` field — ``"native"`` (default), ``"GBP"``,
or ``"GBX"``. ``"GBP"`` on a London ticker is converted to pence for
storage and comparison; the response echoes back the original unit so
the user-facing display can stay in pounds.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.stop_engine import (
    STOP_KINDS,
    build_stop,
    is_gbx_quoted,
    native_to_unit,
    unit_to_native,
)


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(kind: str, payload: Dict[str, Any], tags: list[str] | None = None) -> None:
    ctx = get_agent_context()
    with sqlite3.connect(ctx.db.db_path) as conn:
        conn.execute(
            "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ctx.iteration_id, kind, payload.get("tool", ""),
                json.dumps(payload, default=str), ",".join(tags or []),
            ),
        )


def _paper_broker() -> Any:
    """Return the underlying PaperBroker, or None when the broker is live.

    Stops are paper-only — Trading 212 manages stops natively. We expose
    a clear "live" rejection rather than silently no-op'ing.
    """
    ctx = get_agent_context()
    svc = ctx.broker_service
    broker = getattr(svc, "broker", svc)
    try:
        from paper_broker import PaperBroker
    except Exception:  # pragma: no cover
        return None
    return broker if isinstance(broker, PaperBroker) else None


def _reject_if_live() -> Dict[str, Any] | None:
    if _paper_broker() is None:
        return _text_result({
            "status": "rejected",
            "reason": "stop tools are paper-mode only; live broker manages stops natively",
        })
    return None


def _format_stop(stop: Dict[str, Any], unit: str = "native") -> Dict[str, Any]:
    """Annotate a stored stop dict with the user's preferred display unit."""
    ticker = str(stop.get("ticker", ""))
    out = dict(stop)
    if unit and unit.lower() != "native":
        if stop.get("trigger_price"):
            out["trigger_price_in_unit"] = native_to_unit(
                ticker, float(stop["trigger_price"]), unit,
            )
        if stop.get("high_water_mark") is not None:
            out["high_water_mark_in_unit"] = native_to_unit(
                ticker, float(stop["high_water_mark"]), unit,
            )
        if stop.get("trail_distance") is not None and is_gbx_quoted(ticker) and unit.upper() == "GBP":
            out["trail_distance_in_unit"] = float(stop["trail_distance"]) / 100.0
        out["display_unit"] = unit.upper()
    return out


# ── set_stop_loss ───────────────────────────────────────────────────────

@tool(
    "set_stop_loss",
    "Place a stop-loss on a held position. The native price monitor checks "
    "the live price every second and issues a market SELL the instant the "
    "price touches or breaks the trigger. Paper-mode only. ``unit`` is one "
    "of 'native' (default), 'GBP', or 'GBX' — pass 'GBP' on .L tickers if "
    "you want to think in pounds rather than pence.",
    {
        "ticker": str,
        "trigger_price": float,
        "quantity": float,
        "unit": str,
        "reason": str,
    },
)
async def set_stop_loss(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    ticker = str(args.get("ticker", "")).strip()
    quantity = float(args.get("quantity", 0) or 0)
    trigger_input = float(args.get("trigger_price", 0) or 0)
    unit = str(args.get("unit", "native") or "native")
    reason = str(args.get("reason", "") or "")
    try:
        trigger_native = unit_to_native(ticker, trigger_input, unit)
        stop = build_stop(
            ticker=ticker, kind="stop_loss", quantity=quantity,
            trigger_price=trigger_native, reason=reason,
        )
    except ValueError as e:
        return _text_result({"status": "rejected", "reason": str(e)})

    saved = _paper_broker().add_stop(stop)
    _journal(
        "stop_set",
        {"tool": "set_stop_loss", "stop": saved, "unit_in": unit, "reason": reason},
        tags=["stop", "stop_loss"],
    )
    return _text_result({"status": "set", "stop": _format_stop(saved, unit)})


# ── set_take_profit ────────────────────────────────────────────────────

@tool(
    "set_take_profit",
    "Place a take-profit on a held position. Fires a market SELL when the "
    "live price first touches or exceeds the trigger. Paper-mode only. "
    "``unit`` accepts 'native' (default), 'GBP', or 'GBX'.",
    {
        "ticker": str,
        "trigger_price": float,
        "quantity": float,
        "unit": str,
        "reason": str,
    },
)
async def set_take_profit(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    ticker = str(args.get("ticker", "")).strip()
    quantity = float(args.get("quantity", 0) or 0)
    trigger_input = float(args.get("trigger_price", 0) or 0)
    unit = str(args.get("unit", "native") or "native")
    reason = str(args.get("reason", "") or "")
    try:
        trigger_native = unit_to_native(ticker, trigger_input, unit)
        stop = build_stop(
            ticker=ticker, kind="take_profit", quantity=quantity,
            trigger_price=trigger_native, reason=reason,
        )
    except ValueError as e:
        return _text_result({"status": "rejected", "reason": str(e)})

    saved = _paper_broker().add_stop(stop)
    _journal(
        "stop_set",
        {"tool": "set_take_profit", "stop": saved, "unit_in": unit, "reason": reason},
        tags=["stop", "take_profit"],
    )
    return _text_result({"status": "set", "stop": _format_stop(saved, unit)})


# ── set_trailing_stop ──────────────────────────────────────────────────

@tool(
    "set_trailing_stop",
    "Place a trailing stop on a held position. The monitor tracks the "
    "high-water mark each tick; the stop fires when the price retreats "
    "by either ``trail_distance`` (absolute) or ``trail_distance_pct`` "
    "(percentage) from the peak. Supply exactly one of those two. "
    "``unit`` accepts 'native' (default), 'GBP', or 'GBX' for absolute "
    "distances on London tickers.",
    {
        "ticker": str,
        "quantity": float,
        "trail_distance": float,
        "trail_distance_pct": float,
        "unit": str,
        "reason": str,
    },
)
async def set_trailing_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    ticker = str(args.get("ticker", "")).strip()
    quantity = float(args.get("quantity", 0) or 0)
    distance_in = args.get("trail_distance")
    distance_pct = args.get("trail_distance_pct")
    unit = str(args.get("unit", "native") or "native")
    reason = str(args.get("reason", "") or "")

    distance_native: float | None = None
    if distance_in is not None:
        distance_native = unit_to_native(ticker, float(distance_in), unit)
    pct = float(distance_pct) if distance_pct is not None else None

    try:
        stop = build_stop(
            ticker=ticker, kind="trailing_stop", quantity=quantity,
            trail_distance=distance_native, trail_distance_pct=pct,
            reason=reason,
        )
    except ValueError as e:
        return _text_result({"status": "rejected", "reason": str(e)})

    saved = _paper_broker().add_stop(stop)
    _journal(
        "stop_set",
        {"tool": "set_trailing_stop", "stop": saved, "unit_in": unit, "reason": reason},
        tags=["stop", "trailing_stop"],
    )
    return _text_result({"status": "set", "stop": _format_stop(saved, unit)})


# ── adjust_stop ────────────────────────────────────────────────────────

@tool(
    "adjust_stop",
    "Modify an active stop in place. Pass ``stop_id`` plus any of "
    "``trigger_price``, ``trail_distance``, ``trail_distance_pct``, or "
    "``quantity``. ``unit`` is honoured for any price-shaped field.",
    {
        "stop_id": str,
        "trigger_price": float,
        "trail_distance": float,
        "trail_distance_pct": float,
        "quantity": float,
        "unit": str,
        "reason": str,
    },
)
async def adjust_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    stop_id = str(args.get("stop_id", "")).strip()
    if not stop_id:
        return _text_result({"status": "rejected", "reason": "stop_id is required"})

    broker = _paper_broker()
    existing = next(
        (s for s in broker.list_stops() if s.get("stop_id") == stop_id), None,
    )
    if existing is None:
        return _text_result({"status": "rejected", "reason": f"no active stop {stop_id}"})

    ticker = str(existing.get("ticker", ""))
    unit = str(args.get("unit", "native") or "native")
    updates: Dict[str, Any] = {}

    if args.get("trigger_price") is not None:
        updates["trigger_price"] = unit_to_native(
            ticker, float(args["trigger_price"]), unit,
        )
    if args.get("trail_distance") is not None:
        updates["trail_distance"] = unit_to_native(
            ticker, float(args["trail_distance"]), unit,
        )
    if args.get("trail_distance_pct") is not None:
        updates["trail_distance_pct"] = float(args["trail_distance_pct"])
    if args.get("quantity") is not None:
        qty = float(args["quantity"])
        if qty <= 0:
            return _text_result({"status": "rejected", "reason": "quantity must be > 0"})
        updates["quantity"] = qty
    reason = str(args.get("reason", "") or "")
    if reason:
        updates["reason"] = reason

    if not updates:
        return _text_result({"status": "noop", "reason": "no fields to update"})

    saved = broker.update_stop(stop_id, updates)
    _journal(
        "stop_adjusted",
        {"tool": "adjust_stop", "stop_id": stop_id, "updates": updates,
         "unit_in": unit, "reason": reason},
        tags=["stop"],
    )
    return _text_result({"status": "adjusted", "stop": _format_stop(saved or {}, unit)})


# ── cancel_stop ────────────────────────────────────────────────────────

@tool(
    "cancel_stop",
    "Remove an active stop without firing it. Returns ``rejected`` if the "
    "stop_id is unknown.",
    {"stop_id": str, "reason": str},
)
async def cancel_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    stop_id = str(args.get("stop_id", "")).strip()
    if not stop_id:
        return _text_result({"status": "rejected", "reason": "stop_id is required"})
    reason = str(args.get("reason", "") or "")
    removed = _paper_broker().remove_stop(stop_id)
    if removed is None:
        return _text_result({"status": "rejected", "reason": f"no active stop {stop_id}"})
    _journal(
        "stop_cancelled",
        {"tool": "cancel_stop", "stop": removed, "reason": reason},
        tags=["stop"],
    )
    return _text_result({"status": "cancelled", "stop": removed})


# ── list_active_stops ──────────────────────────────────────────────────

@tool(
    "list_active_stops",
    "Return every active stop, optionally filtered to a single ticker. "
    "``unit`` ('native' default, 'GBP', 'GBX') controls the display "
    "annotations on the response — the stored values are unchanged.",
    {"ticker": str, "unit": str},
)
async def list_active_stops(args: Dict[str, Any]) -> Dict[str, Any]:
    rej = _reject_if_live()
    if rej is not None:
        return rej
    ticker_filter = str(args.get("ticker", "") or "").strip().upper()
    unit = str(args.get("unit", "native") or "native")
    stops = _paper_broker().list_stops()
    if ticker_filter:
        stops = [s for s in stops if str(s.get("ticker", "")).upper() == ticker_filter]
    formatted = [_format_stop(s, unit) for s in stops]
    return _text_result({
        "stops": formatted,
        "count": len(formatted),
        "kinds": list(STOP_KINDS),
    })


STOP_TOOLS = [
    set_stop_loss,
    set_take_profit,
    set_trailing_stop,
    adjust_stop,
    cancel_stop,
    list_active_stops,
]
