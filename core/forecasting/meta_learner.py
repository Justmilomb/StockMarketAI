"""XGBoost meta-learner over forecaster outputs.

Input: a dict ``{forecaster_name: forecaster_output_dict}`` from
Kronos / Chronos / TimesFM / TFT. Output: a blended
``{"prob_up", "direction", "expected_move_pct", "confidence"}`` signal.

Training data is accumulated over time by the ``MetaLearner.record()``
hook — every forecast made at time t, paired with the realised close
delta at t+pred_len, becomes one training row. Until we have at least
50 rows the model falls back to equal-weighted voting so the ensemble
is functional on day 1.

Model is persisted to ``models/meta_learner.json`` (xgboost json format)
so retraining is incremental across terminal restarts.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Names of every forecaster the meta-learner knows about. New names
#: added here propagate to feature columns automatically.
KNOWN_FORECASTERS: List[str] = ["kronos", "chronos", "timesfm", "tft"]

MIN_TRAIN_ROWS: int = 50


def _safe_pct(closes: List[float], last_close: float) -> float:
    if not closes or last_close <= 0:
        return 0.0
    return (closes[-1] / last_close) - 1.0


def _safe_max_pct(closes: List[float], last_close: float) -> float:
    if not closes or last_close <= 0:
        return 0.0
    return (max(closes) / last_close) - 1.0


def _safe_min_pct(closes: List[float], last_close: float) -> float:
    if not closes or last_close <= 0:
        return 0.0
    return (min(closes) / last_close) - 1.0


def build_features(
    forecaster_outputs: Dict[str, Dict[str, Any]],
    last_close: float,
) -> Dict[str, float]:
    """Flatten forecaster dicts into a float feature row.

    For every known forecaster we emit four columns so the feature
    vector has a fixed shape even when some backends fail:
      * ``<name>_pct_final``   — last predicted close / last historical - 1
      * ``<name>_pct_max``
      * ``<name>_pct_min``
      * ``<name>_present``     — 1 if the forecaster returned data, else 0
    """
    feats: Dict[str, float] = {}
    for name in KNOWN_FORECASTERS:
        out = forecaster_outputs.get(name) or {}
        closes = out.get("close") if isinstance(out, dict) else None
        if isinstance(closes, list) and closes and "error" not in out:
            feats[f"{name}_pct_final"] = _safe_pct(closes, last_close)
            feats[f"{name}_pct_max"] = _safe_max_pct(closes, last_close)
            feats[f"{name}_pct_min"] = _safe_min_pct(closes, last_close)
            feats[f"{name}_present"] = 1.0
        else:
            feats[f"{name}_pct_final"] = 0.0
            feats[f"{name}_pct_max"] = 0.0
            feats[f"{name}_pct_min"] = 0.0
            feats[f"{name}_present"] = 0.0
    return feats


class MetaLearner:
    """XGBoost classifier over forecaster features."""

    def __init__(self, model_path: str | Path = "models/meta_learner.json") -> None:
        self._path = Path(model_path)
        self._lock = threading.Lock()
        self._model: Optional[Any] = None
        self._history: List[Dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            import xgboost as xgb
            self._model = xgb.XGBClassifier()
            self._model.load_model(str(self._path))
        except Exception as e:
            logger.info("meta_learner: load failed (%s); will fall back to voting", e)
            self._model = None

    def save(self) -> None:
        if self._model is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._model.save_model(str(self._path))
        except Exception as e:
            logger.warning("meta_learner: save failed: %s", e)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def record(
        self,
        forecaster_outputs: Dict[str, Dict[str, Any]],
        last_close: float,
        realised_close: float,
    ) -> None:
        """Append one (features, label) row to the training buffer."""
        if last_close <= 0 or realised_close <= 0:
            return
        label = 1 if realised_close > last_close else 0
        feats = build_features(forecaster_outputs, last_close)
        feats["__label"] = float(label)
        with self._lock:
            self._history.append(feats)

    def fit(self) -> bool:
        """Fit an XGBoost classifier from buffered rows. Returns True if trained."""
        with self._lock:
            rows = list(self._history)
        if len(rows) < MIN_TRAIN_ROWS:
            return False
        try:
            import xgboost as xgb
        except Exception:
            return False
        feature_cols = [k for k in sorted(rows[0]) if k != "__label"]
        X = np.array([[r[k] for k in feature_cols] for r in rows], dtype=float)
        y = np.array([r["__label"] for r in rows], dtype=int)
        model = xgb.XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            objective="binary:logistic", eval_metric="logloss",
            verbosity=0, n_jobs=1,
        )
        model.fit(X, y)
        self._model = model
        self.save()
        return True

    # ------------------------------------------------------------------
    # Predict
    # ------------------------------------------------------------------

    def predict(
        self,
        forecaster_outputs: Dict[str, Dict[str, Any]],
        last_close: float,
    ) -> Dict[str, Any]:
        feats = build_features(forecaster_outputs, last_close)
        n_present = sum(1 for k, v in feats.items() if k.endswith("_present") and v > 0)
        final_moves = [
            v for k, v in feats.items()
            if k.endswith("_pct_final")
            and feats.get(k.replace("_pct_final", "_present"), 0) > 0
        ]

        if self._model is not None:
            try:
                X = np.array([[feats[k] for k in sorted(feats)]], dtype=float)
                proba = float(self._model.predict_proba(X)[0, 1])
                source = "xgb"
            except Exception as e:
                logger.info("meta_learner: predict failed (%s); voting fallback", e)
                proba = _vote_proba(final_moves)
                source = "vote_fallback"
        else:
            proba = _vote_proba(final_moves)
            source = "vote_cold_start"

        expected_move = float(np.mean(final_moves)) if final_moves else 0.0
        if proba > 0.55:
            direction = "up"
        elif proba < 0.45:
            direction = "down"
        else:
            direction = "flat"

        return {
            "prob_up": round(proba, 4),
            "direction": direction,
            "expected_move_pct": round(expected_move * 100, 4),
            "confidence": round(abs(proba - 0.5) * 2, 4),
            "n_forecasters": n_present,
            "source": source,
        }


def _vote_proba(final_moves: List[float]) -> float:
    """Cold-start: each forecaster votes ``up`` iff its predicted move > 0."""
    if not final_moves:
        return 0.5
    up_votes = sum(1 for m in final_moves if m > 0)
    return up_votes / len(final_moves)
