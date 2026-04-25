"""FinBERT sentiment pipeline — ProsusAI/finbert via HuggingFace.

Lazy singleton. First call loads the ~440 MB model and caches it in the
HuggingFace cache dir. Never raises — returns empty list if the model
can't load (e.g. offline, transformers missing).

Compound score normalisation: FinBERT returns one of {positive, negative,
neutral} with a confidence. We convert to a single scalar in [-1, 1]:

    positive:  +score
    negative:  -score
    neutral:    0
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL_ID: str = "ProsusAI/finbert"
_LOCK = threading.Lock()
_PIPELINE: Optional[Any] = None


def _get_pipeline() -> Optional[Any]:
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    with _LOCK:
        if _PIPELINE is not None:
            return _PIPELINE
        try:
            from core.hf_auth import apply_read_token, read_token
            from core.local_models import resolve
            from transformers import pipeline as hf_pipeline
            apply_read_token()
            token = read_token()
            kwargs = {"token": token} if token else {}
            src = resolve("finbert", MODEL_ID)
            _PIPELINE = hf_pipeline(
                "sentiment-analysis", model=src, tokenizer=src,
                device=-1, framework="pt", **kwargs,
            )
        except Exception as e:
            logger.info("finbert: pipeline init failed: %s", e)
            _PIPELINE = None
        return _PIPELINE


def is_available() -> bool:
    return _get_pipeline() is not None


def score_texts(texts: List[str], max_texts: int = 32) -> List[Dict[str, Any]]:
    """Score each text with FinBERT. Returns list of ``{label, score, compound}``."""
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    if not texts:
        return []
    pipe = _get_pipeline()
    if pipe is None:
        return []
    texts = texts[:max_texts]
    try:
        raw = pipe(texts, truncation=True, max_length=256)
    except Exception as e:
        logger.info("finbert: scoring failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for r in raw:
        label = str(r.get("label", "")).lower()
        score = float(r.get("score", 0.0))
        compound = score if label == "positive" else (-score if label == "negative" else 0.0)
        out.append({"label": label, "score": score, "compound": compound})
    return out


def aggregate_compound(scores: List[Dict[str, Any]]) -> float:
    """Mean compound score across a batch, clamped to [-1, 1]."""
    if not scores:
        return 0.0
    total = sum(float(s.get("compound", 0.0)) for s in scores)
    return max(-1.0, min(1.0, total / len(scores)))
