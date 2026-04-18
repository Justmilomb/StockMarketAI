"""create_sdk_mcp_server wiring for the agent tool bus.

Every tool module exports a ``*_TOOLS`` list of decorated callables.
This module flattens those lists into a single in-process MCP server
that the runner passes to the agent options ``mcp_servers`` parameter.

Phase 8 tool coverage:
    broker_tools, market_tools, risk_tools, memory_tools,
    watchlist_tools, flow_tools, news_tools, social_tools,
    browser_tools, market_hours_tools, backtest_tools,
    indicator_tools, strategy_backtest_tools, performance_tools
"""
from __future__ import annotations

from typing import Any, List

from core.agent._sdk import create_sdk_mcp_server

from core.agent.tools.backtest_tools import BACKTEST_TOOLS
from core.agent.tools.broker_tools import BROKER_TOOLS
from core.agent.tools.browser_tools import BROWSER_TOOLS
from core.agent.tools.flow_tools import FLOW_TOOLS
from core.agent.tools.indicator_tools import INDICATOR_TOOLS
from core.agent.tools.market_hours_tools import MARKET_HOURS_TOOLS
from core.agent.tools.market_tools import MARKET_TOOLS
from core.agent.tools.memory_tools import MEMORY_TOOLS
from core.agent.tools.news_tools import NEWS_TOOLS
from core.agent.tools.performance_tools import PERFORMANCE_TOOLS
from core.agent.tools.risk_tools import RISK_TOOLS
from core.agent.tools.social_tools import SOCIAL_TOOLS
from core.agent.tools.strategy_backtest_tools import STRATEGY_BACKTEST_TOOLS
from core.agent.tools.watchlist_tools import WATCHLIST_TOOLS
from core.agent.tools.research_tools import RESEARCH_TOOLS
from core.agent.tools.forecast_tools import FORECAST_TOOLS
from core.agent.tools.personality_tools import PERSONALITY_TOOLS
from core.agent.tools.ensemble_tools import ENSEMBLE_TOOLS
from core.agent.tools.sentiment_tools import SENTIMENT_TOOLS

# query_grok is disabled — it drives Playwright/Chromium which is blocked
# on some client machines and crashes the app when invoked. Keep the
# module on disk so tests and historical docs still import, but don't
# register it with the agent.


#: Every tool the agent sees this phase.
ALL_TOOLS: List[Any] = [
    *BROKER_TOOLS,
    *MARKET_TOOLS,
    *MARKET_HOURS_TOOLS,
    *RISK_TOOLS,
    *MEMORY_TOOLS,
    *WATCHLIST_TOOLS,
    *NEWS_TOOLS,
    *SOCIAL_TOOLS,
    *BROWSER_TOOLS,
    *BACKTEST_TOOLS,
    *INDICATOR_TOOLS,
    *STRATEGY_BACKTEST_TOOLS,
    *PERFORMANCE_TOOLS,
    *RESEARCH_TOOLS,
    *FLOW_TOOLS,
    *FORECAST_TOOLS,
    *ENSEMBLE_TOOLS,
    *SENTIMENT_TOOLS,
    *PERSONALITY_TOOLS,
]


#: MCP server name — referenced by the allowed_tools list as "mcp__blank__*".
SERVER_NAME: str = "blank"


def build_mcp_server() -> Any:
    """Register every tool against a fresh in-process MCP server."""
    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="0.1.0",
        tools=ALL_TOOLS,
    )


def allowed_tool_names() -> List[str]:
    """The ``allowed_tools`` list the runner passes to agent options.

    The agent SDK expects tool names prefixed as ``mcp__<server>__<tool>``.
    Each decorated tool exposes its name under ``.name``.
    """
    names: List[str] = []
    for t in ALL_TOOLS:
        tool_name = getattr(t, "name", None)
        if tool_name is None:
            # Fallback for older SDK versions that stash it on __name__
            tool_name = getattr(t, "__name__", "")
        if tool_name:
            names.append(f"mcp__{SERVER_NAME}__{tool_name}")
    return names
