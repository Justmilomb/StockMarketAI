from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from core.alt_data.analyst_revisions import revision_momentum


def _fake_ticker():
    est = pd.DataFrame({
        "avg": [1.10, 1.12, 1.15, 1.20],
        "period": ["0q", "+1q", "0y", "+1y"],
    })
    rec = pd.DataFrame({
        "period": ["0m", "-1m", "-2m", "-3m"],
        "strongBuy": [12, 10, 8, 7],
        "buy": [8, 7, 6, 6],
        "hold": [2, 4, 6, 6],
        "sell": [0, 1, 1, 1],
        "strongSell": [0, 0, 0, 0],
    })
    tk = MagicMock()
    tk.recommendations = rec
    tk.earnings_estimate = est
    tk.analyst_price_targets = {
        "current": 150, "high": 175, "low": 120, "mean": 155, "median": 152,
    }
    return tk


def test_revision_momentum_returns_positive_when_upgrades_accelerate():
    with patch("yfinance.Ticker", return_value=_fake_ticker()):
        out = revision_momentum("TSLA")
    assert out["recommendation_velocity"] > 0
    assert out["eps_revision_slope"] > 0
    assert "analyst_targets" in out
    assert out["analyst_targets"]["current"] == 150


def test_revision_momentum_handles_broken_ticker():
    with patch("yfinance.Ticker", side_effect=Exception("boom")):
        out = revision_momentum("XYZ")
    assert "error" in out
