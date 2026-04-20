"""FRED (St. Louis Fed) API client — macroeconomic series data.

Free tier: unlimited requests with a registered key.
Env var: FRED_KEY  (register free at fred.stlouisfed.org/docs/api/api_key.html)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_API_KEY_ENV = "FRED_KEY"
_BASE = "https://api.stlouisfed.org/fred"

# Series IDs used in the macro snapshot
_SNAPSHOT_SERIES: Dict[str, str] = {
    "fed_funds_rate": "FEDFUNDS",
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "yield_spread_10y2y": "T10Y2Y",
    "cpi": "CPIAUCSL",       # All Urban, seasonally adjusted — needs 14 obs for YoY
    "core_pce": "PCEPILFE",  # Core PCE price index
    "unemployment": "UNRATE",
}


def _key() -> str:
    return os.getenv(_API_KEY_ENV, "")


def series_observations(series_id: str, limit: int = 5, ttl: int = 3600) -> Dict[str, Any]:
    """Fetch the most recent *limit* non-missing observations for a FRED series."""
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = f"fred_{series_id}_{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        resp = requests.get(
            f"{_BASE}/series/observations",
            params={
                "series_id": series_id,
                "api_key": _key(),
                "file_type": "json",
                "limit": str(limit),
                "sort_order": "desc",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error_message" in data:
            return {"error": data["error_message"]}
        obs: List[Dict[str, str]] = [
            {"date": o["date"], "value": o["value"]}
            for o in (data.get("observations") or [])
            if o.get("value") not in (".", "")
        ]
        result: Dict[str, Any] = {"series_id": series_id, "observations": obs}
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("fred: series_observations(%s) failed: %s", series_id, exc)
        return {"error": str(exc)}


def macro_snapshot(ttl: int = 3600) -> Dict[str, Any]:
    """Return current values for key macro indicators in one aggregated call.

    CPI is returned with a year-on-year percentage change computed from
    14 monthly observations. An inverted yield spread signals recession risk.
    """
    if not _key():
        return {"error": f"{_API_KEY_ENV} not configured"}
    cache_key = "fred_macro_snapshot"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    result: Dict[str, Any] = {}
    for label, sid in _SNAPSHOT_SERIES.items():
        n = 14 if sid == "CPIAUCSL" else 2
        data = series_observations(sid, limit=n, ttl=ttl)
        if "error" in data:
            result[label] = {"error": data["error"]}
            continue
        obs = data.get("observations", [])
        if not obs:
            result[label] = None
            continue
        if sid == "CPIAUCSL" and len(obs) >= 13:
            try:
                latest = float(obs[0]["value"])
                year_ago = float(obs[12]["value"])
                result[label] = {
                    "value": latest,
                    "yoy_pct": round((latest / year_ago - 1) * 100, 2),
                    "date": obs[0]["date"],
                }
            except Exception:
                result[label] = {"value": obs[0]["value"], "date": obs[0]["date"]}
        else:
            result[label] = {"value": obs[0]["value"], "date": obs[0]["date"]}

    # Derive yield curve shape from spread
    spread = result.get("yield_spread_10y2y", {})
    if isinstance(spread, dict) and "value" in spread:
        try:
            result["yield_curve"] = "inverted" if float(spread["value"]) < 0 else "normal"
        except Exception:
            pass

    _cache.put(cache_key, result, ttl)
    return result
