from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import numpy as np
import pandas as pd


def test_forecast_ensemble_tool_returns_structure():
    from core.agent.tools import ensemble_tools

    fake_df = pd.DataFrame({
        "Close": 100 + np.arange(200) * 0.1,
        "High": 100 + np.arange(200) * 0.1 + 0.3,
        "Low":  100 + np.arange(200) * 0.1 - 0.3,
        "Open": 100 + np.arange(200) * 0.1,
        "Volume": [1000] * 200,
    }, index=pd.date_range("2026-01-01", periods=200, freq="5min"))

    fake_output = {
        "ticker": "TEST",
        "meta": {
            "prob_up": 0.6, "direction": "up",
            "expected_move_pct": 0.5, "confidence": 0.2,
            "n_forecasters": 2, "source": "vote",
        },
        "forecasters": {
            "kronos": {"close": [100.5], "model_id": "kronos"},
            "chronos": {"error": "unavailable"},
        },
        "pred_len": 12, "interval_minutes": 5, "last_close": 100.0,
    }

    async def run():
        with patch("core.agent.tools.ensemble_tools._fetch_recent_bars", return_value=(fake_df, 5)), \
             patch("core.agent.tools.ensemble_tools.run_ensemble", return_value=fake_output):
            return await ensemble_tools.forecast_ensemble.handler({"ticker": "TEST", "horizon_minutes": 60})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert payload["ticker"] == "TEST"
    assert payload["meta"]["direction"] == "up"
    assert payload["forecasters"]["kronos"]["available"] is True
    assert payload["forecasters"]["chronos"]["available"] is False


def test_forecast_ensemble_tool_rejects_empty_ticker():
    from core.agent.tools import ensemble_tools

    async def run():
        return await ensemble_tools.forecast_ensemble.handler({"ticker": "", "horizon_minutes": 60})

    out = asyncio.run(run())
    payload = json.loads(out["content"][0]["text"])
    assert "error" in payload
