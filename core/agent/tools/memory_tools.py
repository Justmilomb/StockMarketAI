"""Memory tools — key/value scratchpad + append-only journal.

Backed by the agent_memory and agent_journal tables created in Phase 1.
Tool names use ``agent_`` prefix so they don't collide with the
separate ``ai_memory`` table used by the legacy chat assistant.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from core.agent._sdk import tool

from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "read_memory",
    "Read a value from the agent's key-value scratchpad. "
    "Returns None if the key does not exist.",
    {"key": str},
)
async def read_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    key = str(args.get("key", "")).strip()
    if not key:
        return _text_result({"error": "key is required"})
    with sqlite3.connect(ctx.db.db_path) as conn:
        row = conn.execute(
            "SELECT value, updated_at FROM agent_memory WHERE key = ?", (key,),
        ).fetchone()
    if row is None:
        return _text_result({"key": key, "value": None})
    return _text_result({"key": key, "value": row[0], "updated_at": row[1]})


@tool(
    "write_memory",
    "Persist a value under a key in the agent's scratchpad. Overwrites on conflict. "
    "Use this for things you want to remember across iterations.",
    {"key": str, "value": str},
)
async def write_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    key = str(args.get("key", "")).strip()
    value = str(args.get("value", ""))
    if not key:
        return _text_result({"error": "key is required"})
    with sqlite3.connect(ctx.db.db_path) as conn:
        conn.execute(
            "INSERT INTO agent_memory (key, value, updated_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = datetime('now')",
            (key, value),
        )
    return _text_result({"key": key, "status": "written"})


@tool(
    "list_memory_keys",
    "Return every key currently stored in the agent scratchpad.",
    {},
)
async def list_memory_keys(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    with sqlite3.connect(ctx.db.db_path) as conn:
        rows = conn.execute(
            "SELECT key, updated_at FROM agent_memory ORDER BY updated_at DESC",
        ).fetchall()
    return _text_result([{"key": r[0], "updated_at": r[1]} for r in rows])


@tool(
    "append_journal",
    "Append a free-form entry to the agent journal. Tags are optional "
    "(comma-separated string) and help you search later.",
    {
        "type": "object",
        "properties": {
            "entry": {"type": "string", "description": "Journal entry text."},
            "tags": {
                "type": "string",
                "description": "Optional comma-separated tags.",
            },
        },
        "required": ["entry"],
    },
)
async def append_journal(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    entry = str(args.get("entry", ""))
    tags = str(args.get("tags", "") or "")
    if not entry:
        return _text_result({"error": "entry is required"})
    with sqlite3.connect(ctx.db.db_path) as conn:
        conn.execute(
            "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
            "VALUES (?, 'note', 'append_journal', ?, ?)",
            (ctx.iteration_id, entry, tags),
        )
    return _text_result({"status": "appended"})


@tool(
    "read_journal",
    "Return the last N journal entries, optionally filtered by a tag.",
    {"limit": int, "tag": str},
)
async def read_journal(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    limit = int(args.get("limit", 25) or 25)
    tag = str(args.get("tag", "") or "").strip()
    with sqlite3.connect(ctx.db.db_path) as conn:
        if tag:
            rows = conn.execute(
                "SELECT timestamp, iteration_id, kind, tool, payload, tags "
                "FROM agent_journal WHERE tags LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{tag}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT timestamp, iteration_id, kind, tool, payload, tags "
                "FROM agent_journal ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    entries: List[Dict[str, Any]] = []
    for r in rows:
        entries.append({
            "ts": r[0], "iteration_id": r[1], "kind": r[2],
            "tool": r[3], "payload": r[4], "tags": r[5],
        })
    return _text_result(entries)


MEMORY_TOOLS = [
    read_memory,
    write_memory,
    list_memory_keys,
    append_journal,
    read_journal,
]
