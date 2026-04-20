"""OpenInsider scraper — insider trading cluster summaries.

No key required. Scrapes openinsider.com/search?q={ticker}.
Parses the transaction table for open-market purchases (P) and sales (S)
and returns aggregated buy/sell counts, dollar values, net bias, and the
top 5 insiders by total transaction value.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import requests

from core.alt_data import _cache

logger = logging.getLogger(__name__)

_BASE = "https://openinsider.com/search"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

_RE_ROWS = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_RE_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_MONEY = re.compile(r"[\$,+]")

# OpenInsider table column offsets (0-based, after stripping the leading
# checkbox/icon <td> that every data row starts with).
# Actual columns: [icon] filing_date trade_date ticker company insider title type price qty owned delta value
_COL_FILING = 1
_COL_TRADE = 2
_COL_INSIDER = 5
_COL_TITLE = 6
_COL_TYPE = 7
_COL_PRICE = 8
_COL_QTY = 9
_COL_VALUE = 12


def _strip(html: str) -> str:
    return _RE_TAGS.sub("", html).strip()


def _parse_dollar(s: str) -> float:
    cleaned = _RE_MONEY.sub("", s).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def insider_activity(ticker: str, ttl: int = 1800) -> Dict[str, Any]:
    """Return a cluster summary of recent insider transactions for *ticker*.

    Filters to open-market purchases (P) and sales (S) only — awards,
    option exercises, and dispositions are excluded as they carry different
    signal value.
    """
    cache_key = f"oi_{ticker.upper()}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            _BASE,
            params={"q": ticker.upper()},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        logger.info("open_insider: fetch(%s) failed: %s", ticker, exc)
        return {"error": str(exc)}

    transactions: List[Dict[str, Any]] = []
    for row_html in _RE_ROWS.findall(html):
        cells = [_strip(td) for td in _RE_TD.findall(row_html)]
        if len(cells) < 13:
            continue
        trade_type = cells[_COL_TYPE]
        if "Purchase" not in trade_type and "Sale" not in trade_type:
            continue
        try:
            transactions.append({
                "filing_date": cells[_COL_FILING],
                "trade_date": cells[_COL_TRADE],
                "insider": cells[_COL_INSIDER],
                "title": cells[_COL_TITLE],
                "type": "buy" if "Purchase" in trade_type else "sell",
                "price": cells[_COL_PRICE],
                "qty": cells[_COL_QTY],
                "value": cells[_COL_VALUE],
                "value_num": _parse_dollar(cells[_COL_VALUE]),
            })
        except IndexError:
            continue

    buys = [t for t in transactions if t["type"] == "buy"]
    sells = [t for t in transactions if t["type"] == "sell"]
    total_buy = sum(t["value_num"] for t in buys)
    total_sell = sum(t["value_num"] for t in sells)

    insider_totals: Dict[str, float] = {}
    for t in transactions:
        name = t["insider"]
        insider_totals[name] = insider_totals.get(name, 0.0) + t["value_num"]
    top = sorted(insider_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    if total_buy == total_sell == 0.0:
        net_bias = "no_activity"
    else:
        net_bias = "buy-heavy" if total_buy > total_sell else "sell-heavy"

    result: Dict[str, Any] = {
        "ticker": ticker.upper(),
        "total_transactions": len(transactions),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_buy_value_usd": round(total_buy),
        "total_sell_value_usd": round(total_sell),
        "net_bias": net_bias,
        "top_insiders": [
            {"name": n, "total_value_usd": round(v)} for n, v in top
        ],
        "recent_transactions": transactions[:20],
    }
    if not transactions:
        result["note"] = "no open-market buy/sell transactions found"

    _cache.put(cache_key, result, ttl)
    return result
