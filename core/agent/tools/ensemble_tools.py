"""Forecast ensemble MCP tool — one call, every forecaster, meta-learner blend."""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import pandas as pd

from core.agent._sdk import tool
from core.forecasting.ensemble import run_ensemble


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _fetch_recent_bars(ticker: str, interval: str, lookback_bars: int = 400) -> Tuple[pd.DataFrame, int]:
    import yfinance as yf

    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}.get(interval, 5)
    period = "7d" if minutes <= 5 else ("30d" if minutes <= 30 else "60d")
    df = yf.download(
        ticker, period=period, interval=interval,
        progress=False, auto_adjust=False, multi_level_index=False,
    )
    if df is None or df.empty:
        return pd.DataFrame(), minutes
    return df.tail(lookback_bars), minutes


@tool(
    "forecast_ensemble",
    "Run every enabled forecaster (Kronos, Chronos-2, TimesFM, TFT) and "
    "blend their outputs via a learned XGBoost meta-learner. Returns a "
    "single `meta.prob_up`, `meta.direction`, and `meta.expected_move_pct` "
    "plus each forecaster's availability/final_close for inspection.\n\n"
    "This is the preferred call over forecast_candles — it aggregates "
    "independent models so no single forecaster dominates a decision. "
    "Any backend that fails is silently dropped; the ensemble keeps "
    "working as long as at least one model returned data.\n\n"
    "Args:\n"
    "    ticker: instrument to forecast\n"
    "    horizon_minutes: prediction horizon (default 60)\n"
    "    interval: bar width — one of '1m','5m','15m','30m','60m' (default '5m')",
    {"ticker": str, "horizon_minutes": int, "interval": str},
)
async def forecast_ensemble(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    horizon = int(args.get("horizon_minutes", 60) or 60)
    interval = str(args.get("interval", "5m") or "5m")
    if not ticker:
        return _text_result({"error": "ticker is required"})

    try:
        hist, interval_minutes = _fetch_recent_bars(ticker, interval)
    except Exception as e:
        return _text_result({"ticker": ticker, "error": f"data fetch failed: {e}"})
    if hist.empty or len(hist) < 64:
        return _text_result({"ticker": ticker, "error": "not enough history"})

    pred_len = max(1, horizon // interval_minutes)
    hist = hist.copy()
    hist.columns = [c.lower() for c in hist.columns]

    out = run_ensemble(
        hist_df=hist,
        interval_minutes=interval_minutes,
        pred_len=pred_len,
        ticker=ticker,
    )
    # Strip the full close/high/low arrays to keep the MCP payload small.
    slim = {
        "ticker": out["ticker"],
        "pred_len": out["pred_len"],
        "interval_minutes": out["interval_minutes"],
        "last_close": out["last_close"],
        "meta": out["meta"],
        "forecasters": {
            name: {
                "available": "error" not in o,
                "error": o.get("error"),
                "final_close": (o.get("close") or [None])[-1] if "close" in o else None,
                "model_id": o.get("model_id"),
            }
            for name, o in out["forecasters"].items()
        },
    }
    return _text_result(slim)


ENSEMBLE_TOOLS = [forecast_ensemble]
