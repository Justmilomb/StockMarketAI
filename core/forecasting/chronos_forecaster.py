"""Chronos-2 forecaster wrapper.

Amazon Chronos-2 is a zero-shot forecasting foundation model
(github.com/amazon-science/chronos-forecasting). We treat it the same
way Kronos is treated in ``core.kronos_forecaster``: lazy singleton,
CPU-safe, never raise.

Chronos is univariate — it predicts only the close series. We extrapolate
high/low bands by scaling the predicted close by the historical
high/low-to-close ratio so downstream code can treat Chronos output
interchangeably with Kronos.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_PIPELINE: Optional[Any] = None

MODEL_ID: str = "amazon/chronos-t5-small"


def _get_pipeline() -> Any:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    with _MODEL_LOCK:
        if _PIPELINE is not None:
            return _PIPELINE
        import torch
        from chronos import ChronosPipeline

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("chronos: loading %s on %s", MODEL_ID, device)
        _PIPELINE = ChronosPipeline.from_pretrained(
            MODEL_ID,
            device_map=device,
            torch_dtype=torch.float32,
        )
        return _PIPELINE


def forecast(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
    num_samples: int = 20,
) -> Dict[str, Any]:
    """Forecast the next ``pred_len`` bars via Chronos-2.

    Contract identical to ``core.kronos_forecaster.forecast`` so the
    ensemble can treat every backend interchangeably.
    """
    if hist_df is None or len(hist_df) < 64:
        return {"error": "need at least 64 historical bars"}
    cols = {c.lower() for c in hist_df.columns}
    if "close" not in cols:
        return {"error": "missing close column"}
    hist = hist_df.copy()
    hist.columns = [c.lower() for c in hist.columns]

    try:
        import torch

        pipeline = _get_pipeline()
        context = torch.tensor(hist["close"].to_numpy(dtype=float))
        samples = pipeline.predict(
            context=context,
            prediction_length=pred_len,
            num_samples=num_samples,
        )
        median = samples[0].median(dim=0).values.cpu().numpy()
    except Exception as e:
        logger.warning("chronos: forecast failed: %s", e)
        return {"error": f"forecast failed: {e}"}

    tail = hist.tail(32)
    high_ratio = float((tail["high"] / tail["close"]).mean()) if "high" in tail else 1.005
    low_ratio = float((tail["low"] / tail["close"]).mean()) if "low" in tail else 0.995

    closes = [float(x) for x in median.tolist()]
    highs = [c * high_ratio for c in closes]
    lows = [c * low_ratio for c in closes]

    last_ts = pd.to_datetime(hist.index[-1])
    step = timedelta(minutes=interval_minutes)
    timestamps = [(last_ts + step * (i + 1)).isoformat() for i in range(pred_len)]

    return {
        "timestamps": timestamps,
        "close": closes,
        "high": highs,
        "low": lows,
        "interval_minutes": interval_minutes,
        "pred_len": pred_len,
        "model_id": MODEL_ID,
    }
