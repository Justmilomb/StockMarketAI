"""Fundamental valuation MCP tools.

Provides four tools backed by Alpha Vantage (company overview + earnings
history) and Financial Modeling Prep (financial ratios + DCF valuation).

Each tool checks the relevant config flag before calling the API client,
and returns a clear error if the source is disabled or the key is missing.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _av_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("alt_data", {}).get("alpha_vantage", {})


def _fmp_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("alt_data", {}).get("fmp", {})


@tool(
    "get_company_overview",
    "Fetch a comprehensive fundamental snapshot for *ticker* from Alpha Vantage: "
    "market cap, P/E, forward P/E, PEG, P/B, P/S, EPS, dividend yield, payout ratio, "
    "52-week high/low, 50/200-day moving averages, beta, ROE, ROA, profit margin, "
    "operating margin, TTM revenue, EBITDA, analyst target price, shares outstanding, "
    "sector, and a company description. "
    "Use this for fundamental context before sizing a position or making a buy/sell decision. "
    "Requires ALPHA_VANTAGE_KEY env var and alt_data.alpha_vantage.enabled: true.",
    {"ticker": str},
)
async def get_company_overview(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = _av_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.alpha_vantage is disabled",
            "fix": "set alt_data.alpha_vantage.enabled to true in config.json and set ALPHA_VANTAGE_KEY",
        })
    from core.alt_data.alpha_vantage import company_overview
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(company_overview(ticker, ttl=ttl))


@tool(
    "get_earnings_history",
    "Fetch the last 8 quarters of EPS actuals vs estimates for *ticker* from Alpha Vantage. "
    "Each row contains: fiscal period, report date, reported EPS, estimated EPS, "
    "surprise amount, and surprise percentage. "
    "A consistent record of large positive surprises signals management credibility "
    "and analyst under-estimation — both bullish predictors of post-earnings drift. "
    "Requires ALPHA_VANTAGE_KEY env var and alt_data.alpha_vantage.enabled: true.",
    {"ticker": str},
)
async def get_earnings_history(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = _av_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({"error": "alt_data.alpha_vantage is disabled"})
    from core.alt_data.alpha_vantage import earnings_history
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(earnings_history(ticker, ttl=ttl))


@tool(
    "get_financial_ratios",
    "Fetch trailing-twelve-month financial ratios for *ticker* from Financial Modeling Prep: "
    "P/E, P/B, P/S, P/FCF, EV/EBITDA, ROE, ROA, ROIC, gross/operating/net margins, "
    "current ratio, quick ratio, debt/equity, interest coverage, dividend yield, payout ratio. "
    "Compare against sector peers to identify cheap or expensive valuations. "
    "High debt/equity + low interest coverage = fragile balance sheet risk. "
    "Requires FMP_KEY env var and alt_data.fmp.enabled: true.",
    {"ticker": str},
)
async def get_financial_ratios(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = _fmp_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.fmp is disabled",
            "fix": "set alt_data.fmp.enabled to true in config.json and set FMP_KEY",
        })
    from core.alt_data.fmp import financial_ratios
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(financial_ratios(ticker, ttl=ttl))


@tool(
    "get_dcf_value",
    "Fetch a DCF (discounted cash flow) intrinsic value estimate for *ticker* from "
    "Financial Modeling Prep. Returns the DCF estimate, current stock price, and "
    "implied upside/downside percentage. "
    "A large positive upside_pct suggests undervaluation; negative suggests overvaluation. "
    "FMP uses a simplified 10-year free-cash-flow model — treat as one data point "
    "alongside P/E, P/B, and analyst targets, not as definitive fair value. "
    "Requires FMP_KEY env var and alt_data.fmp.enabled: true.",
    {"ticker": str},
)
async def get_dcf_value(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})
    ctx = get_agent_context()
    cfg = _fmp_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({"error": "alt_data.fmp is disabled"})
    from core.alt_data.fmp import dcf_value
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(dcf_value(ticker, ttl=ttl))


FUNDAMENTALS_TOOLS = [
    get_company_overview,
    get_earnings_history,
    get_financial_ratios,
    get_dcf_value,
]
