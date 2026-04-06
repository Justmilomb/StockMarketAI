"""Multi-model ensemble — the 'quant desk' of 6 diverse models.

Trains, persists, and orchestrates a heterogeneous ensemble of classifiers
(RandomForest, XGBoost, LightGBM, LogisticRegression, SVM, KNN) across
different feature subsets, then merges their predictions via weighted soft vote.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import asdict
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module=r"sklearn\..*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"sklearn\..*")
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from cpu_config import get_n_jobs
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC

from features_advanced import FEATURE_COLUMNS_V2, get_feature_group_columns
from types_shared import EnsembleConfig, FeatureGroup, ModelSignal, ModelSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation for optional boosting libraries
# ---------------------------------------------------------------------------

_HAS_XGBOOST = False
try:
    from xgboost import XGBClassifier

    _HAS_XGBOOST = True
except ImportError:
    pass

_HAS_LIGHTGBM = False
try:
    from lightgbm import LGBMClassifier

    _HAS_LIGHTGBM = True
except ImportError:
    pass

# Model types that require optional dependencies
_OPTIONAL_TYPES: Dict[str, bool] = {
    "XGBoost": _HAS_XGBOOST,
    "LightGBM": _HAS_LIGHTGBM,
}

# ---------------------------------------------------------------------------
# Default 6-model diversity matrix (one per algorithm type)
# ---------------------------------------------------------------------------

def _spec(name: str, model_type: str, group: str, **hp: float | int | str | bool) -> ModelSpec:
    """Shorthand constructor for the default spec table."""
    return ModelSpec(name=name, model_type=model_type, feature_group=group, hyperparams=dict(hp))


_DEFAULT_SPECS: List[ModelSpec] = [
    _spec("rf_all",          "RandomForest",       "all",               n_estimators=300, max_depth=10),
    _spec("xgb_all",         "XGBoost",            "all",               n_estimators=200, max_depth=6, learning_rate=0.1),
    _spec("lgbm_all",        "LightGBM",           "all",               n_estimators=200, num_leaves=31),
    _spec("lr_all",          "LogisticRegression",  "all",               C=1.0),
    _spec("svm_vol_vol",     "SVM",                "volatility+volume", C=1.0, probability=True),
    _spec("knn_momentum",    "KNN",                "momentum",          n_neighbors=20),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def generate_diverse_specs(
    n_models: int = 6,
    feature_groups: Dict[str, FeatureGroup] | None = None,
) -> List[ModelSpec]:
    """Return the default diversity matrix, filtered to available libraries.

    Args:
        n_models: How many specs to return (first *n_models* from the default
            list, after filtering out unavailable model types).
        feature_groups: Unused in the current implementation but reserved for
            future custom group overrides.

    Returns:
        A list of up to *n_models* ``ModelSpec`` objects.
    """
    available: List[ModelSpec] = []
    for spec in _DEFAULT_SPECS:
        if spec.model_type in _OPTIONAL_TYPES and not _OPTIONAL_TYPES[spec.model_type]:
            logger.warning(
                "Skipping model '%s' — %s is not installed",
                spec.name,
                spec.model_type,
            )
            continue
        available.append(spec)

    return available[:n_models]


def _resolve_feature_columns(group_name: str) -> List[str]:
    """Map a feature-group specifier to the concrete column list.

    Handles ``"all"``, single group names (``"trend"``), and combined groups
    separated by ``+`` (``"trend+momentum"``).
    """
    if group_name == "all":
        return list(FEATURE_COLUMNS_V2)

    if "+" in group_name:
        columns: List[str] = []
        for sub_group in group_name.split("+"):
            columns.extend(get_feature_group_columns(sub_group.strip()))
        return columns

    return get_feature_group_columns(group_name)


def _create_sklearn_model(spec: ModelSpec) -> Any:
    """Factory: instantiate the correct sklearn-compatible estimator.

    This is the single place where ``Any`` is used as return type because the
    concrete class varies at runtime.
    """
    params = dict(spec.hyperparams)
    model_type = spec.model_type

    if model_type == "RandomForest":
        return RandomForestClassifier(
            n_estimators=int(params.get("n_estimators", 200)),
            max_depth=params.get("max_depth"),  # None is valid
            random_state=42,
            n_jobs=get_n_jobs(),
        )

    if model_type == "XGBoost":
        if not _HAS_XGBOOST:
            raise ImportError("XGBoost is required but not installed")
        return XGBClassifier(
            n_estimators=int(params.get("n_estimators", 200)),
            max_depth=int(params.get("max_depth", 6)),
            learning_rate=float(params.get("learning_rate", 0.1)),
            random_state=42,
            eval_metric="logloss",
            n_jobs=get_n_jobs(),
        )

    if model_type == "LightGBM":
        if not _HAS_LIGHTGBM:
            raise ImportError("LightGBM is required but not installed")
        return LGBMClassifier(
            n_estimators=int(params.get("n_estimators", 200)),
            num_leaves=int(params.get("num_leaves", 31)),
            random_state=42,
            n_jobs=get_n_jobs(),
            verbose=-1,
        )

    if model_type == "LogisticRegression":
        return LogisticRegression(
            C=float(params.get("C", 1.0)),
            max_iter=1000,
            random_state=42,
        )

    if model_type == "SVM":
        return SVC(
            C=float(params.get("C", 1.0)),
            probability=bool(params.get("probability", True)),
            random_state=42,
        )

    if model_type == "KNN":
        return KNeighborsClassifier(
            n_neighbors=int(params.get("n_neighbors", 20)),
            n_jobs=get_n_jobs(),
        )

    raise ValueError(f"Unknown model_type '{model_type}'")


def _time_based_split(
    X: pd.DataFrame | np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    train_fraction: float = 0.8,
) -> Tuple[pd.DataFrame | np.ndarray, pd.DataFrame | np.ndarray, np.ndarray, np.ndarray]:
    """Chronological train/validation split using the date column in *meta*."""
    if "date" not in meta.columns:
        raise ValueError("meta DataFrame must contain a 'date' column")

    df = meta.copy()
    df["idx"] = np.arange(len(meta))
    df = df.sort_values("date")

    split_index = int(len(df) * train_fraction)
    train_idx = df["idx"].iloc[:split_index].to_numpy()
    val_idx = df["idx"].iloc[split_index:].to_numpy()

    if isinstance(X, pd.DataFrame):
        return X.iloc[train_idx], X.iloc[val_idx], y[train_idx], y[val_idx]
    return X[train_idx], X[val_idx], y[train_idx], y[val_idx]


def _weighted_soft_vote(predictions: List[Tuple[float, float]]) -> float:
    """Weighted average of (probability, weight) pairs.

    Returns:
        Combined probability in [0, 1].
    """
    total_weight = sum(w for _, w in predictions)
    if total_weight == 0.0:
        return 0.5
    return sum(prob * w for prob, w in predictions) / total_weight


def train_single_model(
    spec: ModelSpec,
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    columns: List[str],
    save_dir: Path | None = None,
) -> Tuple[Any, float]:
    """Train one model from the ensemble on its specific feature subset.

    Args:
        spec: Model specification (type, feature group, hyperparams).
        X: Full feature matrix with columns matching *columns*.
        y: Binary labels.
        meta: DataFrame with ``ticker`` and ``date`` columns.
        columns: Ordered list of column names corresponding to X's columns.
        save_dir: Directory to persist the trained model artefact.
            If *None*, the model is kept in memory only (used during backtesting).

    Returns:
        (trained_model, validation_accuracy)
    """
    # Resolve which feature columns this model uses
    model_columns = _resolve_feature_columns(spec.feature_group)
    col_indices = [columns.index(c) for c in model_columns if c in columns]

    if not col_indices:
        raise ValueError(
            f"Model '{spec.name}' has no overlapping columns with the dataset"
        )

    used_cols = [columns[i] for i in col_indices]
    X_subset = pd.DataFrame(X[:, col_indices], columns=used_cols)

    # Chronological split
    X_train, X_val, y_train, y_val = _time_based_split(X_subset, y, meta)

    # Build and fit
    model = _create_sklearn_model(spec)
    model.fit(X_train, y_train)

    # Validation accuracy
    if len(X_val) > 0:
        y_pred = model.predict(X_val)
        accuracy = float(accuracy_score(y_val, y_pred))
    else:
        accuracy = 0.0
        logger.warning("Model '%s': no validation data — accuracy set to 0", spec.name)

    # Persist model + metadata (skipped when save_dir is None, e.g. backtesting)
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        artefact_path = save_dir / f"{spec.name}.joblib"
        payload = {
            "model": model,
            "spec": asdict(spec),
            "accuracy": accuracy,
            "columns_used": used_cols,
        }
        joblib.dump(payload, artefact_path)
        logger.info(
            "Model '%s' trained — val accuracy %.4f — saved to %s",
            spec.name,
            accuracy,
            artefact_path,
        )
    else:
        logger.info("Model '%s' trained — val accuracy %.4f", spec.name, accuracy)

    return model, accuracy


# ---------------------------------------------------------------------------
# Ensemble class
# ---------------------------------------------------------------------------

# Each trained model is stored as this 4-tuple internally
_ModelEntry = Tuple[ModelSpec, Any, float, List[str]]


class EnsembleModel:
    """Heterogeneous classifier ensemble with weighted soft voting.

    Manages a collection of diverse models that each specialise in a different
    feature subset, then combines their predictions via a performance-weighted
    soft vote.
    """

    def __init__(
        self,
        config: EnsembleConfig | None = None,
        model_overrides: Dict[str, int | float] | None = None,
    ) -> None:
        self._config: EnsembleConfig = config or EnsembleConfig()
        self._model_overrides: Dict[str, int | float] = model_overrides or {}
        self._models: List[_ModelEntry] = []
        self._weights: List[float] = []
        # Cache the most recent per-model predictions for weight updates
        self._last_predictions: Dict[str, Dict[str, float]] = {}  # model_name -> {ticker: prob}

    # ------------------------------------------------------------------
    # Hyperparameter overrides from research agent
    # ------------------------------------------------------------------

    _OVERRIDE_MAP: Dict[str, tuple] = {
        # key_prefix: (model_name_prefix, hyperparam_name)
        "rf_n_estimators": ("rf_", "n_estimators"),
        "rf_max_depth": ("rf_", "max_depth"),
        "xgb_n_estimators": ("xgb_", "n_estimators"),
        "xgb_max_depth": ("xgb_", "max_depth"),
        "xgb_learning_rate": ("xgb_", "learning_rate"),
        "lgbm_n_estimators": ("lgbm_", "n_estimators"),
        "lgbm_num_leaves": ("lgbm_", "num_leaves"),
        "knn_n_neighbors": ("knn_", "n_neighbors"),
    }

    def _apply_overrides(self, specs: List[ModelSpec]) -> None:
        """Apply research agent hyperparameter overrides to model specs."""
        for key, value in self._model_overrides.items():
            mapping = self._OVERRIDE_MAP.get(key)
            if not mapping:
                continue
            prefix, param_name = mapping
            for spec in specs:
                if spec.name.startswith(prefix):
                    spec.hyperparams[param_name] = value

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        meta: pd.DataFrame,
        columns: List[str],
    ) -> None:
        """Train the full ensemble from scratch.

        Generates model specs, trains each one on its feature subset, and
        initialises equal weights.
        """
        specs = generate_diverse_specs(n_models=self._config.n_models)
        if self._model_overrides:
            self._apply_overrides(specs)
        save_dir = Path(self._config.model_dir) if self._config.model_dir else None

        self._models = []
        for spec in specs:
            try:
                model, accuracy = train_single_model(
                    spec=spec,
                    X=X,
                    y=y,
                    meta=meta,
                    columns=columns,
                    save_dir=save_dir,
                )
                model_columns = _resolve_feature_columns(spec.feature_group)
                # Keep only columns that actually exist in the dataset
                valid_columns = [c for c in model_columns if c in columns]
                self._models.append((spec, model, accuracy, valid_columns))
            except Exception:
                logger.exception("Failed to train model '%s' — skipping", spec.name)

        # Equal initial weights
        n = len(self._models)
        self._weights = [1.0 / n] * n if n > 0 else []

        logger.info(
            "Ensemble training complete: %d/%d models succeeded",
            len(self._models),
            len(specs),
        )
        for entry, weight in zip(self._models, self._weights):
            spec, _, acc, _ = entry
            logger.info(
                "  %-20s  type=%-18s  group=%-20s  acc=%.4f  weight=%.4f",
                spec.name,
                spec.model_type,
                spec.feature_group,
                acc,
                weight,
            )

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_all(
        self,
        features_df: pd.DataFrame,
        meta_df: pd.DataFrame,
    ) -> List[ModelSignal]:
        """Run every model individually and return flat signal list.

        Args:
            features_df: DataFrame indexed by ticker, columns are feature names.
            meta_df: DataFrame with ``ticker`` column aligned to *features_df*.

        Returns:
            One ``ModelSignal`` per (model, ticker) combination.
        """
        signals: List[ModelSignal] = []
        tickers: List[str] = list(meta_df["ticker"])
        # Reset prediction cache for this round
        self._last_predictions = {}

        for spec, model, accuracy, model_cols in self._models:
            # Subset features to the columns this model was trained on
            available_cols = [c for c in model_cols if c in features_df.columns]
            if not available_cols:
                logger.warning(
                    "Model '%s' has no matching columns in features_df — skipping",
                    spec.name,
                )
                continue

            X_model = features_df[available_cols].astype(float)

            try:
                probas = model.predict_proba(X_model)
                # predict_proba returns shape (n_samples, n_classes)
                # We want P(class=1) — the "up" probability
                if probas.shape[1] == 2:
                    up_probs = probas[:, 1]
                else:
                    up_probs = probas[:, 0]
            except Exception:
                logger.exception(
                    "predict_proba failed for model '%s' — skipping",
                    spec.name,
                )
                continue

            # Cache predictions for weight updates
            model_preds: Dict[str, float] = {}
            for i, ticker in enumerate(tickers):
                prob = float(up_probs[i])
                model_preds[ticker] = prob
                signals.append(
                    ModelSignal(
                        model_name=spec.name,
                        ticker=ticker,
                        probability=prob,
                        confidence=accuracy,
                        feature_group=spec.feature_group,
                    )
                )
            self._last_predictions[spec.name] = model_preds

        return signals

    def predict_ensemble(
        self,
        features_df: pd.DataFrame,
        meta_df: pd.DataFrame,
    ) -> Tuple[np.ndarray, Dict[str, List[ModelSignal]]]:
        """Weighted soft-vote ensemble prediction.

        Args:
            features_df: DataFrame indexed by ticker, columns are feature names.
            meta_df: DataFrame with ``ticker`` column aligned to *features_df*.

        Returns:
            probabilities: 1-D array of combined up-probabilities, one per ticker.
            per_ticker_signals: Dict mapping ticker to its list of individual
                ``ModelSignal`` objects.
        """
        all_signals = self.predict_all(features_df, meta_df)

        # Group signals by ticker
        per_ticker: Dict[str, List[ModelSignal]] = {}
        for sig in all_signals:
            per_ticker.setdefault(sig.ticker, []).append(sig)

        # Preserve ticker ordering from meta_df
        tickers: List[str] = list(meta_df["ticker"])
        probabilities: List[float] = []

        for ticker in tickers:
            ticker_signals = per_ticker.get(ticker, [])
            if not ticker_signals:
                probabilities.append(0.5)
                continue

            # Build (probability, weight) pairs — look up model weight by name
            model_weight_map = {
                entry[0].name: self._weights[idx]
                for idx, entry in enumerate(self._models)
            }
            vote_pairs: List[Tuple[float, float]] = [
                (sig.probability, model_weight_map.get(sig.model_name, 0.0))
                for sig in ticker_signals
            ]
            probabilities.append(_weighted_soft_vote(vote_pairs))

        return np.array(probabilities, dtype=np.float64), per_ticker

    # ------------------------------------------------------------------
    # Weight updates (online learning)
    # ------------------------------------------------------------------

    def update_weights(self, actual_outcomes: Dict[str, int]) -> None:
        """Reweight models based on recent prediction accuracy.

        Compares each model's cached predictions (from the most recent
        ``predict_all`` call) against the actual binary outcomes, computes
        per-model accuracy, and normalises weights with a floor.

        Args:
            actual_outcomes: Mapping of ticker to actual binary outcome
                (1 = price went up, 0 = didn't).
        """
        if not self._models or not actual_outcomes:
            return

        min_w = self._config.min_model_weight
        raw_weights: List[float] = []

        for spec, _, prev_accuracy, _ in self._models:
            model_preds = self._last_predictions.get(spec.name, {})

            correct = 0
            total = 0
            for ticker, actual in actual_outcomes.items():
                if ticker not in model_preds:
                    continue
                predicted_up = 1 if model_preds[ticker] >= 0.5 else 0
                if predicted_up == actual:
                    correct += 1
                total += 1

            if total > 0:
                recent_acc = correct / total
                # Blend recent performance (70%) with historical accuracy (30%)
                blended = 0.7 * recent_acc + 0.3 * prev_accuracy
            else:
                # No overlap between predictions and outcomes — keep historical
                blended = prev_accuracy

            raw_weights.append(max(blended, min_w))

        # Normalise to sum to 1
        total_weight = sum(raw_weights)
        if total_weight > 0:
            self._weights = [w / total_weight for w in raw_weights]
        else:
            n = len(self._models)
            self._weights = [1.0 / n] * n

        logger.info("Ensemble weights updated: %s", self._weight_summary())

    def _weight_summary(self) -> str:
        """Format a compact summary of current model weights."""
        parts: List[str] = []
        for (spec, _, _, _), w in zip(self._models, self._weights):
            parts.append(f"{spec.name}={w:.3f}")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Persist the entire ensemble to a single joblib file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "config": asdict(self._config),
            "models": [
                {
                    "spec": asdict(spec),
                    "model": model,
                    "accuracy": accuracy,
                    "feature_columns": feature_columns,
                }
                for spec, model, accuracy, feature_columns in self._models
            ],
            "weights": list(self._weights),
        }
        joblib.dump(payload, path)
        logger.info("Ensemble saved to %s (%d models)", path, len(self._models))

    @classmethod
    def load(cls, path: Path) -> EnsembleModel:
        """Load a previously saved ensemble from disk.

        Args:
            path: Path to the joblib file created by :meth:`save`.

        Returns:
            A fully reconstructed ``EnsembleModel`` ready for prediction.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Ensemble file not found at {path}")

        payload: Dict[str, Any] = joblib.load(path)

        config = EnsembleConfig(**payload["config"])
        instance = cls(config=config)

        instance._models = [
            (
                ModelSpec(**entry["spec"]),
                entry["model"],
                entry["accuracy"],
                entry["feature_columns"],
            )
            for entry in payload["models"]
        ]
        instance._weights = payload["weights"]

        logger.info(
            "Ensemble loaded from %s — %d models", path, len(instance._models)
        )
        return instance

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def n_models(self) -> int:
        """Number of successfully trained models in this ensemble."""
        return len(self._models)

    @property
    def model_names(self) -> List[str]:
        """Ordered list of model names currently in the ensemble."""
        return [spec.name for spec, _, _, _ in self._models]

    @property
    def weights(self) -> List[float]:
        """Current model weights (read-only copy)."""
        return list(self._weights)
