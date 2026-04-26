"""Smart-market order execution helper.

When the agent submits a market order, the spread on the underlying
ticker can quietly cost more than the trade's expected edge. This
helper interposes:

1. Read the L1 quote (bid/ask) for the ticker.
2. If the spread is tight (``<= smart_market_spread_pct_threshold`` of
   mid), submit the original market order — there's no spread to
   recapture.
3. Otherwise, submit a limit at the bid (buy) or ask (sell), poll the
   broker for fill for up to ``smart_market_wait_seconds``, and:
   * If the limit fills, return ``filled=True`` with the broker
     response so the calling tool reuses it as the final result.
   * If the limit doesn't fill in time, cancel it and return
     ``filled=False`` so the caller falls back to a market order.

Returns ``None`` (no smart action) when the feature is disabled or
prerequisites aren't met (no quote, zero quantity, etc).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def _l1_quote(ticker: str) -> Optional[Dict[str, float]]:
    """Best-effort bid/ask via yfinance fast_info."""
    try:
        import yfinance as yf
    except Exception:
        return None

    def _fetch() -> Dict[str, float]:
        out: Dict[str, float] = {}
        try:
            t = yf.Ticker(ticker)
            fi = t.fast_info
            bid = float(getattr(fi, "bid", 0.0) or 0.0)
            ask = float(getattr(fi, "ask", 0.0) or 0.0)
            last = float(getattr(fi, "last_price", 0.0) or 0.0)
            if bid <= 0 or ask <= 0:
                info = t.info or {}
                bid = bid or float(info.get("bid", 0.0) or 0.0)
                ask = ask or float(info.get("ask", 0.0) or 0.0)
                last = last or float(info.get("regularMarketPrice", 0.0) or 0.0)
            if bid > 0 and ask > bid:
                out["bid"] = bid
                out["ask"] = ask
                out["last"] = last
        except Exception:
            return {}
        return out

    return await asyncio.to_thread(_fetch)


def _normalise_for_pence(ticker: str, price: float) -> float:
    """Reverse the GBX→GBP conversion when sending a price back to the broker.

    ``yfinance`` returns LSE prices in pence; the broker expects native
    units (pence on .L tickers, pounds elsewhere). We do not divide
    here because ``fast_info`` returns the pence number directly — the
    broker is happy with that.
    """
    return float(price)


async def _wait_for_fill(
    svc: Any,
    order_id: str,
    timeout_seconds: float,
    poll_seconds: float = 1.0,
) -> bool:
    """Poll until the order is no longer pending or the timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            pending = svc.get_pending_orders() or []
        except Exception:
            return False
        if not any(str(o.get("order_id", "")) == order_id for o in pending):
            return True
        await asyncio.sleep(poll_seconds)
    return False


async def attempt_smart_market(
    *,
    svc: Any,
    ticker: str,
    side: str,
    quantity: float,
    config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Attempt a limit-first execution. Returns a summary dict or None.

    When the helper returns a summary with ``filled=True``, the caller
    must reuse ``broker_response`` as the order's final result. When
    ``filled=False``, the caller should fall back to a market order.
    """
    exec_cfg = (config or {}).get("execution", {}) or {}
    if not bool(exec_cfg.get("smart_market_enabled", True)):
        return None
    if quantity <= 0 or side not in ("buy", "sell"):
        return None

    threshold_pct = float(exec_cfg.get("smart_market_spread_pct_threshold", 0.5) or 0.5)
    wait_seconds = float(exec_cfg.get("smart_market_wait_seconds", 30.0) or 30.0)

    quote = await _l1_quote(ticker)
    if not quote:
        return {
            "path": "no_quote",
            "filled": False,
            "reason": "no L1 quote available",
        }

    bid = quote["bid"]
    ask = quote["ask"]
    mid = (bid + ask) / 2.0
    spread_pct = ((ask - bid) / mid * 100.0) if mid > 0 else 0.0

    if spread_pct <= threshold_pct:
        return {
            "path": "tight_spread_skip",
            "filled": False,
            "spread_pct": round(spread_pct, 4),
            "threshold_pct": threshold_pct,
            "reason": "spread within threshold — submitting market directly",
        }

    limit_price = bid if side == "buy" else ask
    limit_price = _normalise_for_pence(ticker, limit_price)

    try:
        resp = svc.submit_order(
            ticker=ticker,
            side=side.upper(),
            quantity=quantity,
            order_type="limit",
            limit_price=limit_price,
        )
    except Exception as e:
        logger.warning("[smart_exec] limit submit failed for %s: %s", ticker, e)
        return {
            "path": "limit_submit_error",
            "filled": False,
            "reason": str(e),
            "spread_pct": round(spread_pct, 4),
        }

    order_id = str((resp or {}).get("order_id", "") or "")
    if not order_id:
        return {
            "path": "limit_no_order_id",
            "filled": False,
            "spread_pct": round(spread_pct, 4),
            "broker_response": resp,
            "reason": "broker did not return an order_id — cannot wait for fill",
        }

    filled = await _wait_for_fill(svc, order_id, timeout_seconds=wait_seconds)
    if filled:
        return {
            "path": "limit_filled",
            "filled": True,
            "spread_pct": round(spread_pct, 4),
            "limit_price": limit_price,
            "wait_seconds": wait_seconds,
            "broker_response": resp,
        }

    try:
        svc.cancel_order(order_id)
    except Exception as e:
        logger.warning("[smart_exec] cancel failed for %s: %s", order_id, e)

    return {
        "path": "market_fallback",
        "filled": False,
        "spread_pct": round(spread_pct, 4),
        "limit_price": limit_price,
        "wait_seconds": wait_seconds,
        "cancelled_order_id": order_id,
        "reason": f"limit not filled in {wait_seconds:.0f}s — falling back to market",
    }
