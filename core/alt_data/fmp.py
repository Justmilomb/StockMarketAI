"""Financial Modeling Prep client — financial ratios, DCF, analyst targets.

Free tier: 250 requests/day.
Env var: FMP_KEY
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_API_KEY_ENV = "FMP_KEY"
_BASE = "https://financialmodelingprep.com/api/v3"


def _key() -> str:
    return os.getenv(_API_KEY_ENV, "")


def _get(path: str, params: Optional[Dict[str, str]] = None, timeout: float = 15.0) -> Any:
    url = f"{_BASE}/{path}"
    p: Dict[str, str] = {"apikey": _key()}
    if params:
        p.update(params)
    resp = requests.get(url, params=p, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def financial_ratios(ticker: str, ttl: int = 3600) -> Dict[str, Any]:
    """Return trailing-twelve-month ratios: P/E, ROE, margins, leverage, etc."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"fmp_ratios_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = _get(f"ratios-ttm/{ticker.upper()}")
        if not data or not isinstance(data, list):
            return {"error": f"no ratio data for {ticker}"}
        r = data[0]
        result: Dict[str, Any] = {
            "ticker": ticker.upper(),
            "pe_ratio": r.get("peRatioTTM"),
            "price_to_book": r.get("priceToBookRatioTTM"),
            "price_to_sales": r.get("priceToSalesRatioTTM"),
            "price_to_fcf": r.get("priceToFreeCashFlowsTTM"),
            "ev_to_ebitda": r.get("enterpriseValueMultipleTTM"),
            "roe": r.get("returnOnEquityTTM"),
            "roa": r.get("returnOnAssetsTTM"),
            "roic": r.get("returnOnCapitalEmployedTTM"),
            "gross_margin": r.get("grossProfitMarginTTM"),
            "operating_margin": r.get("operatingProfitMarginTTM"),
            "net_margin": r.get("netProfitMarginTTM"),
            "current_ratio": r.get("currentRatioTTM"),
            "quick_ratio": r.get("quickRatioTTM"),
            "debt_to_equity": r.get("debtEquityRatioTTM"),
            "interest_coverage": r.get("interestCoverageTTM"),
            "dividend_yield": r.get("dividendYieldTTM"),
            "payout_ratio": r.get("payoutRatioTTM"),
        }
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("fmp: financial_ratios(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}


def dcf_value(ticker: str, ttl: int = 3600) -> Dict[str, Any]:
    """Return FMP's DCF intrinsic value + implied upside/downside vs current price."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"fmp_dcf_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = _get(f"discounted-cash-flow/{ticker.upper()}")
        if not data or not isinstance(data, list):
            return {"error": f"no DCF data for {ticker}"}
        d = data[0]
        result: Dict[str, Any] = {
            "ticker": ticker.upper(),
            "date": d.get("date"),
            "stock_price": d.get("stockPrice"),
            "dcf_value": d.get("dcf"),
        }
        price = d.get("stockPrice")
        dcf = d.get("dcf")
        if price and dcf:
            try:
                result["upside_pct"] = round((float(dcf) / float(price) - 1) * 100, 1)
            except Exception:
                pass
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("fmp: dcf_value(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}


def analyst_targets(ticker: str, ttl: int = 3600) -> Dict[str, Any]:
    """Return analyst consensus price target (high / low / median / mean)."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"fmp_targets_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        data = _get(f"price-target-consensus/{ticker.upper()}")
        if not data or not isinstance(data, list):
            return {"error": f"no analyst target data for {ticker}"}
        d = data[0]
        result: Dict[str, Any] = {
            "ticker": ticker.upper(),
            "target_consensus": d.get("targetConsensus"),
            "target_high": d.get("targetHigh"),
            "target_low": d.get("targetLow"),
            "target_median": d.get("targetMedian"),
        }
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("fmp: analyst_targets(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}
