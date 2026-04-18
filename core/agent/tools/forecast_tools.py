"""Kronos forecast tool — pre-sell price-forecast gate for the agent.

Exposes a single MCP tool, ``forecast_candles(ticker, pred_minutes,
interval)``. The agent is instructed by the system prompt to call
this before every discretionary sell: if the model forecasts
recovery above entry within the window, it should hold.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import pandas as pd

from core.agent._sdk import tool


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _fetch_recent_bars(ticker: str, interval: str, lookback_bars: int = 400) -> Tuple[pd.DataFrame, int]:
    """Pull recent intraday bars via yfinance. Returns (df, interval_minutes)."""
    import yfinance as yf

    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}.get(interval, 5)
    if minutes <= 5:
        period = "7d"
    elif minutes <= 30:
        period = "30d"
    else:
        period = "60d"
    df = yf.download(
        ticker, period=period, interval=interval,
        progress=False, auto_adjust=False, multi_level_index=False,
    )
    if df is None or df.empty:
        return pd.DataFrame(), minutes
    return df.tail(lookback_bars), minutes


@tool(
    "forecast_candles",
    "Forecast the next N minutes of OHLC candles for a ticker using the "
    "Kronos financial foundation model. Call this BEFORE every "
    "discretionary sell. If the forecast shows close recovering above "
    "your entry price within the window, you should hold instead of "
    "exiting. Also useful for entry timing — buy only if the forecast "
    "trends up.\n\n"
    "Args:\n"
    "    ticker: instrument to forecast\n"
    "    pred_minutes: horizon in minutes (e.g. 60, 120, 240)\n"
    "    interval: bar width — one of '1m','5m','15m','30m','60m' (default '5m')\n\n"
    "Returns predicted close/high/low arrays and a summary with the "
    "final predicted close, the max predicted close, and the min "
    "predicted low over the horizon.",
    {"ticker": str, "pred_minutes": int, "interval": str},
)
async def forecast_candles(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    pred_minutes = int(args.get("pred_minutes", 60) or 60)
    interval = str(args.get("interval", "5m") or "5m")
    if not ticker:
        return _text_result({"error": "ticker is required"})
    if pred_minutes <= 0 or pred_minutes > 1440:
        return _text_result({"error": "pred_minutes must be 1..1440"})

    try:
        hist, interval_minutes = _fetch_recent_bars(ticker, interval)
    except Exception as e:
        return _text_result({"ticker": ticker, "error": f"data fetch failed: {e}"})
    if hist.empty or len(hist) < 64:
        return _text_result({"ticker": ticker, "error": "not enough history to forecast"})

    pred_len = max(1, pred_minutes // interval_minutes)

    from core.kronos_forecaster import forecast as _forecast
    result = _forecast(hist_df=hist, interval_minutes=interval_minutes, pred_len=pred_len)
    if "error" in result:
        return _text_result({"ticker": ticker, **result})

    closes = result["close"]
    highs = result["high"]
    lows = result["low"]
    last_close = float(hist["Close"].iloc[-1]) if "Close" in hist.columns else float(hist["close"].iloc[-1])
    return _text_result({
        "ticker": ticker,
        "interval": interval,
        "pred_minutes": pred_minutes,
        "pred_len": pred_len,
        "model_id": result["model_id"],
        "timestamps": result["timestamps"],
        "predicted_close": closes,
        "predicted_high": highs,
        "predicted_low": lows,
        "summary": {
            "final_close": closes[-1] if closes else 0.0,
            "max_close": max(closes) if closes else 0.0,
            "min_low": min(lows) if lows else 0.0,
            "pct_move_final_vs_last_hist": round(
                (closes[-1] / last_close - 1) * 100, 3
            ) if closes and last_close else 0.0,
        },
    })


FORECAST_TOOLS = [forecast_candles]
