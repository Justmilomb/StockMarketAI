"""Multi-timeframe market data tools.

Returns 1m, 5m, 15m and 1h candles for a single ticker in one tool call
so the agent can see micro trends inside macro trends without firing
four separate ``get_intraday_bars`` requests. Each interval is fetched
in parallel via a small thread pool, then trimmed to the last N bars
and normalised to pounds for ``.L`` tickers.
"""
from __future__ import annotations

import concurrent.futures
import json
from typing import Any, Dict, List

from core.agent._sdk import tool
from core.agent.context import get_agent_context


_DEFAULT_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "60m")
_VALID_INTERVALS: frozenset[str] = frozenset({"1m", "5m", "15m", "30m", "60m"})

#: Minimum lookback needed per interval to give the agent enough bars
#: to reason about trend direction without bloating the response.
_LOOKBACK_BY_INTERVAL: Dict[str, str] = {
    "1m": "1d",
    "5m": "1d",
    "15m": "5d",
    "30m": "5d",
    "60m": "30d",
}


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(payload: Dict[str, Any]) -> None:
    import sqlite3
    try:
        ctx = get_agent_context()
    except Exception:
        return
    try:
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, ?)",
                (
                    ctx.iteration_id,
                    payload.get("tool", ""),
                    json.dumps(payload, default=str),
                    "multi_timeframe",
                ),
            )
    except Exception:
        pass


def _fetch_one(ticker: str, interval: str, tail: int) -> Dict[str, Any]:
    """Fetch a single interval and return its bar list."""
    try:
        import yfinance as yf
        period = _LOOKBACK_BY_INTERVAL.get(interval, "5d")
        df = yf.download(
            ticker, period=period, interval=interval,
            progress=False, auto_adjust=False, multi_level_index=False,
        )
    except Exception as e:
        return {"interval": interval, "error": f"yfinance error: {e}", "bars": []}

    if df is None or df.empty:
        return {"interval": interval, "bars": []}

    try:
        from fx import is_pence_quoted
        px_div = 100.0 if is_pence_quoted(ticker) else 1.0
    except Exception:
        px_div = 1.0

    bars: List[Dict[str, Any]] = []
    for ts, row in df.tail(max(1, int(tail))).iterrows():
        bars.append({
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "open": float(row.get("Open", 0.0) or 0.0) / px_div,
            "high": float(row.get("High", 0.0) or 0.0) / px_div,
            "low": float(row.get("Low", 0.0) or 0.0) / px_div,
            "close": float(row.get("Close", 0.0) or 0.0) / px_div,
            "volume": float(row.get("Volume", 0.0) or 0.0),
        })

    last_close = bars[-1]["close"] if bars else 0.0
    first_close = bars[0]["close"] if bars else 0.0
    pct_change = (
        ((last_close - first_close) / first_close * 100.0)
        if first_close > 0 else 0.0
    )

    return {
        "interval": interval,
        "count": len(bars),
        "last_close": last_close,
        "pct_change_in_window": round(pct_change, 3),
        "bars": bars,
    }


@tool(
    "get_multi_timeframe",
    "Return recent OHLCV candles for a ticker across multiple timeframes "
    "(1m / 5m / 15m / 1h by default) in a single call. The agent uses "
    "this to confirm a setup at multiple zooms — a 1m breakout that "
    "agrees with a 1h uptrend is far stronger than one that fights it. "
    "Pass ``intervals`` to shrink the set, ``tail_bars`` to control how "
    "many bars per interval (default 60, max 200).",
    {"ticker": str, "intervals": str, "tail_bars": int},
)
async def get_multi_timeframe(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    raw_intervals = str(args.get("intervals", "") or "").strip()
    if raw_intervals:
        requested = [i.strip() for i in raw_intervals.split(",") if i.strip()]
        intervals = [i for i in requested if i in _VALID_INTERVALS] or list(_DEFAULT_INTERVALS)
    else:
        intervals = list(_DEFAULT_INTERVALS)

    tail_bars = int(args.get("tail_bars", 60) or 60)
    tail_bars = max(5, min(200, tail_bars))

    results: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(intervals)) as pool:
        futures = {
            pool.submit(_fetch_one, ticker, iv, tail_bars): iv
            for iv in intervals
        }
        for fut in concurrent.futures.as_completed(futures):
            iv = futures[fut]
            try:
                results[iv] = fut.result()
            except Exception as e:
                results[iv] = {"interval": iv, "error": str(e), "bars": []}

    response = {
        "ticker": ticker,
        "intervals": intervals,
        "tail_bars": tail_bars,
        "frames": results,
    }
    _journal({"tool": "get_multi_timeframe", "ticker": ticker, "intervals": intervals})
    return _text_result(response)


MULTI_TIMEFRAME_TOOLS = [get_multi_timeframe]
