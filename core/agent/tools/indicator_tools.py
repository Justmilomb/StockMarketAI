"""Technical indicator computation tools.

Gives the agent pre-computed indicator values (RSI, SMA, EMA, Bollinger
Bands, MACD, ATR, OBV, Stochastic, ADX) so it can evaluate technical
conditions in a single tool call instead of parsing hundreds of raw
OHLCV bars. All maths is pure pandas / numpy — no external TA library.

``tail_rows`` (default 10, max 50) controls how many recent rows are
returned, keeping token cost bounded while still showing trajectory.
Internally the full ``lookback_days`` window is used for accuracy
(e.g. SMA-200 needs 200+ bars).
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


# ── shared helpers (same pattern as backtest_tools) ──────────────────

def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(tool_name: str, payload: Dict[str, Any], tags: str = "indicator") -> None:
    try:
        ctx = get_agent_context()
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, 'tool_call', ?, ?, ?)",
                (ctx.iteration_id, tool_name, json.dumps(payload, default=str), tags),
            )
    except Exception:
        pass


def _clip_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        n = int(value or default)
    except (TypeError, ValueError):
        n = default
    return max(low, min(high, n))


def _fetch_daily(ticker: str, lookback_days: int) -> pd.DataFrame:
    from data_loader import fetch_ticker_data  # type: ignore

    end = datetime.utcnow().date()
    start = end - timedelta(days=lookback_days + 10)
    df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()
    return df


# ── indicator compute functions ──────────────────────────────────────
# Each takes a DataFrame with standard OHLCV columns and params dict,
# and returns the same DataFrame with new columns added.

def _compute_sma(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("sma_period", 20))
    df[f"sma_{period}"] = df["Close"].rolling(window=period).mean()
    return df


def _compute_ema(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("ema_period", 12))
    df[f"ema_{period}"] = df["Close"].ewm(span=period, adjust=False).mean()
    return df


def _compute_rsi(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("rsi_period", 14))
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing (exponential moving average).
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
    return df


def _compute_bbands(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("bb_period", 20))
    n_std = float(params.get("bb_std", 2.0))
    middle = df["Close"].rolling(window=period).mean()
    std = df["Close"].rolling(window=period).std()
    df["bb_upper"] = middle + n_std * std
    df["bb_middle"] = middle
    df["bb_lower"] = middle - n_std * std
    bandwidth = df["bb_upper"] - df["bb_lower"]
    df["bb_pct_b"] = (df["Close"] - df["bb_lower"]) / bandwidth.replace(0, np.nan)
    df["bb_bandwidth"] = bandwidth / middle.replace(0, np.nan)
    return df


def _compute_macd(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    fast = int(params.get("macd_fast", 12))
    slow = int(params.get("macd_slow", 26))
    signal = int(params.get("macd_signal", 9))
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["macd_line"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd_line"].ewm(span=signal, adjust=False).mean()
    df["macd_histogram"] = df["macd_line"] - df["macd_signal"]
    return df


def _compute_atr(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("atr_period", 14))
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=period).mean()
    return df


def _compute_obv(df: pd.DataFrame, _params: Dict[str, Any]) -> pd.DataFrame:
    direction = np.sign(df["Close"].diff()).fillna(0)
    df["obv"] = (df["Volume"] * direction).cumsum()
    return df


def _compute_stoch(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    k_period = int(params.get("stoch_k", 14))
    d_period = int(params.get("stoch_d", 3))
    low_min = df["Low"].rolling(window=k_period).min()
    high_max = df["High"].rolling(window=k_period).max()
    denom = (high_max - low_min).replace(0, np.nan)
    df["stoch_k"] = 100.0 * (df["Close"] - low_min) / denom
    df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
    return df


def _compute_adx(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    period = int(params.get("adx_period", 14))
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)

    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index)
    minus_dm_s = pd.Series(minus_dm, index=df.index)

    atr_smooth = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    plus_di = 100.0 * plus_dm_s.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr_smooth.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_s.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr_smooth.replace(0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


#: Registry mapping indicator names to compute functions.
_INDICATOR_REGISTRY: Dict[str, Any] = {
    "sma": _compute_sma,
    "ema": _compute_ema,
    "rsi": _compute_rsi,
    "bbands": _compute_bbands,
    "macd": _compute_macd,
    "atr": _compute_atr,
    "obv": _compute_obv,
    "stoch": _compute_stoch,
    "adx": _compute_adx,
}

VALID_INDICATORS: List[str] = sorted(_INDICATOR_REGISTRY.keys())


# ── tool ─────────────────────────────────────────────────────────────

@tool(
    "compute_indicators",
    (
        "Compute technical indicators for a ticker over daily OHLCV data. "
        "Pass a list of indicator names from: sma, ema, rsi, bbands, macd, "
        "atr, obv, stoch, adx. Each indicator accepts parameters via the "
        "params dict (e.g. {\"sma_period\": 50, \"rsi_period\": 14}). "
        "Returns the last `tail_rows` bars with all requested indicators. "
        "Use this to check technical conditions before sizing a trade — "
        "cheaper than eyeballing 200 bars of raw OHLCV."
    ),
    {
        "ticker": str,
        "indicators": list,
        "params": dict,
        "lookback_days": int,
        "tail_rows": int,
    },
)
async def compute_indicators(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    if not ticker:
        return _text_result({"error": "ticker is required"})

    raw_indicators = args.get("indicators", [])
    if not raw_indicators:
        return _text_result({
            "error": "indicators list is required",
            "valid": VALID_INDICATORS,
        })

    requested: List[str] = []
    unknown: List[str] = []
    for name in raw_indicators:
        name_lower = str(name).strip().lower()
        if name_lower in _INDICATOR_REGISTRY:
            requested.append(name_lower)
        else:
            unknown.append(str(name))

    if not requested:
        return _text_result({
            "error": f"no valid indicators in {raw_indicators}",
            "valid": VALID_INDICATORS,
        })

    params = args.get("params") or {}
    lookback_days = _clip_int(args.get("lookback_days"), 60, 730, 365)
    tail_rows = _clip_int(args.get("tail_rows"), 1, 50, 10)

    try:
        df = _fetch_daily(ticker, lookback_days)
    except Exception as exc:
        _journal("compute_indicators", {"ticker": ticker, "error": str(exc)}, "indicator,error")
        return _text_result({"error": f"data fetch failed: {exc}", "ticker": ticker})

    if df.empty:
        _journal("compute_indicators", {"ticker": ticker, "error": "no data"}, "indicator,error")
        return _text_result({"error": "no historical data available", "ticker": ticker})

    df = df.tail(lookback_days)

    for ind_name in requested:
        fn = _INDICATOR_REGISTRY[ind_name]
        df = fn(df, params)

    # Only return the tail rows with indicator columns + OHLCV.
    tail = df.tail(tail_rows).copy()

    # Build output: list of row dicts with date + all computed columns.
    base_cols = ["Open", "High", "Low", "Close", "Volume"]
    extra_cols = [c for c in tail.columns if c not in base_cols]
    rows: List[Dict[str, Any]] = []
    for idx, row in tail.iterrows():
        entry: Dict[str, Any] = {"date": str(idx.date()) if hasattr(idx, "date") else str(idx)}
        entry["close"] = round(float(row["Close"]), 4)
        for col in extra_cols:
            val = row[col]
            if pd.notna(val):
                entry[col.lower()] = round(float(val), 4)
        rows.append(entry)

    result: Dict[str, Any] = {
        "ticker": ticker,
        "indicators": requested,
        "params_used": params,
        "bars_total": len(df),
        "bars_returned": len(rows),
        "data": rows,
    }
    if unknown:
        result["unknown_indicators"] = unknown
        result["valid_indicators"] = VALID_INDICATORS

    _journal("compute_indicators", {
        "ticker": ticker,
        "indicators": requested,
        "bars": len(rows),
    })
    return _text_result(result)


INDICATOR_TOOLS = [compute_indicators]
