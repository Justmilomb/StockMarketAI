"""Market data tools for the Claude agent.

Routing:
    * held ticker → Trading 212 ``currentPrice`` (live)
    * other      → yfinance 5-day latest close (15-20 min delayed)

Intraday bars come from yfinance; 1m resolution is limited to the last
seven days by yfinance's own rules.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from claude_agent_sdk import tool

from core.agent.context import get_agent_context


# ── helpers ────────────────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _held_current_price(ticker: str) -> float | None:
    """Look up the live price the broker already knows about."""
    ctx = get_agent_context()
    try:
        for p in ctx.broker_service.get_positions():
            if str(p.get("ticker", "")) == ticker:
                px = float(p.get("current_price", 0.0) or 0.0)
                return px if px > 0 else None
    except Exception:
        return None
    return None


def _yf_interval_period(interval: str, lookback_minutes: int) -> tuple[str, str]:
    """Map an agent request to a valid yfinance (period, interval) pair."""
    intervals = {"1m", "5m", "15m", "30m", "60m"}
    if interval not in intervals:
        interval = "5m"
    # yfinance limit: 1m max 7 days, others max 60 days.
    max_days_by_interval = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "60m": 730}
    cap_days = max_days_by_interval[interval]
    days_needed = max(1, int((lookback_minutes / (60 * 6.5)) + 1))
    days = min(days_needed, cap_days)
    return f"{days}d", interval


# ── tools ──────────────────────────────────────────────────────────────

@tool(
    "get_live_price",
    "Return the latest known price for a ticker. If we already hold it, "
    "uses the broker's currentPrice (truly live). Otherwise uses yfinance "
    "(delayed 15-20 min). The response includes the source so you can "
    "reason about staleness.",
    {"ticker": str},
)
async def get_live_price(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    px = _held_current_price(ticker)
    if px is not None:
        return _text_result({
            "ticker": ticker, "price": px, "source": "broker_live",
            "ts": datetime.utcnow().isoformat() + "Z",
        })

    try:
        from data_loader import fetch_live_prices
        live = fetch_live_prices([ticker])
        data = live.get(ticker, {}) or {}
        price = float(data.get("price", 0.0) or 0.0)
        return _text_result({
            "ticker": ticker,
            "price": price,
            "change_pct": float(data.get("change_pct", 0.0) or 0.0),
            "source": "yfinance_delayed",
            "ts": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        return _text_result({"ticker": ticker, "error": str(e)})


@tool(
    "get_intraday_bars",
    "Return recent intraday OHLCV bars for a ticker. Intervals: 1m, 5m, "
    "15m, 30m, 60m. yfinance hard-caps 1m data to the last 7 trading days.",
    {"ticker": str, "interval": str, "lookback_minutes": int},
)
async def get_intraday_bars(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    interval = str(args.get("interval", "5m") or "5m")
    lookback_minutes = int(args.get("lookback_minutes", 240) or 240)
    if not ticker:
        return _text_result({"error": "ticker is required"})

    period, interval = _yf_interval_period(interval, lookback_minutes)
    try:
        import yfinance as yf
        df = yf.download(
            ticker, period=period, interval=interval,
            progress=False, auto_adjust=False, multi_level_index=False,
        )
    except Exception as e:
        return _text_result({"ticker": ticker, "error": f"yfinance error: {e}"})

    if df is None or df.empty:
        return _text_result({"ticker": ticker, "interval": interval, "bars": []})

    bars: List[Dict[str, Any]] = []
    for ts, row in df.tail(400).iterrows():
        bars.append({
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(row.get("Open", 0.0) or 0.0),
            "high": float(row.get("High", 0.0) or 0.0),
            "low": float(row.get("Low", 0.0) or 0.0),
            "close": float(row.get("Close", 0.0) or 0.0),
            "volume": float(row.get("Volume", 0.0) or 0.0),
        })
    return _text_result({
        "ticker": ticker, "interval": interval, "period": period,
        "count": len(bars), "bars": bars,
    })


@tool(
    "get_daily_bars",
    "Return recent daily OHLCV bars for a ticker via the cached data loader.",
    {"ticker": str, "lookback_days": int},
)
async def get_daily_bars(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    lookback_days = int(args.get("lookback_days", 90) or 90)
    if not ticker:
        return _text_result({"error": "ticker is required"})

    try:
        from data_loader import fetch_ticker_data
        end = datetime.utcnow().date()
        start = end - timedelta(days=max(7, lookback_days + 5))
        df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    except Exception as e:
        return _text_result({"ticker": ticker, "error": str(e)})

    if df is None or df.empty:
        return _text_result({"ticker": ticker, "bars": []})

    bars: List[Dict[str, Any]] = []
    for ts, row in df.tail(lookback_days).iterrows():
        bars.append({
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(row.get("Open", 0.0) or 0.0),
            "high": float(row.get("High", 0.0) or 0.0),
            "low": float(row.get("Low", 0.0) or 0.0),
            "close": float(row.get("Close", 0.0) or 0.0),
            "volume": float(row.get("Volume", 0.0) or 0.0),
        })
    return _text_result({"ticker": ticker, "count": len(bars), "bars": bars})


@tool(
    "search_instrument",
    "Search the broker's instrument catalogue for tickers matching a query. "
    "Useful when the agent wants to trade a name it has not held before.",
    {"query": str, "limit": int},
)
async def search_instrument(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    query = str(args.get("query", "")).strip().lower()
    limit = int(args.get("limit", 20) or 20)
    if not query:
        return _text_result({"matches": []})

    try:
        instruments = ctx.broker_service.get_instruments() or []
    except Exception as e:
        return _text_result({"error": str(e), "matches": []})

    matches: List[Dict[str, Any]] = []
    for i in instruments:
        if not isinstance(i, dict):
            continue
        hay = " ".join(str(v) for v in i.values()).lower()
        if query in hay:
            matches.append({
                "ticker": i.get("ticker", ""),
                "name": i.get("name", ""),
                "type": i.get("type", ""),
                "currencyCode": i.get("currencyCode", ""),
            })
            if len(matches) >= limit:
                break
    return _text_result({"query": query, "count": len(matches), "matches": matches})


MARKET_TOOLS = [
    get_live_price,
    get_intraday_bars,
    get_daily_bars,
    search_instrument,
]
