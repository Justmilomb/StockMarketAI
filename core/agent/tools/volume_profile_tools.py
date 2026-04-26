"""Volume profile tool — price-by-volume distribution.

A volume profile bins traded volume by price level over a lookback
window, surfacing the prices where most activity has occurred.
High-volume bins act as natural support / resistance: they're where
buyers and sellers have already agreed on a fair price, so future
returns to those levels usually attract more activity (defending or
breaking through).

Returns the volume-weighted point of control (POC) — the single
highest-volume bin — plus the value area around it that contains a
configurable fraction of total volume (default 70%).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

import numpy as np
import pandas as pd

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
                    ctx.iteration_id, "get_volume_profile",
                    json.dumps(payload, default=str), "volume_profile",
                ),
            )
    except Exception:
        pass


def _build_profile(
    df: pd.DataFrame,
    bins: int,
    value_area_pct: float,
) -> Dict[str, Any]:
    """Bin daily bars by typical price and sum volume per bin."""
    if df.empty:
        return {"bins": [], "poc": None, "value_area": None}

    typical = (df["High"] + df["Low"] + df["Close"]) / 3.0
    volume = df["Volume"].astype(float)

    lo = float(typical.min())
    hi = float(typical.max())
    if hi <= lo:
        # Flat window — degenerate case, fold all volume into one bin
        return {
            "bins": [{"price_low": lo, "price_high": hi, "volume": float(volume.sum())}],
            "poc": {"price_mid": lo, "volume": float(volume.sum())},
            "value_area": {"low": lo, "high": hi, "pct": 1.0},
        }

    edges = np.linspace(lo, hi, bins + 1)
    bin_idx = np.clip(np.digitize(typical.values, edges) - 1, 0, bins - 1)

    totals = np.zeros(bins, dtype=float)
    for i, vol in zip(bin_idx, volume.values):
        totals[i] += float(vol)

    bin_rows: List[Dict[str, float]] = []
    for i in range(bins):
        bin_rows.append({
            "price_low": float(edges[i]),
            "price_high": float(edges[i + 1]),
            "price_mid": float((edges[i] + edges[i + 1]) / 2.0),
            "volume": float(totals[i]),
        })

    poc_idx = int(np.argmax(totals))
    poc = {
        "price_mid": bin_rows[poc_idx]["price_mid"],
        "price_low": bin_rows[poc_idx]["price_low"],
        "price_high": bin_rows[poc_idx]["price_high"],
        "volume": bin_rows[poc_idx]["volume"],
    }

    # Build the value area outward from POC by greedy expansion: at each
    # step, take whichever neighbour bin has more volume until the
    # accumulated share crosses the target.
    target = float(totals.sum() * value_area_pct)
    accumulated = totals[poc_idx]
    lo_idx = poc_idx
    hi_idx = poc_idx
    while accumulated < target and (lo_idx > 0 or hi_idx < bins - 1):
        next_lo = totals[lo_idx - 1] if lo_idx > 0 else -1.0
        next_hi = totals[hi_idx + 1] if hi_idx < bins - 1 else -1.0
        if next_lo < 0 and next_hi < 0:
            break
        if next_hi >= next_lo:
            hi_idx += 1
            accumulated += totals[hi_idx]
        else:
            lo_idx -= 1
            accumulated += totals[lo_idx]

    value_area = {
        "low": bin_rows[lo_idx]["price_low"],
        "high": bin_rows[hi_idx]["price_high"],
        "pct": float(accumulated / totals.sum()) if totals.sum() > 0 else 0.0,
    }

    return {"bins": bin_rows, "poc": poc, "value_area": value_area}


@tool(
    "get_volume_profile",
    "Return the price-by-volume distribution for a ticker over the last "
    "N daily bars. Identifies the point-of-control (highest-volume price) "
    "and the value area (the price band containing 70% of volume). Use "
    "POC and value-area edges as natural support / resistance: bouncing "
    "off the value-area-low is a common entry; rejecting the value-area-"
    "high is a common short. Defaults: 30 days, 20 bins.",
    {"ticker": str, "days": int, "bins": int, "value_area_pct": float},
)
async def get_volume_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    days = max(5, min(365, int(args.get("days", 30) or 30)))
    bins = max(5, min(50, int(args.get("bins", 20) or 20)))
    value_area_pct = float(args.get("value_area_pct", 0.7) or 0.7)
    if not (0.1 < value_area_pct < 1.0):
        value_area_pct = 0.7

    try:
        from data_loader import fetch_ticker_data
        end = datetime.utcnow().date()
        start = end - timedelta(days=days + 5)
        df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    except Exception as e:
        return _text_result({"ticker": ticker, "error": str(e), "bins": []})

    if df is None or df.empty:
        return _text_result({"ticker": ticker, "bins": [], "note": "no data"})

    df = df.tail(days)
    profile = _build_profile(df, bins=bins, value_area_pct=value_area_pct)

    try:
        from fx import is_pence_quoted
        if is_pence_quoted(ticker):
            for b in profile["bins"]:
                b["price_low"] /= 100.0
                b["price_high"] /= 100.0
                b["price_mid"] /= 100.0
            if profile.get("poc"):
                profile["poc"]["price_low"] /= 100.0
                profile["poc"]["price_high"] /= 100.0
                profile["poc"]["price_mid"] /= 100.0
            if profile.get("value_area"):
                profile["value_area"]["low"] /= 100.0
                profile["value_area"]["high"] /= 100.0
    except Exception:
        pass

    response = {
        "ticker": ticker,
        "days": int(days),
        "bins": int(bins),
        "value_area_pct": value_area_pct,
        "profile": profile,
    }
    _journal({"ticker": ticker, "days": days, "bins": bins})
    return _text_result(response)


VOLUME_PROFILE_TOOLS = [get_volume_profile]
