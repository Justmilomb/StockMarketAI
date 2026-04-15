"""Risk tools for the Claude agent.

``size_position`` is the only risk tool exposed to the agent. It delegates
to RiskManager.assess_position and computes ATR from recent daily bars
on the fly so the agent only has to supply conviction + price.

Currency handling: a £100 GBP paper account sizing a USD stock like TSLA
used to silently treat the USD price as if it were GBP, so a Kelly bet of
10% of £100 mapped to ``0.03 shares @ $300`` — a position that is
actually worth only ~£8, not the intended £10. We fix that here by
converting the ticker's quote + ATR into the account currency *before*
calling ``assess_position``. All sizing stays in account currency, the
returned ``suggested_shares`` is the real figure to pass to
``place_order``, and the report surfaces both the account-currency
numbers and the native quote so the agent can sanity-check.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict

from claude_agent_sdk import tool

from core.agent.context import get_agent_context
from fx import fx_rate, ticker_currency


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
    "max_position_pct cap, then converts to the account currency so "
    "the suggested share count is correct even when the ticker is "
    "quoted in a different currency (e.g. £100 GBP account sizing a "
    "USD stock like TSLA).\n\n"
    "Returns suggested share quantity plus the account-currency cost, "
    "stop-loss, take-profit, and both the native and converted price. "
    "Pass ``suggested_shares`` straight to ``place_order`` — no extra "
    "FX conversion needed.\n\n"
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

    native_price, native_atr = _compute_atr(ticker)
    if native_price <= 0 or native_atr <= 0:
        return _text_result({
            "ticker": ticker,
            "error": "could not compute ATR (no price data)",
            "shares": 0.0, "dollars": 0.0,
        })

    positions = ctx.broker_service.get_positions()
    account = ctx.broker_service.get_account_info()

    # Convert ticker-native quote into account currency so Kelly
    # sizing comes out in the right denomination. A £100 GBP account
    # sizing a $300 TSLA needs the price expressed in GBP — otherwise
    # ``kelly_size (GBP) / price (USD)`` returns a share count that
    # silently undersizes by the FX rate.
    native_ccy = ticker_currency(ticker, default="USD")
    account_ccy = str(account.get("currency") or "USD").upper()
    rate = fx_rate(native_ccy, account_ccy)
    price = native_price * rate
    atr = native_atr * rate

    assessment = ctx.risk_manager.assess_position(
        ticker=ticker,
        probability=max(0.5, min(1.0, conviction)),
        confidence=max(0.0, min(1.0, confidence)),
        price=price,
        atr=atr,
        positions=positions,
        account=account,
        consensus=None,
    )

    # assess_position returned stop/take in account currency because
    # we fed it the converted price+atr. Divide back out so the agent
    # gets stops in the same currency the broker compares against (the
    # ticker's native quote). ``place_order``'s ``stop_loss`` and
    # ``take_profit`` fields must be in native currency or the paper
    # broker's limit/stop comparisons will never trigger.
    native_stop_loss = (assessment.stop_loss / rate) if rate else 0.0
    native_take_profit = (assessment.take_profit / rate) if rate else 0.0

    return _text_result({
        "ticker": ticker,
        "native_currency": native_ccy,
        "account_currency": account_ccy,
        "fx_rate": round(rate, 6),
        "native_price": round(native_price, 4),
        "native_atr": round(native_atr, 4),
        "price_in_account_ccy": round(price, 4),
        "atr_in_account_ccy": round(atr, 4),
        "suggested_shares": float(assessment.position_size_shares),
        "suggested_cost_account_ccy": float(assessment.position_size_dollars),
        # Pass these through to place_order — they're in the ticker's
        # native currency (USD for TSLA, GBP for VOD.L, etc).
        "stop_loss": round(native_stop_loss, 4),
        "take_profit": round(native_take_profit, 4),
        # Same levels expressed in account currency for display.
        "stop_loss_account_ccy": round(float(assessment.stop_loss), 4),
        "take_profit_account_ccy": round(float(assessment.take_profit), 4),
        "kelly_fraction": float(assessment.kelly_fraction),
        "risk_score": float(assessment.risk_score),
        "reason": assessment.reason,
    })


RISK_TOOLS = [size_position]
