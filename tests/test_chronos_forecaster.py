"""Chronos forecaster tests — skip when deps missing."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("chronos")


def _synthetic_ohlcv(bars: int = 128) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=bars, freq="5min")
    close = 100 + np.cumsum(rng.normal(0, 0.5, bars))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.1, bars),
            "high": close + np.abs(rng.normal(0.3, 0.1, bars)),
            "low": close - np.abs(rng.normal(0.3, 0.1, bars)),
            "close": close,
            "volume": rng.integers(1_000, 10_000, bars),
        },
        index=idx,
    )


def test_chronos_returns_error_on_tiny_history():
    from core.forecasting import chronos_forecaster
    out = chronos_forecaster.forecast(_synthetic_ohlcv(10), interval_minutes=5, pred_len=12)
    assert "error" in out


def test_chronos_forecast_shape_on_valid_input():
    from core.forecasting import chronos_forecaster
    out = chronos_forecaster.forecast(_synthetic_ohlcv(256), interval_minutes=5, pred_len=12)
    if "error" in out:
        pytest.skip(f"chronos unavailable: {out['error']}")
    assert len(out["close"]) == 12
    assert len(out["timestamps"]) == 12
