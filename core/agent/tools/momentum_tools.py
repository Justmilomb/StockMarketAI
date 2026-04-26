"""Momentum trigger tools.

Lets the agent arm pre-set rules of the form *"if price moves >= X% in
the last 10 seconds, fire a market BUY/SELL of size Q without waiting
for the next iteration"*. The 1-second StopEngine polls these triggers
on the same loop it uses for stop-loss / take-profit / trailing stops,
so a flash spike fires immediately rather than on the next supervisor
wake.

Paper mode only — Trading 212's REST surface doesn't expose the same
sub-second monitoring hook, and live momentum execution belongs at the
broker, not in this process.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(kind: str, payload: Dict[str, Any]) -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ctx.iteration_id, kind, payload.get("tool", ""),
                    json.dumps(payload, default=str), "momentum",
                ),
            )
    except Exception:
        pass


def _paper_broker() -> Optional[Any]:
    """Return the active paper broker, or None when running live."""
    try:
        ctx = get_agent_context()
        broker = getattr(ctx.broker_service, "broker", None) or ctx.broker_service
    except Exception:
        return None
    try:
        from paper_broker import PaperBroker
    except Exception:
        return None
    return broker if isinstance(broker, PaperBroker) else None


@tool(
    "set_momentum_trigger",
    "Arm a sub-second momentum trigger on a ticker. When the price "
    "moves >= ``threshold_pct`` in ``direction`` over the rolling "
    "10-second window, the StopEngine fires a market ``buy`` or "
    "``sell`` of ``quantity`` shares without waiting for the next "
    "iteration. Use this for pre-positioning around a catalyst — e.g. "
    "FDA decision, earnings print, rate announcement. Triggers are "
    "single-shot: after firing they are removed. Optional ``ttl_minutes`` "
    "(default 60) reaps the trigger if it never fires. Paper mode only.",
    {
        "ticker": str,
        "direction": str,
        "threshold_pct": float,
        "action": str,
        "quantity": float,
        "ttl_minutes": int,
        "reason": str,
    },
)
async def set_momentum_trigger(args: Dict[str, Any]) -> Dict[str, Any]:
    broker = _paper_broker()
    if broker is None:
        return _text_result({
            "status": "rejected",
            "reason": "momentum triggers require paper mode",
        })

    ticker = str(args.get("ticker", "")).strip()
    direction = str(args.get("direction", "")).strip().lower()
    threshold_pct = float(args.get("threshold_pct", 0.0) or 0.0)
    action = str(args.get("action", "")).strip().lower()
    quantity = float(args.get("quantity", 0.0) or 0.0)
    ttl_minutes = max(1, int(args.get("ttl_minutes", 60) or 60))
    reason = str(args.get("reason", "") or "")

    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})
    if direction not in ("up", "down"):
        return _text_result({"status": "rejected", "reason": "direction must be 'up' or 'down'"})
    if threshold_pct <= 0 or threshold_pct > 50:
        return _text_result({"status": "rejected", "reason": "threshold_pct must be between 0 and 50"})
    if action not in ("buy", "sell"):
        return _text_result({"status": "rejected", "reason": "action must be 'buy' or 'sell'"})
    if quantity <= 0:
        return _text_result({"status": "rejected", "reason": "quantity must be > 0"})

    trigger_id = f"mom-{uuid.uuid4().hex[:10]}"
    record: Dict[str, Any] = {
        "trigger_id": trigger_id,
        "ticker": ticker,
        "direction": direction,
        "threshold_pct": threshold_pct,
        "action": action,
        "quantity": quantity,
        "ttl_ts": time.time() + ttl_minutes * 60,
        "reason": reason,
        "created_at": time.time(),
    }
    stored = broker.add_momentum_trigger(record)
    _journal("momentum_armed", {"tool": "set_momentum_trigger", **record})
    return _text_result({"status": "armed", "trigger": stored})


@tool(
    "list_momentum_triggers",
    "List every armed momentum trigger across all tickers.",
    {},
)
async def list_momentum_triggers(args: Dict[str, Any]) -> Dict[str, Any]:
    broker = _paper_broker()
    if broker is None:
        return _text_result({"triggers": [], "note": "paper mode required"})
    triggers: List[Dict[str, Any]] = broker.list_momentum_triggers()
    _journal("tool_call", {"tool": "list_momentum_triggers", "count": len(triggers)})
    return _text_result({"triggers": triggers, "count": len(triggers)})


@tool(
    "cancel_momentum_trigger",
    "Disarm a momentum trigger by id.",
    {"trigger_id": str},
)
async def cancel_momentum_trigger(args: Dict[str, Any]) -> Dict[str, Any]:
    broker = _paper_broker()
    if broker is None:
        return _text_result({"status": "rejected", "reason": "paper mode required"})
    trigger_id = str(args.get("trigger_id", "")).strip()
    if not trigger_id:
        return _text_result({"status": "rejected", "reason": "trigger_id is required"})
    removed = broker.remove_momentum_trigger(trigger_id)
    _journal("momentum_cancelled", {
        "tool": "cancel_momentum_trigger",
        "trigger_id": trigger_id,
        "found": removed is not None,
    })
    return _text_result({
        "status": "ok" if removed is not None else "not_found",
        "removed": removed,
    })


MOMENTUM_TOOLS = [
    set_momentum_trigger,
    list_momentum_triggers,
    cancel_momentum_trigger,
]
