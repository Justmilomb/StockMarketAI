"""FinRL portfolio-allocation MCP tool (scaffold)."""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.rl.finrl_scaffold import allocate


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "rl_portfolio_allocation",
    "Return a portfolio weight recommendation for *tickers* given "
    "*equity* and current market *regime*. Today returns an equal-weight "
    "baseline; future versions load trained FinRL PPO/SAC weights. "
    "Always includes a recommended rebalance cadence.",
    {"tickers": list, "equity": float, "regime": str},
)
async def rl_portfolio_allocation(args: Dict[str, Any]) -> Dict[str, Any]:
    tickers = [str(t) for t in (args.get("tickers") or []) if t]
    equity = float(args.get("equity", 0) or 0)
    regime = str(args.get("regime", "neutral"))
    return _text_result(allocate(tickers, equity, regime))


RL_TOOLS = [rl_portfolio_allocation]
