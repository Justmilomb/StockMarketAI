"""Market data tools for the AI agent.

Routing:
    * held ticker → Trading 212 ``currentPrice`` (live)
    * other      → yfinance 5-day latest close (15-20 min delayed)

Intraday bars come from yfinance; 1m resolution is limited to the last
seven days by yfinance's own rules.

``search_instrument`` has a two-tier lookup: it asks the active broker
service first (which works in live mode), and if that comes back empty
it falls back to a direct Trading 212 metadata call using whatever
credentials are in the environment. This matters in paper mode, where
the session-wide ``PaperBroker`` inherits the base broker's empty
``get_instruments`` implementation and would otherwise leave the agent
with no way to discover tickers by name.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.agent._sdk import tool

from core.agent.context import get_agent_context


# ── helpers ────────────────────────────────────────────────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


#: Process-lifetime cache for the Trading 212 instrument catalogue.
#: Populated on first successful fetch and reused for the rest of the
#: session — the ~15k-row list rarely changes and is ~2 MB on the wire.
_INSTRUMENT_CACHE: Optional[List[Dict[str, Any]]] = None


def _load_instruments_with_fallback() -> List[Dict[str, Any]]:
    """Return the broker's instrument catalogue, with a paper-mode fallback.

    Order of attempts:

    1. The active broker service (``ctx.broker_service``). In live mode
       this goes straight to ``Trading212Broker.get_instruments``; in
       paper mode it hits the inherited empty list and returns ``[]``.
    2. A direct ``Trading212Broker`` instantiation using ``T212_API_KEY``
       / ``T212_SECRET_KEY`` from the environment. This lets paper-mode
       sessions still resolve tickers by name as long as the user has
       live creds configured.
    3. Empty list — cached so we don't keep hitting the network.
    """
    global _INSTRUMENT_CACHE
    if _INSTRUMENT_CACHE is not None:
        return _INSTRUMENT_CACHE

    try:
        ctx = get_agent_context()
        primary = ctx.broker_service.get_instruments() or []
    except Exception:
        primary = []
    if primary:
        _INSTRUMENT_CACHE = primary
        return primary

    api_key = os.getenv("T212_API_KEY", "")
    secret_key = os.getenv("T212_SECRET_KEY", "")
    if not api_key:
        _INSTRUMENT_CACHE = []
        return []

    try:
        from trading212 import Trading212Broker, Trading212BrokerConfig
        cfg = Trading212BrokerConfig(
            api_key=api_key,
            secret_key=secret_key,
            base_url="https://live.trading212.com",
            practice=False,
        )
        broker = Trading212Broker(cfg)
        _INSTRUMENT_CACHE = broker.get_instruments() or []
    except Exception:
        _INSTRUMENT_CACHE = []
    return _INSTRUMENT_CACHE


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
    "Search the Trading 212 instrument catalogue for tickers matching a query. "
    "Matches against both the ticker symbol and the company name. Works in "
    "both live and paper mode (paper mode falls back to a direct metadata "
    "fetch using the configured T212 credentials).",
    {"query": str, "limit": int},
)
async def search_instrument(args: Dict[str, Any]) -> Dict[str, Any]:
    query = str(args.get("query", "")).strip().lower()
    limit = int(args.get("limit", 20) or 20)
    if not query:
        return _text_result({"matches": []})

    try:
        instruments = _load_instruments_with_fallback()
    except Exception as e:
        return _text_result({"error": str(e), "matches": []})

    if not instruments:
        return _text_result({
            "query": query,
            "count": 0,
            "matches": [],
            "note": "instrument catalogue unavailable — check T212 credentials",
        })

    matches: List[Dict[str, Any]] = []
    for i in instruments:
        if not isinstance(i, dict):
            continue
        ticker = str(i.get("ticker", "")).lower()
        name = str(i.get("name", "")).lower()
        if query in ticker or query in name:
            matches.append({
                "ticker": i.get("ticker", ""),
                "name": i.get("name", ""),
                "type": i.get("type", ""),
                "currencyCode": i.get("currencyCode", "") or i.get("currency", ""),
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
