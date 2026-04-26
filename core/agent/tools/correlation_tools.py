"""Correlation engine tools.

Surface the pending sector-correlation signals to the agent. These get
populated by the scraper runner whenever a news headline matches one
of the curated rules in ``core.correlation_engine``. The agent reads
the queue, decides whether to act, and acknowledges (or dismisses)
each signal so it doesn't keep re-firing.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.correlation_engine import (
    CORRELATION_RULES,
    acknowledge_signal,
    get_pending_signals,
)


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(payload: Dict[str, Any]) -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, ?)",
                (
                    ctx.iteration_id, payload.get("tool", ""),
                    json.dumps(payload, default=str), "correlation",
                ),
            )
    except Exception:
        pass


@tool(
    "get_correlation_signals",
    "Read every pending correlation-engine signal — sector triggers "
    "(oil moving, defense news, tech selloff, etc.) that the scraper "
    "runner mapped to specific tickers via the curated rule set. Each "
    "row carries the matched trigger key, the suggested action, and "
    "the source headline so you can decide whether the headline really "
    "supports the trade. Acknowledge with ``acknowledge_correlation_"
    "signal`` so it stops resurfacing. Default limit 50.",
    {"limit": int},
)
async def get_correlation_signals(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    limit = max(1, min(200, int(args.get("limit", 50) or 50)))
    rows: List[Dict[str, Any]] = get_pending_signals(ctx.db.db_path, limit=limit)
    _journal({"tool": "get_correlation_signals", "count": len(rows)})
    return _text_result({"signals": rows, "count": len(rows)})


@tool(
    "acknowledge_correlation_signal",
    "Mark a correlation signal as handled so it stops appearing in "
    "``get_correlation_signals``. Pass ``status='dismissed'`` if the "
    "signal was a false positive you don't want to act on; "
    "``status='acted'`` if you placed a trade off the back of it. "
    "Defaults to ``acknowledged``.",
    {"signal_id": int, "status": str},
)
async def acknowledge_correlation_signal(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    try:
        signal_id = int(args.get("signal_id", 0))
    except (TypeError, ValueError):
        return _text_result({"status": "rejected", "reason": "signal_id must be an integer"})
    if signal_id <= 0:
        return _text_result({"status": "rejected", "reason": "signal_id must be > 0"})

    new_status = str(args.get("status", "acknowledged") or "acknowledged").lower()
    if new_status not in ("acknowledged", "dismissed", "acted"):
        return _text_result({
            "status": "rejected",
            "reason": "status must be 'acknowledged', 'dismissed', or 'acted'",
        })

    ok = acknowledge_signal(ctx.db.db_path, signal_id, new_status=new_status)
    _journal({
        "tool": "acknowledge_correlation_signal",
        "signal_id": signal_id, "new_status": new_status, "ok": ok,
    })
    return _text_result({"status": "ok" if ok else "not_found", "signal_id": signal_id})


@tool(
    "list_correlation_rules",
    "Return the static correlation-rule library so you can see which "
    "trigger keys exist and which tickers they map to.",
    {},
)
async def list_correlation_rules(args: Dict[str, Any]) -> Dict[str, Any]:
    rules: List[Dict[str, Any]] = []
    for rule in CORRELATION_RULES:
        rules.append({
            "trigger_key": rule.trigger_key,
            "keywords": list(rule.keywords),
            "targets": [
                {"ticker": t, "direction": d, "action": a}
                for t, d, a in rule.targets
            ],
        })
    return _text_result({"rules": rules, "count": len(rules)})


CORRELATION_TOOLS = [
    get_correlation_signals,
    acknowledge_correlation_signal,
    list_correlation_rules,
]
