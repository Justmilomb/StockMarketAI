"""Execution-planning MCP tool.

The agent calls ``plan_vwap_twap`` to preview how a large order would be
sliced before committing. Placement still happens via ``place_order`` —
this tool is advisory today, but the plan structure is what a future
child-order broker would iterate.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.execution.vwap import plan_execution


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "plan_vwap_twap",
    "Build a VWAP or TWAP execution plan for a large order. Returns a "
    "list of time-sliced child orders (`fire_at`, `shares`, `weight`). "
    "Use VWAP when liquidity is predictable (normal session), TWAP when "
    "uncertain (pre-market, news events, thin names).\n\nThis is a "
    "planning tool — it does not place orders on its own. Call "
    "place_order per slice if you want to execute the plan.",
    {"ticker": str, "side": str, "total_shares": float,
     "duration_minutes": int, "strategy": str, "slices": int},
)
async def plan_vwap_twap(args: Dict[str, Any]) -> Dict[str, Any]:
    plan = plan_execution(
        ticker=str(args.get("ticker", "")),
        side=str(args.get("side", "BUY")),
        total_shares=float(args.get("total_shares", 0) or 0),
        duration_minutes=int(args.get("duration_minutes", 60) or 60),
        strategy=str(args.get("strategy", "twap")),
        slices=int(args.get("slices", 6) or 6),
    )
    return _text_result(plan)


EXECUTION_TOOLS = [plan_vwap_twap]
