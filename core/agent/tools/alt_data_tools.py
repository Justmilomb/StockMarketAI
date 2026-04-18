"""Alt-data MCP tools: analyst revisions and EPS momentum."""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.alt_data.analyst_revisions import revision_momentum


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "analyst_revision_momentum",
    "Compute two analyst-based signals for *ticker*: "
    "`recommendation_velocity` (change in bullish vs bearish analyst "
    "count over the latest month vs earliest available) and "
    "`eps_revision_slope` (linear slope of avg-EPS estimates across "
    "near/far quarters and years). Accelerating upward revisions "
    "historically correlate with stronger forward returns.",
    {"ticker": str},
)
async def analyst_revision_momentum(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    return _text_result(revision_momentum(ticker))


ALT_DATA_TOOLS = [analyst_revision_momentum]
