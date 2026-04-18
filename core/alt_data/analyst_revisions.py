"""Analyst EPS revision momentum.

Computes two signals via yfinance:

* ``recommendation_velocity`` — change in strongBuy+buy count over the
  latest month vs earliest available month, normalised by total analysts.
  Positive = upgrades accelerating.

* ``eps_revision_slope`` — linear slope of the avg-EPS estimate series
  across future-period rows (0q -> +1q -> 0y -> +1y). Positive =
  estimates rising into the future.

Plus a snapshot of ``analyst_price_targets`` (current/high/low/mean/median).
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import numpy as np

logger = logging.getLogger(__name__)


def revision_momentum(ticker: str) -> Dict[str, Any]:
    try:
        import yfinance as yf
    except Exception:
        return {"error": "yfinance unavailable"}

    try:
        tk = yf.Ticker(ticker)
    except Exception as e:
        return {"error": f"ticker init failed: {e}"}

    rec_velocity = 0.0
    try:
        rec = tk.recommendations
        if rec is not None and len(rec) >= 2:
            current = rec.iloc[0]
            prior = rec.iloc[-1]
            current_bullish = float(current.get("strongBuy", 0) + current.get("buy", 0))
            prior_bullish = float(prior.get("strongBuy", 0) + prior.get("buy", 0))
            total = float(
                current.get("strongBuy", 0) + current.get("buy", 0) + current.get("hold", 0)
                + current.get("sell", 0) + current.get("strongSell", 0)
            ) or 1.0
            rec_velocity = (current_bullish - prior_bullish) / total
    except Exception as e:
        logger.info("analyst_revisions: recommendations fetch failed: %s", e)

    eps_slope = 0.0
    try:
        est = tk.earnings_estimate
        if est is not None and len(est) >= 2:
            values = est["avg"].to_numpy(dtype=float)
            xs = np.arange(len(values), dtype=float)
            if np.isfinite(values).all():
                eps_slope = float(np.polyfit(xs, values, 1)[0])
    except Exception as e:
        logger.info("analyst_revisions: earnings_estimate fetch failed: %s", e)

    targets: Dict[str, Any] = {}
    try:
        tp = tk.analyst_price_targets
        if isinstance(tp, dict):
            targets = {k: tp.get(k) for k in ("current", "high", "low", "mean", "median")}
    except Exception:
        pass

    return {
        "ticker": ticker.upper(),
        "recommendation_velocity": round(rec_velocity, 4),
        "eps_revision_slope": round(eps_slope, 4),
        "analyst_targets": targets,
    }
