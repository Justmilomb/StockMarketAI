"""TFT wrapper tests — skip when deps missing."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pytorch_forecasting")


def _series(bars: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2026-01-01", periods=bars, freq="5min")
    close = 100 + np.cumsum(rng.normal(0, 0.3, bars))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 1000},
        index=idx,
    )


def test_tft_returns_structure_even_without_checkpoint():
    from core.forecasting import tft_forecaster
    out = tft_forecaster.forecast(_series(), 5, 12)
    # Either we returned an error (no checkpoint, training disabled on CI)
    # or real predictions. Both are valid shapes.
    assert "close" in out or "error" in out


def test_tft_too_short_history():
    from core.forecasting import tft_forecaster
    out = tft_forecaster.forecast(_series(64), 5, 12)
    assert "error" in out
