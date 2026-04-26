"""Order book / Level 2 tools.

Surfaces best bid / ask, sizes, and (when an L2 source is available)
depth so the agent can read where buy/sell walls sit before committing
to a trade.

Provider behaviour:

* **FMP active** — FMP's quote endpoint exposes ``bid``, ``ask``,
  ``bidSize`` and ``askSize`` (L1 only — no public depth feed). We mark
  ``depth_available: false`` so the agent treats walls as estimates.
* **yfinance fallback** — ``yf.Ticker.fast_info`` and ``info`` give
  the same L1 fields. Same caveat applies.

Both paths return a uniform JSON shape so the agent can write rules
once and not branch on provider.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(payload: Dict[str, Any]) -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, ?)",
                (
                    ctx.iteration_id, "get_order_book",
                    json.dumps(payload, default=str), "order_book",
                ),
            )
    except Exception:
        pass


def _normalise_pence(ticker: str, value: Optional[float]) -> Optional[float]:
    """Convert pence-quoted LSE prices to pounds."""
    if value is None or value <= 0:
        return value
    try:
        from fx import is_pence_quoted
        if is_pence_quoted(ticker):
            return float(value) / 100.0
    except Exception:
        pass
    return float(value)


def _yfinance_book(ticker: str) -> Dict[str, Any]:
    """Best-effort L1 quote via yfinance.

    ``fast_info`` is cheaper than ``info`` and is the recommended path
    in current yfinance, but it lacks bid/ask sizes — fall back to
    ``info`` for those when available.
    """
    try:
        import yfinance as yf
    except Exception as e:
        return {"error": f"yfinance unavailable: {e}"}

    try:
        t = yf.Ticker(ticker)
    except Exception as e:
        return {"error": f"yfinance ticker error: {e}"}

    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None

    try:
        fi = t.fast_info
        bid = float(getattr(fi, "bid", None) or 0.0) or None
        ask = float(getattr(fi, "ask", None) or 0.0) or None
        last = float(getattr(fi, "last_price", None) or 0.0) or None
    except Exception:
        pass

    if not bid or not ask:
        try:
            info = t.info or {}
            bid = bid or float(info.get("bid") or 0.0) or None
            ask = ask or float(info.get("ask") or 0.0) or None
            last = last or float(info.get("regularMarketPrice") or 0.0) or None
            bid_size = float(info.get("bidSize") or 0.0) or None
            ask_size = float(info.get("askSize") or 0.0) or None
        except Exception:
            pass
    else:
        try:
            info = t.info or {}
            bid_size = float(info.get("bidSize") or 0.0) or None
            ask_size = float(info.get("askSize") or 0.0) or None
        except Exception:
            pass

    bid = _normalise_pence(ticker, bid)
    ask = _normalise_pence(ticker, ask)
    last = _normalise_pence(ticker, last)

    spread = (ask - bid) if (bid and ask and ask > bid) else None
    mid = ((bid + ask) / 2.0) if (bid and ask) else None
    spread_pct = (spread / mid * 100.0) if (spread and mid and mid > 0) else None

    return {
        "source": "yfinance_l1",
        "best_bid": bid,
        "best_ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "last_price": last,
        "spread": spread,
        "mid": mid,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "depth_available": False,
        "depth": [],
    }


def _fmp_book(ticker: str) -> Dict[str, Any]:
    """L1 quote via the FMP provider (only reachable when FMP is active)."""
    try:
        from core.data import get_provider
        provider = get_provider()
    except Exception as e:
        return {"error": f"fmp provider error: {e}"}

    if getattr(provider, "name", "") != "fmp":
        return {"error": "fmp provider not active"}

    try:
        live = provider.fetch_live_prices([ticker]) or {}
        row = live.get(ticker, {}) or {}
    except Exception as e:
        return {"error": f"fmp fetch error: {e}"}

    bid = float(row.get("bid") or 0.0) or None
    ask = float(row.get("ask") or 0.0) or None
    last = float(row.get("price") or 0.0) or None
    bid_size = float(row.get("bidSize") or 0.0) or None
    ask_size = float(row.get("askSize") or 0.0) or None

    spread = (ask - bid) if (bid and ask and ask > bid) else None
    mid = ((bid + ask) / 2.0) if (bid and ask) else None
    spread_pct = (spread / mid * 100.0) if (spread and mid and mid > 0) else None

    return {
        "source": "fmp_l1",
        "best_bid": bid,
        "best_ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "last_price": last,
        "spread": spread,
        "mid": mid,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "depth_available": False,
        "depth": [],
    }


@tool(
    "get_order_book",
    "Return best bid / ask, sizes, spread and (when available) order-"
    "book depth for a ticker. When FMP is the active data provider, "
    "uses its L1 quote endpoint; otherwise falls back to yfinance. "
    "Both paths return ``depth_available: false`` for now — wire L2 "
    "later when an exchange-grade feed is configured. Use ``spread_"
    "pct`` to spot wide-spread tickers where market orders cost more "
    "than the agent's expected edge.",
    {"ticker": str},
)
async def get_order_book(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    book: Dict[str, Any]
    fmp = _fmp_book(ticker)
    if fmp and "error" not in fmp and (fmp.get("best_bid") or fmp.get("best_ask")):
        book = fmp
    else:
        book = _yfinance_book(ticker)

    book["ticker"] = ticker
    _journal({"ticker": ticker, "source": book.get("source", "unknown")})
    return _text_result(book)


ORDER_BOOK_TOOLS = [get_order_book]
