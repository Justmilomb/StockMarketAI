"""EarningsWhispers scraper — next earnings date and whisper/consensus EPS.

No key required. Scrapes earningswhispers.com with a browser User-Agent.
The site is partially JS-rendered; we extract what's in the initial HTML
response and fall back to yfinance calendar when the scrape yields nothing.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_BASE = "https://www.earningswhispers.com/stocks"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_RE_DATE = re.compile(
    r'(?:earnings.date|epsdate|id="[^"]*date[^"]*")[^>]*>\s*'
    r'([A-Za-z]+\.?\s+\d{1,2},?\s*\d{4})',
    re.IGNORECASE,
)
_RE_WHISPER = re.compile(
    r'(?:epswhisper|whisper.eps|id="eps")[^>]*>\s*\$?([-\d.]+)',
    re.IGNORECASE,
)
_RE_CONSENSUS = re.compile(
    r'(?:consensus|wallstreet|epsestimate|eps.estimate)[^>]*>\s*\$?([-\d.]+)',
    re.IGNORECASE,
)
_RE_REVENUE = re.compile(
    r'(?:rev(?:enue)?.{0,20}estimate|revest)[^>]*>\s*\$?([\d.,]+\s*[BbMmKk]?)',
    re.IGNORECASE,
)


def _yf_fallback(ticker: str) -> Dict[str, Any]:
    """Return yfinance calendar data as fallback."""
    try:
        import yfinance as yf  # type: ignore
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        if cal is None:
            return {}
        if hasattr(cal, "to_dict"):
            cal = cal.to_dict()
        if not isinstance(cal, dict):
            return {}
        return {str(k).lower().replace(" ", "_"): v for k, v in cal.items()}
    except Exception:
        return {}


def earnings_estimate(ticker: str, ttl: int = 1800) -> Dict[str, Any]:
    """Fetch earnings date and EPS estimates for *ticker*.

    Tries EarningsWhispers first; falls back to yfinance calendar.
    """
    cache_key = f"ew_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    result: Dict[str, Any] = {"ticker": ticker.upper()}
    scraped_any = False

    try:
        resp = requests.get(
            f"{_BASE}/{ticker.lower()}",
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text

        m = _RE_DATE.search(html)
        if m:
            result["earnings_date"] = m.group(1).strip()
            scraped_any = True
        m = _RE_WHISPER.search(html)
        if m:
            result["whisper_eps"] = m.group(1).strip()
            scraped_any = True
        m = _RE_CONSENSUS.search(html)
        if m:
            result["consensus_eps"] = m.group(1).strip()
        m = _RE_REVENUE.search(html)
        if m:
            result["revenue_estimate"] = m.group(1).strip()
        result["source"] = "earningswhispers"
    except Exception as exc:
        logger.info("earnings_whispers: scrape(%s) failed: %s", ticker, exc)

    if not scraped_any:
        yf_data = _yf_fallback(ticker)
        if yf_data:
            result.update(yf_data)
            result.setdefault("source", "yfinance")

    if len(result) <= 1:
        result["error"] = "no earnings data available"

    _cache.put(cache_key, result, ttl)
    return result
