"""Temporal Fusion Transformer (TFT) forecaster wrapper.

We use pytorch-forecasting's TemporalFusionTransformer with a very
small config (attention_head_size=4, hidden_size=32). Training happens
on demand per ticker and the checkpoint is cached to
``models/tft/<ticker>.ckpt``. A single quick-fit takes 1-2 minutes on
CPU for 400 bars; subsequent forecasts for the same ticker are sub-second.

Why train-on-demand? pytorch-forecasting TFT has no public
foundation-model checkpoint — every real deployment trains per dataset.
Caching one per ticker gets us zero-shot-ish behaviour for the agent
while keeping the dep honest.

If training/inference raises for any reason the wrapper returns an
``error`` field so the meta-learner can ignore the backend this round.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MODEL_ID: str = "pytorch-forecasting.TemporalFusionTransformer"
_CACHE_DIR = Path("models/tft")
_LOCK = threading.Lock()


def _ckpt_path(ticker: str) -> Path:
    safe = ticker.upper().replace("/", "_").replace("\\", "_")
    return _CACHE_DIR / f"{safe}.ckpt"


def _fit_and_save(series: np.ndarray, ckpt: Path) -> Optional[Any]:
    try:
        from pytorch_forecasting import TemporalFusionTransformer, TimeSeriesDataSet
        from pytorch_forecasting.data import GroupNormalizer
        import pytorch_lightning as pl
    except Exception as e:
        logger.info("tft: deps missing: %s", e)
        return None

    df = pd.DataFrame({
        "time_idx": np.arange(len(series)),
        "value": series.astype(float),
        "group": "x",
    })
    max_prediction = 24
    max_encoder = 96

    try:
        training = TimeSeriesDataSet(
            df,
            time_idx="time_idx",
            target="value",
            group_ids=["group"],
            max_encoder_length=max_encoder,
            max_prediction_length=max_prediction,
            static_categoricals=["group"],
            time_varying_unknown_reals=["value"],
            target_normalizer=GroupNormalizer(groups=["group"]),
        )
        dataloader = training.to_dataloader(train=True, batch_size=32, num_workers=0)
        model = TemporalFusionTransformer.from_dataset(
            training,
            hidden_size=32,
            attention_head_size=4,
            dropout=0.1,
            hidden_continuous_size=16,
            output_size=7,
            log_interval=0,
            reduce_on_plateau_patience=4,
        )
        trainer = pl.Trainer(
            max_epochs=3, enable_checkpointing=False, logger=False,
            enable_progress_bar=False, accelerator="cpu",
        )
        trainer.fit(model, train_dataloaders=dataloader)
        ckpt.parent.mkdir(parents=True, exist_ok=True)
        trainer.save_checkpoint(str(ckpt))
        return model
    except Exception as e:
        logger.warning("tft: fit failed: %s", e)
        return None


def _load_model(ckpt: Path) -> Optional[Any]:
    try:
        from pytorch_forecasting import TemporalFusionTransformer
        return TemporalFusionTransformer.load_from_checkpoint(str(ckpt))
    except Exception as e:
        logger.info("tft: load failed (%s); will retrain", e)
        return None


def forecast(
    hist_df: pd.DataFrame,
    interval_minutes: int,
    pred_len: int,
    ticker: str = "generic",
) -> Dict[str, Any]:
    if hist_df is None or len(hist_df) < 128:
        return {"error": "need at least 128 historical bars for tft"}
    cols = {c.lower() for c in hist_df.columns}
    if "close" not in cols:
        return {"error": "missing close column"}
    hist = hist_df.copy()
    hist.columns = [c.lower() for c in hist.columns]
    series = hist["close"].to_numpy(dtype=float)

    ckpt = _ckpt_path(ticker)
    with _LOCK:
        model = _load_model(ckpt) if ckpt.exists() else None
        if model is None:
            model = _fit_and_save(series, ckpt)
    if model is None:
        return {"error": "tft_not_trained"}

    try:
        preds = model.predict(
            pd.DataFrame({
                "time_idx": np.arange(len(series)),
                "value": series,
                "group": "x",
            }),
            mode="prediction",
        )
        closes_arr = np.asarray(preds).reshape(-1)[:pred_len]
        closes = [float(x) for x in closes_arr.tolist()]
    except Exception as e:
        logger.warning("tft: predict failed: %s", e)
        return {"error": f"predict failed: {e}"}

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
