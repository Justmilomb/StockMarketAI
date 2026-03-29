"""Crypto-tuned ML ensemble.

Composes from the existing ``EnsembleModel`` class with crypto-appropriate
hyperparameters: deeper trees, more estimators for the higher volatility
and 24/7 nature of crypto markets. Models are saved in ``models/crypto/ensemble/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List

from types_shared import EnsembleConfig, ModelSpec

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Crypto-specific model diversity matrix
#
# Compared to stocks:
# - Deeper trees (crypto has more noise, need capacity)
# - More estimators (larger ensembles smooth out volatility)
# - Tighter regularisation for boosting (prevent overfitting to spikes)
# - Includes the 'crypto' feature group
# ---------------------------------------------------------------------------

def _spec(name: str, model_type: str, group: str, **hp: float | int | str | bool) -> ModelSpec:
    """Shorthand constructor for model specs."""
    return ModelSpec(name=name, model_type=model_type, feature_group=group, hyperparams=dict(hp))


CRYPTO_MODEL_SPECS: List[ModelSpec] = [
    _spec("rf_all",          "RandomForest",       "all",               n_estimators=400, max_depth=14),
    _spec("rf_trend_crypto", "RandomForest",       "trend+crypto",      n_estimators=250, max_depth=12),
    _spec("rf_momentum",     "RandomForest",       "momentum",          n_estimators=200, max_depth=10),
    _spec("xgb_all",         "XGBoost",            "all",               n_estimators=300, max_depth=8, learning_rate=0.05),
    _spec("xgb_vol_crypto",  "XGBoost",            "volatility+crypto", n_estimators=200, max_depth=6, learning_rate=0.08),
    _spec("lgbm_all",        "LightGBM",           "all",               n_estimators=300, num_leaves=48),
    _spec("lgbm_mom_crypto", "LightGBM",           "momentum+crypto",   n_estimators=200, num_leaves=24),
    _spec("lr_all",          "LogisticRegression",  "all",               C=0.5),
    _spec("svm_vol",         "SVM",                "volatility",        C=1.0, probability=True),
    _spec("knn_momentum",    "KNN",                "momentum",          n_neighbors=15),
    _spec("rf_volume",       "RandomForest",       "volume",            n_estimators=150, max_depth=8),
    _spec("rf_crypto",       "RandomForest",       "crypto",            n_estimators=200, max_depth=10),
]


def get_crypto_ensemble_config(
    config: Dict[str, object] | None = None,
) -> EnsembleConfig:
    """Build an EnsembleConfig for crypto, reading overrides from config dict."""
    cfg = config or {}
    return EnsembleConfig(
        n_models=int(cfg.get("n_models", 8)),
        stacking_enabled=bool(cfg.get("stacking_enabled", True)),
        performance_lookback_days=int(cfg.get("performance_lookback_days", 60)),
        min_model_weight=float(cfg.get("min_model_weight", 0.02)),
        model_dir=str(cfg.get("model_dir", "models/crypto/ensemble")),
    )


def generate_crypto_specs(
    n_models: int = 8,
) -> List[ModelSpec]:
    """Return the crypto diversity matrix, filtered to available libraries.

    Mirrors ``ensemble.generate_diverse_specs`` but uses crypto hyperparams.
    """
    from ensemble import _OPTIONAL_TYPES

    available: List[ModelSpec] = []
    for spec in CRYPTO_MODEL_SPECS:
        if spec.model_type in _OPTIONAL_TYPES and not _OPTIONAL_TYPES[spec.model_type]:
            logger.warning(
                "Skipping crypto model '%s' -- %s is not installed",
                spec.name,
                spec.model_type,
            )
            continue
        available.append(spec)

    return available[:n_models]


def create_crypto_ensemble():  # noqa: ANN201
    """Factory: create an EnsembleModel pre-configured for crypto.

    Returns an ``EnsembleModel`` instance with crypto-specific config.
    The caller should provide crypto feature columns when calling
    ``ensemble.train()`` and ``ensemble.predict_all()``.
    """
    from ensemble import EnsembleModel

    config = get_crypto_ensemble_config()
    model = EnsembleModel(config=config)
    return model
