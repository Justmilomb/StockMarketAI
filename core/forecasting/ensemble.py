"""Ensemble orchestrator — fan out to every enabled forecaster, blend via MetaLearner."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from core.forecasting.meta_learner import MetaLearner

logger = logging.getLogger(__name__)


def _safe_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        logger.warning("ensemble: forecaster raised: %s", e)
        return {"error": str(e)}


def run_ensemble(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
    ticker: str = "generic",
    enabled: Optional[Dict[str, bool]] = None,
    meta_model_path: str | Path = "models/meta_learner.json",
) -> Dict[str, Any]:
    """Run every enabled forecaster, feed outputs to the meta-learner.

    Returns a dict with ``forecasters`` (raw per-model outputs) and
    ``meta`` (blended signal). Any backend that raises or returns
    ``{"error": ...}`` is simply excluded from the blend — the
    ensemble keeps working as long as at least one forecaster returned
    usable data.
    """
    # Lazy imports so a missing backend dep only disables that wrapper,
    # not the entire ensemble module.
    from core.kronos_forecaster import forecast as kronos_fc
    from core.forecasting.chronos_forecaster import forecast as chronos_fc
    from core.forecasting.timesfm_forecaster import forecast as timesfm_fc
    from core.forecasting.tft_forecaster import forecast as tft_fc

    enabled = enabled or {"kronos": True, "chronos": True, "timesfm": True, "tft": True}

    outputs: Dict[str, Dict[str, Any]] = {}
    if enabled.get("kronos"):
        outputs["kronos"] = _safe_call(kronos_fc, hist_df, interval_minutes, pred_len)
    if enabled.get("chronos"):
        outputs["chronos"] = _safe_call(chronos_fc, hist_df, interval_minutes, pred_len)
    if enabled.get("timesfm"):
        outputs["timesfm"] = _safe_call(timesfm_fc, hist_df, interval_minutes, pred_len)
    if enabled.get("tft"):
        outputs["tft"] = _safe_call(tft_fc, hist_df, interval_minutes, pred_len, ticker=ticker)

    close_series = hist_df["close"] if "close" in hist_df.columns else hist_df["Close"]
    last_close = float(close_series.iloc[-1])
    meta = MetaLearner(model_path=meta_model_path).predict(outputs, last_close=last_close)

    return {
        "ticker": ticker,
        "pred_len": pred_len,
        "interval_minutes": interval_minutes,
        "last_close": last_close,
        "forecasters": outputs,
        "meta": meta,
    }
