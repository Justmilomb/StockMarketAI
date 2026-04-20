"""SEC EDGAR client — institutional 13F holder discovery.

No API key required. Uses EDGAR's full-text search API to find 13F-HR
filings that mention a given ticker, returning the filing entity names
(institutional holders) and filing metadata.

Note: this surface gives you *who holds the stock*, not *how many shares*.
Parsing exact share counts requires fetching and parsing the filing's XML
primary document — that's out of scope here.

SEC requires a descriptive, contact-bearing User-Agent for programmatic access.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_USER_AGENT = "Blank Research contact@certifiedrandom.com"
_EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"


def institutional_holders(
    ticker: str,
    lookback_days: int = 90,
    ttl: int = 3600,
) -> Dict[str, Any]:
    """Find institutions that recently filed 13F-HR reports mentioning *ticker*.

    Uses EDGAR full-text search — institutions whose 13F filing text contains
    the ticker symbol are likely holders. Returns deduplicated entity names,
    filing dates, and reporting periods for up to 30 institutions.
    """
    cache_key = f"edgar_13f_{ticker.upper()}_{lookback_days}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            _EFTS_BASE,
            params={
                "q": f'"{ticker.upper()}"',
                "forms": "13F-HR",
                "dateRange": "custom",
                "startdt": cutoff,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        hits: List[Dict[str, Any]] = (data.get("hits") or {}).get("hits") or []
        institutions: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for hit in hits[:50]:
            src = hit.get("_source", {})
            name = src.get("entity_name", "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            institutions.append({
                "institution": name,
                "file_date": src.get("file_date"),
                "period": src.get("period_of_report"),
            })
        total = (data.get("hits") or {}).get("total", {})
        if isinstance(total, dict):
            total_count = total.get("value", 0)
        else:
            total_count = int(total or 0)
        result: Dict[str, Any] = {
            "ticker": ticker.upper(),
            "lookback_days": lookback_days,
            "institutions_found": len(institutions),
            "total_13f_filings": total_count,
            "institutions": institutions[:30],
        }
        _cache.put(cache_key, result, ttl)
        return result
    except Exception as exc:
        logger.info("sec_edgar: institutional_holders(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}
