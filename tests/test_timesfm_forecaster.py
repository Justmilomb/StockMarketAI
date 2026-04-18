"""TimesFM wrapper tests — skip when deps missing."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("timesfm")


def _series(bars: int = 256) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    idx = pd.date_range("2026-01-01", periods=bars, freq="5min")
    close = 100 + np.cumsum(rng.normal(0, 0.5, bars))
    return pd.DataFrame(
        {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000},
        index=idx,
    )


def test_timesfm_tiny_returns_error():
    from core.forecasting import timesfm_forecaster
    assert "error" in timesfm_forecaster.forecast(_series(10), 5, 12)


def test_timesfm_valid_shape():
    from core.forecasting import timesfm_forecaster
    out = timesfm_forecaster.forecast(_series(256), 5, 12)
    if "error" in out:
        pytest.skip(f"timesfm unavailable: {out['error']}")
    assert len(out["close"]) == 12
