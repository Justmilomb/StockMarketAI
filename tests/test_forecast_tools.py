"""forecast_candles MCP tool — pipes yfinance bars into Kronos wrapper."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _fake_bars(n: int = 80, interval_min: int = 5) -> pd.DataFrame:
    now = datetime.now()
    idx = [now - timedelta(minutes=interval_min * (n - i)) for i in range(n)]
    return pd.DataFrame({
        "Open":   [100 + i * 0.1 for i in range(n)],
        "High":   [101 + i * 0.1 for i in range(n)],
        "Low":    [99 + i * 0.1 for i in range(n)],
        "Close":  [100 + i * 0.1 for i in range(n)],
        "Volume": [1000] * n,
    }, index=pd.DatetimeIndex(idx))


def test_forecast_returns_prediction_summary() -> None:
    from core.agent.tools import forecast_tools

    async def run() -> dict:
        with (
            patch.object(forecast_tools, "_fetch_recent_bars", return_value=(_fake_bars(), 5)),
            patch("core.kronos_forecaster.forecast", return_value={
                "timestamps": ["2026-04-18T14:00:00"],
                "close": [110.0], "high": [111.0], "low": [109.0],
                "interval_minutes": 5, "pred_len": 1, "model_id": "test",
            }),
        ):
            result = await forecast_tools.forecast_candles.handler({
                "ticker": "AAPL", "pred_minutes": 60,
            })
            return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert out["ticker"] == "AAPL"
    assert out["predicted_close"] == [110.0]
    assert out["summary"]["final_close"] == 110.0


def test_forecast_rejects_blank_ticker() -> None:
    from core.agent.tools import forecast_tools

    async def run() -> dict:
        result = await forecast_tools.forecast_candles.handler({"ticker": "", "pred_minutes": 60})
        return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out


def test_forecast_rejects_bad_horizon() -> None:
    from core.agent.tools import forecast_tools

    async def run() -> dict:
        result = await forecast_tools.forecast_candles.handler({"ticker": "AAPL", "pred_minutes": 9999})
        return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out


def test_forecast_reports_fetch_failure() -> None:
    from core.agent.tools import forecast_tools

    def boom(*_a, **_k):
        raise RuntimeError("network down")

    async def run() -> dict:
        with patch.object(forecast_tools, "_fetch_recent_bars", side_effect=boom):
            result = await forecast_tools.forecast_candles.handler({
                "ticker": "AAPL", "pred_minutes": 60,
            })
            return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out
    assert out["ticker"] == "AAPL"


def test_forecast_requires_enough_history() -> None:
    from core.agent.tools import forecast_tools

    async def run() -> dict:
        with patch.object(forecast_tools, "_fetch_recent_bars",
                          return_value=(_fake_bars(n=10), 5)):
            result = await forecast_tools.forecast_candles.handler({
                "ticker": "AAPL", "pred_minutes": 60,
            })
            return json.loads(result["content"][0]["text"])

    out = asyncio.run(run())
    assert "error" in out
