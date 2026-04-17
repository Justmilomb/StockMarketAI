"""Watchlist tools — the agent reads and modifies its own watchlist.

Watchlists live in config.json under ``watchlists[active_watchlist]``.
Mutations are persisted back to disk and logged to agent_journal.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

from core.agent._sdk import tool

from core.agent.context import get_agent_context


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


def _active_watchlist_name() -> str:
    ctx = get_agent_context()
    return str(ctx.config.get("active_watchlist", "Trading 212"))


def _watchlists_root() -> Dict[str, Any]:
    ctx = get_agent_context()
    # Paper and live mode maintain separate watchlists so agent mutations in
    # one mode never bleed into the other.
    config_key = "watchlists_paper" if ctx.paper_mode else "watchlists"
    wl = ctx.config.setdefault(config_key, {})
    if not isinstance(wl, dict):
        wl = {}
        ctx.config[config_key] = wl
    return wl


def _save_config() -> None:
    ctx = get_agent_context()
    path = Path(ctx.config.get("__config_path__", "config.json"))
    # Drop the sentinel before serialising
    data = {k: v for k, v in ctx.config.items() if k != "__config_path__"}
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@tool(
    "get_watchlist",
    "Return the tickers on the currently active watchlist.",
    {},
)
async def get_watchlist(args: Dict[str, Any]) -> Dict[str, Any]:
    wl_root = _watchlists_root()
    name = _active_watchlist_name()
    tickers = list(wl_root.get(name, []) or [])
    return _text_result({"watchlist": name, "tickers": tickers})


def add_to_watchlist_sync(
    ticker: str,
    reason: str = "",
    tool_tag: str = "add_to_watchlist",
) -> Dict[str, Any]:
    """Plain helper used by both the MCP tool and other tools (place_order).

    Returns a dict shaped like ``{"status": ..., "ticker": ..., "watchlist": ...}``
    so callers can log the outcome without parsing the MCP text envelope.
    Never raises — a failure is reported as ``status == "error"``.
    """
    ticker = str(ticker or "").strip()
    if not ticker:
        return {"status": "rejected", "reason": "ticker is required"}

    try:
        wl_root = _watchlists_root()
        name = _active_watchlist_name()
        tickers = list(wl_root.get(name, []) or [])
        if ticker in tickers:
            return {"status": "noop", "reason": "already on watchlist",
                    "ticker": ticker, "watchlist": name}
        tickers.append(ticker)
        wl_root[name] = tickers
        _save_config()
        _journal(
            "watchlist_add",
            {"tool": tool_tag, "ticker": ticker, "reason": reason, "watchlist": name},
            tags=["watchlist"],
        )
        return {"status": "added", "ticker": ticker, "watchlist": name}
    except Exception as e:
        return {"status": "error", "reason": str(e), "ticker": ticker}


@tool(
    "add_to_watchlist",
    "Add a ticker to the active watchlist. Supply a short reason for the journal.",
    {"ticker": str, "reason": str},
)
async def add_to_watchlist(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    reason = str(args.get("reason", ""))
    result = add_to_watchlist_sync(ticker, reason=reason, tool_tag="add_to_watchlist")
    return _text_result(result)


@tool(
    "remove_from_watchlist",
    "Remove a ticker from the active watchlist. Supply a short reason for the journal.",
    {"ticker": str, "reason": str},
)
async def remove_from_watchlist(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    reason = str(args.get("reason", ""))
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker is required"})

    wl_root = _watchlists_root()
    name = _active_watchlist_name()
    tickers = list(wl_root.get(name, []) or [])
    if ticker not in tickers:
        return _text_result({"status": "noop", "reason": "not on watchlist"})
    tickers = [t for t in tickers if t != ticker]
    wl_root[name] = tickers
    _save_config()
    _journal(
        "watchlist_remove",
        {"tool": "remove_from_watchlist", "ticker": ticker, "reason": reason, "watchlist": name},
        tags=["watchlist"],
    )
    return _text_result({"status": "removed", "ticker": ticker, "watchlist": name})


@tool(
    "clear_watchlist_except",
    "Remove every ticker from the active watchlist except the ones in 'keep'. "
    "Typical use: chat asks to keep only tickers the user has open positions in, "
    "so first call get_portfolio, extract the ticker list, then pass it here. "
    "Supply a short reason for the journal.",
    {"keep": list, "reason": str},
)
async def clear_watchlist_except(args: Dict[str, Any]) -> Dict[str, Any]:
    keep_raw = args.get("keep") or []
    # Case-insensitive match — the watchlist can carry broker-specific
    # suffixes (e.g. "NVDA_US_EQ") but the user usually types plain tickers,
    # so we compare on uppercase prefix / exact uppercase.
    keep_upper = {str(t).strip().upper() for t in keep_raw if str(t).strip()}
    reason = str(args.get("reason", ""))

    wl_root = _watchlists_root()
    name = _active_watchlist_name()
    tickers = list(wl_root.get(name, []) or [])

    # Normalise both sides to their root symbol (strip broker suffixes like
    # "_US_EQ", "_EQ") so "VUKG" matches "VUKG_EQ" and vice-versa.
    def _normalise(t: str) -> str:
        return t.strip().upper().split("_", 1)[0]

    keep_normalised = {_normalise(k) for k in keep_raw if str(k).strip()}

    def _matches(ticker: str) -> bool:
        t_up = ticker.upper()
        # Exact match first (handles identical formats).
        if t_up in keep_upper:
            return True
        # Normalised match: covers "VUKG" vs "VUKG_EQ" in either direction.
        return _normalise(ticker) in keep_normalised

    kept = [t for t in tickers if _matches(t)]
    removed = [t for t in tickers if not _matches(t)]

    if not removed:
        return _text_result({
            "status": "noop",
            "reason": "nothing to remove",
            "watchlist": name,
            "kept": kept,
        })

    wl_root[name] = kept
    _save_config()
    _journal(
        "watchlist_clear_except",
        {
            "tool": "clear_watchlist_except",
            "kept": kept,
            "removed": removed,
            "reason": reason,
            "watchlist": name,
        },
        tags=["watchlist"],
    )
    return _text_result({
        "status": "cleared",
        "watchlist": name,
        "kept": kept,
        "removed": removed,
    })


WATCHLIST_TOOLS = [
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    clear_watchlist_except,
]
