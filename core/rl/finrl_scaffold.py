"""FinRL allocation scaffold.

Today this module returns an equal-weight allocation (baseline). A
follow-up plan will replace the body of ``allocate`` with a trained
FinRL PPO/SAC agent loaded from ``models/finrl_<regime>.zip``.

The contract is stable: give a list of tickers and an equity figure,
get back ``{ticker: weight}`` summing to 1.0 plus a recommended
rebalance cadence in hours.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def allocate(tickers: List[str], equity: float, regime: str = "neutral") -> Dict[str, Any]:
    tickers = [t for t in tickers if t]
    if not tickers or equity <= 0:
        return {"weights": {}, "rebalance_hours": 24, "source": "empty"}

    weight = 1.0 / len(tickers)
    weights = {t.upper(): round(weight, 6) for t in tickers}
    cadence = {"bull": 72, "neutral": 48, "bear": 24, "crisis": 6}.get(regime, 48)
    return {
        "weights": weights,
        "rebalance_hours": cadence,
        "regime": regime,
        "source": "equal_weight_cold_start",
    }
