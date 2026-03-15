from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report


@dataclass
class ModelConfig:
    n_estimators: int = 200
    max_depth: int | None = None
    random_state: int = 42
    model_path: Path = Path("models") / "rf_tomorrow_up.joblib"
    train_fraction: float = 0.8  # time-based split


def _time_based_split(
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    train_fraction: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Perform a time-based train/validation split using the 'date' column in meta.
    """
    if "date" not in meta.columns:
        raise ValueError("meta DataFrame must contain a 'date' column for time-based split.")

    df = meta.copy()
    df["idx"] = np.arange(len(meta))
    df = df.sort_values("date")

    split_index = int(len(df) * train_fraction)
    train_idx = df["idx"].iloc[:split_index].to_numpy()
    val_idx = df["idx"].iloc[split_index:].to_numpy()

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    return X_train, X_val, y_train, y_val


def train_model(
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    config: ModelConfig | None = None,
) -> RandomForestClassifier:
    """
    Train a RandomForestClassifier to predict whether tomorrow's close
    will be higher than today's (binary classification).
    """
    if config is None:
        config = ModelConfig()

    X_train, X_val, y_train, y_val = _time_based_split(
        X=X,
        y=y,
        meta=meta,
        train_fraction=config.train_fraction,
    )

    clf = RandomForestClassifier(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        random_state=config.random_state,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    if len(X_val) > 0:
        y_pred = clf.predict(X_val)
        acc = accuracy_score(y_val, y_pred)
        print(f"[model] Validation accuracy: {acc:.4f}")
        print("[model] Classification report:")
        print(classification_report(y_val, y_pred, digits=4))
    else:
        print("[model] Skipped validation: not enough data for a hold-out set.")

    # Persist model
    config.model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": clf, "config": config.__dict__},
        config.model_path,
    )
    print(f"[model] Saved model to {config.model_path}")

    return clf


def load_model(model_path: Path | str | None = None) -> RandomForestClassifier:
    """
    Load a previously trained model from disk.
    """
    if model_path is None:
        model_path = ModelConfig().model_path
    model_path = Path(model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found at {model_path}")

    payload: Dict = joblib.load(model_path)
    clf = payload["model"]
    return clf

