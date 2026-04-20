"""Integration: every alt-data MCP tool is registered with the MCP server."""
from __future__ import annotations

from core.agent.mcp_server import allowed_tool_names

EXPECTED_ALT_DATA_TOOLS = {
    # fundamentals_tools
    "get_company_overview",
    "get_earnings_history",
    "get_financial_ratios",
    "get_dcf_value",
    "get_analyst_price_targets",
    # macro_tools
    "get_macro_snapshot",
    "get_fred_series",
    # news_api_tools
    "get_structured_news",
    # alt_data_extended_tools
    "get_institutional_holders",
    "get_earnings_whisper",
    "get_insider_cluster_summary",
}


def test_all_alt_data_tools_registered() -> None:
    names = set(allowed_tool_names())
    short = {n.rsplit("__", 1)[-1] for n in names}
    missing = EXPECTED_ALT_DATA_TOOLS - short
    assert not missing, f"missing alt-data tools: {missing}"
