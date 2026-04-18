"""Options-flow heuristic — unusual volume via yfinance option chain.

No paid feed. For each expiry up to 60 days out we pull the chain and
flag strikes where volume > 3 x open interest AND absolute volume is
meaningful (>= 200 contracts). Those spikes are the most reliable
signal retail can see without a dark-pool feed.

Returns list of {ticker, expiry, side, strike, volume, oi, iv, spot,
moneyness}. Sorted by vol/oi ratio descending.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

VOLUME_OI_THRESHOLD: float = 3.0
ABS_VOLUME_FLOOR: int = 200
MAX_DAYS_OUT: int = 60


def unusual_activity(ticker: str) -> List[Dict[str, Any]]:
    try:
        import yfinance as yf
    except Exception:
        return []

    try:
        tk = yf.Ticker(ticker)
        expiries = list(tk.options or [])
    except Exception as e:
        logger.info("options_flow: ticker init failed: %s", e)
        return []

    try:
        spot_hist = tk.history(period="1d")
        spot = float(spot_hist["Close"].iloc[-1]) if not spot_hist.empty else 0.0
    except Exception:
        spot = 0.0

    today = datetime.now(timezone.utc).date()
    hits: List[Dict[str, Any]] = []
    for exp in expiries:
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
        except Exception:
            continue
        if (exp_date - today) > timedelta(days=MAX_DAYS_OUT):
            continue
        try:
            chain = tk.option_chain(exp)
        except Exception:
            continue
        for side, df in (("call", chain.calls), ("put", chain.puts)):
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                try:
                    vol = int(row.get("volume") or 0)
                    oi = int(row.get("openInterest") or 0)
                except Exception:
                    continue
                if vol < ABS_VOLUME_FLOOR or oi <= 0:
                    continue
                ratio = vol / oi
                if ratio < VOLUME_OI_THRESHOLD:
                    continue
                strike = float(row.get("strike") or 0.0)
                if side == "call" and strike > 0:
                    moneyness = spot / strike
                elif spot > 0:
                    moneyness = strike / spot
                else:
                    moneyness = 0.0
                hits.append({
                    "ticker": ticker.upper(),
                    "expiry": exp,
                    "side": side,
                    "strike": strike,
                    "volume": vol,
                    "oi": oi,
                    "vol_oi_ratio": round(ratio, 2),
                    "iv": float(row.get("impliedVolatility") or 0.0),
                    "spot": spot,
                    "moneyness": round(moneyness, 3),
                })
    hits.sort(key=lambda h: h["vol_oi_ratio"], reverse=True)
    return hits[:20]
