"""Flow-control tools — end_iteration.

``end_iteration`` is how the agent cleanly closes a turn. The tool writes
a summary to agent_journal, flips ``AgentContext.end_requested``, records
the requested delay, and returns — leaving the runner to kill the
subprocess on the next tool-call pause. The SDK does not let a tool
hard-stop its own query, so this is a soft signal: after the tool
returns, the agent is expected to emit one last text message and stop
calling tools.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

from core.agent._sdk import tool

from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "end_iteration",
    "Signal that you are done for this turn. Provide a short `summary` "
    "of what you decided and did, plus `next_check_in_minutes` — how "
    "long you want to sleep before the next wake-up (the runner clamps "
    "this to the configured cadence floor). After calling this tool, "
    "emit one final text message and stop calling tools.",
    {"summary": str, "next_check_in_minutes": int},
)
async def end_iteration(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    summary = str(args.get("summary", "") or "").strip()
    try:
        minutes = int(args.get("next_check_in_minutes", 5) or 5)
    except (TypeError, ValueError):
        minutes = 5
    if minutes < 0:
        minutes = 0

    ctx.end_requested = True
    ctx.next_wait_minutes = minutes
    ctx.end_summary = summary

    # Fire the cadence hook *before* the journal write so the settings
    # panel countdown flips to the new value immediately, not after the
    # ~5-20s post-iteration assessor/reflector tail. The hook is
    # best-effort — a runner that didn't install one is fine.
    hook = ctx.cadence_hook
    if hook is not None:
        try:
            hook(minutes)
        except Exception:
            pass

    with sqlite3.connect(ctx.db.db_path) as conn:
        conn.execute(
            "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
            "VALUES (?, 'iteration_end', 'end_iteration', ?, 'flow')",
            (
                ctx.iteration_id,
                json.dumps(
                    {"summary": summary, "next_check_in_minutes": minutes},
                    default=str,
                ),
            ),
        )

    return _text_result({
        "status": "ended",
        "next_check_in_minutes": minutes,
        "summary": summary,
    })


FLOW_TOOLS = [end_iteration]
