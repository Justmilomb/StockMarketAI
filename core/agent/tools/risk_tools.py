"""Risk tools for the Claude agent.

``size_position`` is the only risk tool exposed to the agent. It delegates
to RiskManager.assess_position and computes ATR from recent daily bars
on the fly so the agent only has to supply conviction + price.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict

from claude_agent_sdk import tool

from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _compute_atr(ticker: str, period_days: int = 30) -> tuple[float, float]:
    """Return (latest_close, ATR over *period_days*). Falls back to (0, 0) on failure."""
    try:
        from data_loader import fetch_ticker_data
        end = datetime.utcnow().date()
        start = end - timedelta(days=period_days * 2 + 10)
        df = fetch_ticker_data(ticker, start.isoformat(), end.isoformat())
    except Exception:
        return 0.0, 0.0

    if df is None or df.empty or len(df) < 2:
        return 0.0, 0.0

    tail = df.tail(period_days + 1).copy()
    high = tail["High"].astype(float)
    low = tail["Low"].astype(float)
    close = tail["Close"].astype(float)
    prev_close = close.shift(1)
    tr = (high - low).abs()
    tr = tr.combine((high - prev_close).abs(), max)
    tr = tr.combine((low - prev_close).abs(), max)
    atr = float(tr.dropna().mean() or 0.0)
    latest = float(close.iloc[-1])
    return latest, atr


@tool(
    "size_position",
    "Compute a risk-managed position size for a proposed entry. "
    "Uses Kelly sizing bounded by ATR volatility and the "
    "max_position_pct cap. Returns suggested share quantity, dollar "
    "exposure, stop-loss and take-profit levels.\n\n"
    "Args:\n"
    "    ticker: instrument identifier (e.g. 'TSLA')\n"
    "    conviction: 0.5-1.0, how strongly you believe in the edge\n"
    "    confidence: 0.0-1.0, independent confidence in your model\n"
    "This does NOT place the order — call place_order after reviewing the size.",
    {"ticker": str, "conviction": float, "confidence": float},
)
async def size_position(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    ticker = str(args.get("ticker", "")).strip()
    conviction = float(args.get("conviction", 0.6) or 0.6)
    confidence = float(args.get("confidence", 0.5) or 0.5)
    if not ticker:
        return _text_result({"error": "ticker is required"})

    latest, atr = _compute_atr(ticker)
    if latest <= 0 or atr <= 0:
        return _text_result({
            "ticker": ticker,
            "error": "could not compute ATR (no price data)",
            "shares": 0.0, "dollars": 0.0,
        })

    positions = ctx.broker_service.get_positions()
    account = ctx.broker_service.get_account_info()

    assessment = ctx.risk_manager.assess_position(
        ticker=ticker,
        probability=max(0.5, min(1.0, conviction)),
        confidence=max(0.0, min(1.0, confidence)),
        price=latest,
        atr=atr,
        positions=positions,
        account=account,
        consensus=None,
    )

    return _text_result({
        "ticker": ticker,
        "price": latest,
        "atr": atr,
        "suggested_shares": float(assessment.position_size_shares),
        "suggested_dollars": float(assessment.position_size_dollars),
        "stop_loss": float(assessment.stop_loss),
        "take_profit": float(assessment.take_profit),
        "kelly_fraction": float(assessment.kelly_fraction),
        "risk_score": float(assessment.risk_score),
        "reason": assessment.reason,
    })


RISK_TOOLS = [size_position]
