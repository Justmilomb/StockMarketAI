"""Insider trading + unusual options-activity MCP tools."""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.scrapers.options_flow import unusual_activity
from core.scrapers.sec_insider import fetch_form4


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "recent_insider_trades",
    "Pull the most recent SEC Form 4 insider-trading filings for *ticker* "
    "from EDGAR's Atom feed. Use this to spot institutional front-running: "
    "large clusters of insider buys before a catalyst are historically a "
    "strong bullish signal.\n\nReturns list of {title, filing_date, url, "
    "summary}. Does NOT attempt to parse transaction size — the agent "
    "should follow the URL if it needs dollar figures.",
    {"ticker": str},
)
async def recent_insider_trades(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    filings = fetch_form4(ticker)
    return _text_result({
        "ticker": ticker,
        "filings": filings[:15],
        "count": len(filings),
    })


@tool(
    "unusual_options_activity",
    "Scan the public option chain for *ticker* and flag strikes with "
    "volume > 3x open interest and absolute volume >= 200 contracts. "
    "Bullish interpretation: large call sweeps on OTM strikes suggest "
    "institutional positioning ahead of a catalyst. Bearish: same rule "
    "on puts.\n\nReturns up to 20 hits sorted by vol/OI ratio descending.",
    {"ticker": str},
)
async def unusual_options_activity_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    hits = unusual_activity(ticker)
    bullish_calls = sum(1 for h in hits if h["side"] == "call")
    bearish_puts = sum(1 for h in hits if h["side"] == "put")
    if bullish_calls > bearish_puts:
        bias = "bullish"
    elif bearish_puts > bullish_calls:
        bias = "bearish"
    else:
        bias = "neutral"
    return _text_result({
        "ticker": ticker,
        "hits": hits,
        "bullish_calls": bullish_calls,
        "bearish_puts": bearish_puts,
        "net_bias": bias,
    })


INSIDER_TOOLS = [recent_insider_trades, unusual_options_activity_tool]
