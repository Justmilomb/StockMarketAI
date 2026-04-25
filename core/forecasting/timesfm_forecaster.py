"""TimesFM (Google) forecaster wrapper.

Uses the PyTorch TimesFM 2.0 checkpoint. Same contract as every other
forecaster: ``forecast(hist_df, interval_minutes, pred_len) -> dict``.
Univariate — high/low derived from close via recent ratio (same trick
as Chronos).
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_MODEL: Optional[Any] = None

MODEL_ID: str = "google/timesfm-2.0-500m-pytorch"


def _get_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        from core.hf_auth import apply_read_token
        # TimesFM reads HUGGING_FACE_HUB_TOKEN from the env directly.
        apply_read_token()
        import timesfm
        logger.info("timesfm: loading %s", MODEL_ID)
        _MODEL = timesfm.TimesFm(
            hparams=timesfm.TimesFmHparams(
                backend="cpu",
                per_core_batch_size=32,
                horizon_len=128,
                num_layers=50,
                use_positional_embedding=False,
                context_len=2048,
            ),
            checkpoint=timesfm.TimesFmCheckpoint(huggingface_repo_id=MODEL_ID),
        )
        return _MODEL


def forecast(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
) -> Dict[str, Any]:
    if hist_df is None or len(hist_df) < 64:
        return {"error": "need at least 64 historical bars"}
    cols = {c.lower() for c in hist_df.columns}
    if "close" not in cols:
        return {"error": "missing close column"}
    hist = hist_df.copy()
    hist.columns = [c.lower() for c in hist.columns]
    series = hist["close"].to_numpy(dtype=float)

    try:
        model = _get_model()
        forecast_arr, _ = model.forecast(
            inputs=[series],
            # 0 = high-frequency granularity in TimesFM's freq enum; OK
            # for intraday minute bars.
            freq=[0],
        )
        closes_full = np.asarray(forecast_arr[0], dtype=float)
        closes = [float(x) for x in closes_full[:pred_len].tolist()]
    except Exception as e:
        logger.warning("timesfm: forecast failed: %s", e)
        return {"error": f"forecast failed: {e}"}

    # Pad in case the model returned fewer steps than requested.
    while len(closes) < pred_len:
        closes.append(closes[-1] if closes else float(series[-1]))

    tail = hist.tail(32)
    high_ratio = float((tail["high"] / tail["close"]).mean()) if "high" in tail else 1.005
    low_ratio = float((tail["low"] / tail["close"]).mean()) if "low" in tail else 0.995

    last_ts = pd.to_datetime(hist.index[-1])
    step = timedelta(minutes=interval_minutes)
    timestamps = [(last_ts + step * (i + 1)).isoformat() for i in range(pred_len)]

    return {
        "timestamps": timestamps,
        "close": closes,
        "high": [c * high_ratio for c in closes],
        "low": [c * low_ratio for c in closes],
        "interval_minutes": interval_minutes,
        "pred_len": pred_len,
        "model_id": MODEL_ID,
    }
