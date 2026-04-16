"""Market-hours tools for the AI agent.

``get_market_status`` is the single entry point. It asks
:mod:`core.market_hours` for every registered exchange, joins the
result with the broker's current positions, and returns a JSON-safe
dict the agent can use to decide how long to sleep.

The shape is designed for a quick ``end_iteration`` heuristic:

    * If every exchange with positions is closed and the next open is
      hours away, the agent should sleep for *hours*.
    * If a position's exchange is open, the agent should check back on
      the normal cadence (minutes).
    * If everything is closed and the agent has no positions, a long
      sleep is the right call.

The tool is read-only and cheap — it does not touch the network beyond
the broker positions call every other tool already does. Budget: one
fast broker call, no HTTP, no yfinance.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from core.agent._sdk import tool

from core.agent.context import get_agent_context
from core.market_hours import Exchange, all_exchanges, exchange_for_ticker, status


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _positions_by_exchange(positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group broker positions by exchange code.

    Unrecognised tickers (crypto, unmapped suffixes) land under
    ``"UNKNOWN"`` so the agent can see them without the tool quietly
    losing them.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for p in positions:
        ticker = str(p.get("ticker", ""))
        ex: Exchange | None = exchange_for_ticker(ticker)
        code = ex.code if ex else "UNKNOWN"
        bucket = out.setdefault(code, {"count": 0, "tickers": []})
        bucket["count"] += 1
        bucket["tickers"].append(ticker)
    return out


@tool(
    "get_market_status",
    (
        "Return the live open/closed status of every supported stock "
        "exchange along with how many of your current positions trade on "
        "each venue. Use this to pick a smart `next_check_in_minutes` when "
        "you call `end_iteration`: if every exchange hosting a position "
        "is closed and the next open is hours away, sleep for hours. If "
        "a held position's market is open, check back on the normal "
        "cadence. Covers US, LSE, XETRA, Euronext Paris/Amsterdam, BME, "
        "Borsa Italiana, SIX Swiss, Nasdaq Nordics, Oslo, TASE. Regular "
        "sessions only — holidays are not modelled."
    ),
    {},
)
async def get_market_status(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    # Ask the broker for positions exactly once — no cached snapshot.
    try:
        positions = ctx.broker_service.get_positions()
    except Exception as exc:
        positions = []
        _journal_error("get_market_status", str(exc))

    by_exchange = _positions_by_exchange(positions)

    exchanges: List[Dict[str, Any]] = []
    open_count = 0
    for ex in all_exchanges():
        snapshot = status(ex)
        bucket = by_exchange.get(ex.code, {"count": 0, "tickers": []})
        snapshot["positions_count"] = int(bucket["count"])
        snapshot["position_tickers"] = list(bucket["tickers"])
        if snapshot["is_open"]:
            open_count += 1
        exchanges.append(snapshot)

    unknown = by_exchange.get("UNKNOWN")
    result = {
        "exchanges": exchanges,
        "open_count": open_count,
        "total_positions": sum(b["count"] for b in by_exchange.values()),
        "unmapped_tickers": list(unknown["tickers"]) if unknown else [],
    }

    _journal_call(
        tool_name="get_market_status",
        payload={
            "open_count": open_count,
            "total_positions": result["total_positions"],
        },
    )
    return _text_result(result)


def _journal_call(tool_name: str, payload: Dict[str, Any]) -> None:
    """Write a best-effort journal row so the UI log shows the call."""
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, 'market_hours')",
                (ctx.iteration_id, tool_name, json.dumps(payload, default=str)),
            )
    except Exception:
        # Journal writes are best-effort — never break the tool.
        pass


def _journal_error(tool_name: str, message: str) -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_error', ?, ?, 'market_hours,error')",
                (ctx.iteration_id, tool_name, json.dumps({"error": message})),
            )
    except Exception:
        pass


MARKET_HOURS_TOOLS = [get_market_status]
