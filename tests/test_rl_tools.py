from __future__ import annotations

import asyncio
import json


def test_rl_portfolio_allocation_cold_start():
    from core.agent.tools import rl_tools

    async def run():
        return await rl_tools.rl_portfolio_allocation.handler({
            "tickers": ["TSLA", "AAPL"], "equity": 100.0, "regime": "neutral",
        })

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert round(sum(payload["weights"].values()), 4) == 1.0
    assert payload["rebalance_hours"] > 0
    assert payload["source"] == "equal_weight_cold_start"


def test_rl_portfolio_allocation_empty_tickers():
    from core.agent.tools import rl_tools

    async def run():
        return await rl_tools.rl_portfolio_allocation.handler({
            "tickers": [], "equity": 100.0, "regime": "neutral",
        })

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["weights"] == {}
    assert payload["source"] == "empty"


def test_rl_portfolio_allocation_crisis_regime():
    from core.agent.tools import rl_tools

    async def run():
        return await rl_tools.rl_portfolio_allocation.handler({
            "tickers": ["TSLA"], "equity": 100.0, "regime": "crisis",
        })

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["rebalance_hours"] == 6
