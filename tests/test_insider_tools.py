from __future__ import annotations

import asyncio
import json
from unittest.mock import patch


def test_recent_insider_trades_tool():
    from core.agent.tools import insider_tools

    async def run():
        with patch(
            "core.agent.tools.insider_tools.fetch_form4",
            return_value=[{
                "ticker": "TSLA", "title": "CEO bought 100k shares",
                "filing_date": "2026-04-10", "url": "x", "summary": "",
            }],
        ):
            return await insider_tools.recent_insider_trades.handler({"ticker": "TSLA"})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["count"] == 1


def test_recent_insider_trades_rejects_empty():
    from core.agent.tools import insider_tools

    async def run():
        return await insider_tools.recent_insider_trades.handler({"ticker": ""})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert "error" in payload


def test_unusual_options_activity_tool_bullish():
    from core.agent.tools import insider_tools

    async def run():
        with patch(
            "core.agent.tools.insider_tools.unusual_activity",
            return_value=[{
                "ticker": "TSLA", "side": "call", "strike": 105.0,
                "volume": 2000, "oi": 100, "vol_oi_ratio": 20.0,
                "iv": 0.5, "spot": 104.0, "moneyness": 0.99,
                "expiry": "2026-05-01",
            }],
        ):
            return await insider_tools.unusual_options_activity_tool.handler({"ticker": "TSLA"})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["net_bias"] == "bullish"


def test_unusual_options_activity_tool_neutral():
    from core.agent.tools import insider_tools

    async def run():
        with patch(
            "core.agent.tools.insider_tools.unusual_activity",
            return_value=[],
        ):
            return await insider_tools.unusual_options_activity_tool.handler({"ticker": "TSLA"})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["net_bias"] == "neutral"
