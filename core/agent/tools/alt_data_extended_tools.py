"""Extended alt-data MCP tools:

  get_institutional_holders — SEC EDGAR 13F: which institutions hold this stock
  get_earnings_whisper      — EarningsWhispers: next earnings date + whisper EPS
  get_insider_cluster_summary — OpenInsider: clustered buy/sell activity summary

All three sources are no-key or scrape-based. Each checks the relevant
config flag under alt_data.{source}.enabled before proceeding.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "get_institutional_holders",
    "Find institutions that recently filed 13F-HR reports with the SEC mentioning *ticker*. "
    "Uses EDGAR full-text search — each result is an institution whose quarterly 13F "
    "filing contains this ticker, confirming large-money exposure. "
    "Returns deduplicated institution names, filing dates, and reporting periods. "
    "High count of recent new filers = growing institutional conviction. "
    "*lookback_days* defaults to 90 (the standard quarterly reporting cycle). "
    "No API key required. Requires alt_data.sec_edgar.enabled: true.",
    {"ticker": str, "lookback_days": int},
)
async def get_institutional_holders(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    lookback = max(30, min(365, int(args.get("lookback_days", 90) or 90)))
    ctx = get_agent_context()
    cfg = ctx.config.get("alt_data", {}).get("sec_edgar", {})
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.sec_edgar is disabled",
            "fix": "set alt_data.sec_edgar.enabled to true in config.json (no API key needed)",
        })
    from core.alt_data.sec_edgar import institutional_holders
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(institutional_holders(ticker, lookback_days=lookback, ttl=ttl))


@tool(
    "get_earnings_whisper",
    "Fetch the next earnings date and EPS estimates for *ticker* from EarningsWhispers. "
    "Returns the 'whisper number' (the unofficial street consensus, often more accurate "
    "than published estimates), consensus EPS, and revenue estimate where available. "
    "A stock priced above the whisper number heading into earnings carries beat-in risk; "
    "below it carries negative-surprise risk. "
    "Falls back to yfinance calendar data if the EarningsWhispers scrape fails. "
    "No API key required. Requires alt_data.earnings_whispers.enabled: true.",
    {"ticker": str},
)
async def get_earnings_whisper(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = ctx.config.get("alt_data", {}).get("earnings_whispers", {})
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.earnings_whispers is disabled",
            "fix": "set alt_data.earnings_whispers.enabled to true in config.json (no API key needed)",
        })
    from core.alt_data.earnings_whispers import earnings_estimate
    ttl = int(cfg.get("cache_ttl_seconds", 1800))
    return _text_result(earnings_estimate(ticker, ttl=ttl))


@tool(
    "get_insider_cluster_summary",
    "Scrape OpenInsider for recent open-market insider transactions on *ticker*. "
    "Returns buy vs sell count, total dollar value bought and sold, net bias "
    "(buy-heavy / sell-heavy / no_activity), and the top 5 insiders by transaction value. "
    "Only open-market purchases (P) and sales (S) are counted — awards and option "
    "exercises are excluded as they carry different signal quality. "
    "Clusters of insider purchases by multiple C-suite insiders at similar price levels "
    "are historically one of the strongest near-term upside signals. "
    "No API key required. Requires alt_data.open_insider.enabled: true.",
    {"ticker": str},
)
async def get_insider_cluster_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = ctx.config.get("alt_data", {}).get("open_insider", {})
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.open_insider is disabled",
            "fix": "set alt_data.open_insider.enabled to true in config.json (no API key needed)",
        })
    from core.alt_data.open_insider import insider_activity
    ttl = int(cfg.get("cache_ttl_seconds", 1800))
    return _text_result(insider_activity(ticker, ttl=ttl))


ALT_DATA_EXTENDED_TOOLS = [
    get_institutional_holders,
    get_earnings_whisper,
    get_insider_cluster_summary,
]
