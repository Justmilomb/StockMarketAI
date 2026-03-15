# Model

## Goal
Trains and persists a RandomForestClassifier to predict whether tomorrow's closing price will be higher than today's (binary classification).

## Implementation
Uses a time-based train/validation split (80/20 by date) to avoid look-ahead bias. Model is `RandomForestClassifier(n_estimators=200, n_jobs=-1)`. Serialised with joblib as `{"model": clf, "config": config_dict}`. Prints validation accuracy and full classification report during training.

## Key Code
```python
@dataclass
class ModelConfig:
    n_estimators: int = 200
    model_path: Path = Path("models/rf_tomorrow_up.joblib")
    train_fraction: float = 0.8

def train_model(X, y, meta, config) -> RandomForestClassifier
def load_model(model_path) -> RandomForestClassifier
```

## Notes
- Time-based split prevents data leakage across train/val
- `random_state=42` for reproducibility
- Model expects exactly 10 features matching `FEATURE_COLUMNS`
- `predict_proba()[:, 1]` gives P(tomorrow up)
