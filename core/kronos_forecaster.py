"""Kronos forecaster — pre-sell price-forecast gate.

Wraps the vendored ``core.kronos`` model with lazy, process-wide
caching so the 100 MB model is loaded at most once. ``forecast``
takes the ticker's recent intraday bars and returns predicted close
/ high / low series for the next N minutes.

Design
------

* Lazy load — import torch only when first forecast is requested.
* Singleton — one (tokenizer, model, predictor) tuple per process.
* CPU-only by default; if a CUDA device is visible it'll use it.
* Forecast failures (missing data, torch OOM, HTTPError from HF) are
  caught and surfaced as ``{"error": "..."}`` dicts rather than
  propagating — the agent should *hold* when forecasting fails, not
  crash the loop.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_MODEL_LOCK = threading.Lock()
_PREDICTOR: Optional[Any] = None

#: Default HF identifiers. Kronos-small is 24.7M params — fast and
#: cheap on CPU. Kronos-base (102M) is higher quality but slower.
TOKENIZER_ID: str = "NeoQuasar/Kronos-Tokenizer-base"
MODEL_ID: str = "NeoQuasar/Kronos-small"


def _get_predictor() -> Any:
    global _PREDICTOR
    if _PREDICTOR is not None:
        return _PREDICTOR
    with _MODEL_LOCK:
        if _PREDICTOR is not None:
            return _PREDICTOR
        from core.hf_auth import apply_read_token, read_token
        from core.kronos import Kronos, KronosTokenizer, KronosPredictor
        apply_read_token()
        token = read_token()
        kwargs = {"token": token} if token else {}
        logger.info("kronos: loading tokenizer %s", TOKENIZER_ID)
        tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID, **kwargs)
        logger.info("kronos: loading model %s", MODEL_ID)
        model = Kronos.from_pretrained(MODEL_ID, **kwargs)
        _PREDICTOR = KronosPredictor(model, tokenizer, max_context=512)
        logger.info("kronos: predictor ready")
        return _PREDICTOR


def forecast(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
    sample_count: int = 1,
    temperature: float = 1.0,
    top_p: float = 0.9,
) -> Dict[str, Any]:
    """Forecast the next ``pred_len`` candles.

    Args:
        hist_df: DataFrame indexed by timestamp with columns
            ``open``, ``high``, ``low``, ``close``, ``volume``.
            Must have at least 64 rows.
        interval_minutes: bar width in minutes (matches hist_df's
            spacing — 5 for 5-minute bars, etc.).
        pred_len: number of future candles to predict.
        sample_count: ensemble size. 1 is usually enough.
        temperature, top_p: sampling knobs.

    Returns:
        Dict with ``close``, ``high``, ``low`` lists + a ``timestamps``
        list for the predicted bars, or ``{"error": ...}`` on failure.
    """
    if hist_df is None or len(hist_df) < 64:
        return {"error": "need at least 64 historical bars for forecasting"}

    hist = hist_df.copy()
    required = {"open", "high", "low", "close"}
    if not required.issubset({c.lower() for c in hist.columns}):
        return {"error": f"missing required OHLC columns: {required}"}
    hist.columns = [c.lower() for c in hist.columns]
    if "volume" not in hist.columns:
        hist["volume"] = 0.0

    x_timestamp = pd.Series(hist.index, index=hist.index)
    last_ts = pd.to_datetime(hist.index[-1])
    step = timedelta(minutes=interval_minutes)
    y_timestamp = pd.Series(
        [last_ts + step * (i + 1) for i in range(pred_len)]
    )

    try:
        predictor = _get_predictor()
        pred_df = predictor.predict(
            df=hist[["open", "high", "low", "close", "volume"]],
            x_timestamp=x_timestamp,
            y_timestamp=y_timestamp,
            pred_len=pred_len,
            T=temperature,
            top_p=top_p,
            sample_count=sample_count,
            verbose=False,
        )
    except Exception as e:
        logger.warning("kronos: forecast failed: %s", e)
        return {"error": f"forecast failed: {e}"}

    return {
        "timestamps": [ts.isoformat() for ts in y_timestamp],
        "close": [float(x) for x in pred_df["close"].tolist()],
        "high": [float(x) for x in pred_df["high"].tolist()],
        "low": [float(x) for x in pred_df["low"].tolist()],
        "interval_minutes": interval_minutes,
        "pred_len": pred_len,
        "model_id": MODEL_ID,
    }
