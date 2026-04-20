"""Alpha Vantage client — company fundamentals and earnings data.

Free tier: 25 requests/day (standard free key).
Rate limit: 5 requests/minute — cache aggressively.
Env var: ALPHA_VANTAGE_KEY
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_API_KEY_ENV = "ALPHA_VANTAGE_KEY"
_BASE = "https://www.alphavantage.co/query"


def _key() -> str:
    return os.getenv(_API_KEY_ENV, "")


def _get(params: Dict[str, str], timeout: float = 15.0) -> Dict[str, Any]:
    p = dict(params)
    p["apikey"] = _key()
    resp = requests.get(_BASE, params=p, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # AV signals quota exhaustion via top-level "Note" or "Information" keys
    if "Note" in data or "Information" in data:
        msg = data.get("Note") or data.get("Information", "quota/error")
        raise RuntimeError(f"Alpha Vantage: {msg}")
    return data


def company_overview(ticker: str, ttl: int = 3600) -> Dict[str, Any]:
    """Return fundamental snapshot from AV OVERVIEW endpoint."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"av_overview_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = _get({"function": "OVERVIEW", "symbol": ticker.upper()})
        if not raw or "Symbol" not in raw:
            return {"error": f"no overview data for {ticker}"}
        result: Dict[str, Any] = {
            "ticker": raw.get("Symbol"),
            "name": raw.get("Name"),
            "sector": raw.get("Sector"),
            "industry": raw.get("Industry"),
            "market_cap": raw.get("MarketCapitalization"),
            "pe_ratio": raw.get("PERatio"),
            "forward_pe": raw.get("ForwardPE"),
            "peg_ratio": raw.get("PEGRatio"),
            "pb_ratio": raw.get("PriceToBookRatio"),
            "ps_ratio": raw.get("PriceToSalesRatioTTM"),
            "eps": raw.get("EPS"),
            "eps_diluted": raw.get("DilutedEPSTTM"),
            "dividend_yield": raw.get("DividendYield"),
            "payout_ratio": raw.get("PayoutRatio"),
            "52w_high": raw.get("52WeekHigh"),
            "52w_low": raw.get("52WeekLow"),
            "50d_ma": raw.get("50DayMovingAverage"),
            "200d_ma": raw.get("200DayMovingAverage"),
            "beta": raw.get("Beta"),
            "roe": raw.get("ReturnOnEquityTTM"),
            "roa": raw.get("ReturnOnAssetsTTM"),
            "profit_margin": raw.get("ProfitMargin"),
            "operating_margin": raw.get("OperatingMarginTTM"),
            "revenue_ttm": raw.get("RevenueTTM"),
            "gross_profit_ttm": raw.get("GrossProfitTTM"),
            "ebitda": raw.get("EBITDA"),
            "analyst_target": raw.get("AnalystTargetPrice"),
            "shares_outstanding": raw.get("SharesOutstanding"),
            "float_shares": raw.get("SharesFloat"),
            "description": raw.get("Description"),
        }
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("alpha_vantage: company_overview(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}


def earnings_history(ticker: str, ttl: int = 3600) -> Dict[str, Any]:
    """Return last 8 quarters of EPS actuals, estimates, and surprise."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"av_earnings_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = _get({"function": "EARNINGS", "symbol": ticker.upper()})
        quarterly: List[Dict[str, Any]] = []
        for row in (raw.get("quarterlyEarnings") or [])[:8]:
            quarterly.append({
                "period": row.get("fiscalDateEnding"),
                "reported_date": row.get("reportedDate"),
                "reported_eps": row.get("reportedEPS"),
                "estimated_eps": row.get("estimatedEPS"),
                "surprise": row.get("surprise"),
                "surprise_pct": row.get("surprisePercentage"),
            })
        result: Dict[str, Any] = {"ticker": ticker.upper(), "quarterly": quarterly}
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("alpha_vantage: earnings_history(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}
