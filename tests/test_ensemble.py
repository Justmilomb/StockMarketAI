from __future__ import annotations

import numpy as np
import pandas as pd

from core.forecasting import ensemble


def _df(bars: int = 128) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=bars, freq="5min")
    close = 100 + np.cumsum(rng.normal(0, 0.5, bars))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 1000},
        index=idx,
    )


def _stub_forecaster(df, interval_minutes, pred_len, **_kw):
    last_close = float(df["close"].iloc[-1])
    return {
        "close": [last_close * 1.01] * pred_len,
        "high": [last_close * 1.015] * pred_len,
        "low":  [last_close * 1.005] * pred_len,
        "timestamps": ["t"] * pred_len,
        "interval_minutes": interval_minutes,
        "pred_len": pred_len,
        "model_id": "stub",
    }


def test_run_ensemble_with_all_stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr("core.kronos_forecaster.forecast", _stub_forecaster)
    monkeypatch.setattr("core.forecasting.chronos_forecaster.forecast", _stub_forecaster)
    monkeypatch.setattr("core.forecasting.timesfm_forecaster.forecast", _stub_forecaster)
    monkeypatch.setattr("core.forecasting.tft_forecaster.forecast",
                        lambda *a, **kw: {"error": "skip"})

    out = ensemble.run_ensemble(
        _df(), interval_minutes=5, pred_len=12, ticker="TEST",
        meta_model_path=tmp_path / "meta.json",
    )
    assert "meta" in out
    assert out["meta"]["n_forecasters"] >= 3
    # Every stubbed forecaster predicted +1% so the ensemble should
    # lean ``up``.
    assert out["meta"]["direction"] in {"up", "flat"}
    assert "kronos" in out["forecasters"]


def test_run_ensemble_with_all_failing(monkeypatch, tmp_path):
    for path in (
        "core.kronos_forecaster.forecast",
        "core.forecasting.chronos_forecaster.forecast",
        "core.forecasting.timesfm_forecaster.forecast",
        "core.forecasting.tft_forecaster.forecast",
    ):
        monkeypatch.setattr(path, lambda *a, **kw: {"error": "x"})

    out = ensemble.run_ensemble(
        _df(), interval_minutes=5, pred_len=12, ticker="TEST",
        meta_model_path=tmp_path / "meta.json",
    )
    assert out["meta"]["n_forecasters"] == 0
    assert out["meta"]["direction"] == "flat"
