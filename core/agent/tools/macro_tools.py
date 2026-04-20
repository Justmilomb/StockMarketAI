"""Macroeconomic MCP tools — FRED economic series data.

Two tools: a curated macro snapshot (rates, inflation, yield curve) and
a raw series lookup for any FRED series by ID.

Requires FRED_KEY env var and alt_data.fred.enabled: true in config.json.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _fred_cfg(config: Dict[str, Any]) -> Dict[str, Any]:
    return config.get("alt_data", {}).get("fred", {})


@tool(
    "get_macro_snapshot",
    "Fetch a current macroeconomic regime snapshot from FRED: Federal Funds Rate, "
    "10-Year and 2-Year Treasury yields, 10Y-2Y yield spread (negative = inverted = "
    "recession signal), CPI year-on-year inflation, core PCE inflation, and unemployment rate. "
    "Use this at the start of each session to calibrate risk appetite: "
    "inverted curve + rising CPI + high unemployment = strongly defensive posture; "
    "steep curve + falling inflation + low unemployment = risk-on environment. "
    "Requires FRED_KEY env var and alt_data.fred.enabled: true.",
    {},
)
async def get_macro_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    cfg = _fred_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({
            "error": "alt_data.fred is disabled",
            "fix": "set alt_data.fred.enabled to true in config.json and set FRED_KEY",
        })
    from core.alt_data.fred import macro_snapshot
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(macro_snapshot(ttl=ttl))


@tool(
    "get_fred_series",
    "Fetch the most recent *limit* observations from a specific FRED data series. "
    "Common series IDs: FEDFUNDS (Fed Funds Rate), DGS10 (10Y Treasury), DGS2 (2Y Treasury), "
    "T10Y2Y (10Y-2Y spread), CPIAUCSL (CPI headline), UNRATE (unemployment), "
    "GDP (quarterly GDP), BAMLH0A0HYM2 (HY credit spread), VIXCLS (VIX). "
    "Full catalogue at fred.stlouisfed.org. *limit* is capped at 100. "
    "Requires FRED_KEY env var and alt_data.fred.enabled: true.",
    {"series_id": str, "limit": int},
)
async def get_fred_series(args: Dict[str, Any]) -> Dict[str, Any]:
    series_id = str(args.get("series_id", "")).strip().upper()
    if not series_id:
        return _text_result({"error": "series_id is required"})
    limit = max(1, min(100, int(args.get("limit", 10) or 10)))
    ctx = get_agent_context()
    cfg = _fred_cfg(ctx.config)
    if not cfg.get("enabled", False):
        return _text_result({"error": "alt_data.fred is disabled"})
    from core.alt_data.fred import series_observations
    ttl = int(cfg.get("cache_ttl_seconds", 3600))
    return _text_result(series_observations(series_id, limit=limit, ttl=ttl))


MACRO_TOOLS = [get_macro_snapshot, get_fred_series]
