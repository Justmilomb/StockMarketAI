# Forecaster — Deep Learning (N-BEATS)

Lightweight N-BEATS neural network forecaster for multi-horizon stock return prediction. Optional PyTorch dependency — returns empty dict when unavailable.

## Purpose

Provides the "deep learning" family in the three-family meta-ensemble. N-BEATS (Neural Basis Expansion Analysis for Time Series) learns to decompose a price series into trend and detail components via residual stacking, without requiring hand-crafted features.

## Architecture

```
Input: normalised returns window (lookback=60 bars)
    │
    ├── Trend Stack (3 × NBeatsBlock with FC-stack + residual)
    │
    └── Detail Stack (3 × NBeatsBlock with FC-stack + residual)
        │
        └── Output: forecast horizon values (e.g. 1, 5, 20 bars ahead)
```

Each `NBeatsBlock` has a 4-layer FC stack (hidden_dim=128), a backcast head, and a forecast head. Blocks are chained with residual subtraction: each block refines what the previous one left unexplained.

## Training Strategy

- One model per forecast horizon, trained on cross-sectional data (all tickers pooled)
- Input: normalised return windows from the entire universe
- Loss: MSE on normalised returns
- Adam optimiser, 50 epochs, batch_size=32, lr=0.001
- Models are cached to `models/deep/nbeats_h{horizon}.pt` and reused if the file exists

## Public API

```python
class DeepForecaster:
    is_available: bool  # True when PyTorch is installed

    def fit_and_predict(
        universe_data: Dict[str, pd.DataFrame],
        horizons: List[int],
        on_progress: Callable | None,
    ) -> Dict[str, List[ForecasterSignal]]
    # Returns empty dict if torch unavailable or on any training failure
```

## Signal Conversion

Forecast returns are converted to P(up) via the normal CDF (same as statistical forecaster, using scipy.stats.norm). Confidence is proportional to `|probability - 0.5|`.

## Configuration

```json
{
  "deep_forecaster": {
    "lookback_window": 60,
    "hidden_dim": 128,
    "n_blocks": 3,
    "epochs": 50,
    "batch_size": 32,
    "learning_rate": 0.001,
    "cache_dir": "models/deep"
  }
}
```

## Dependencies

- `torch` (optional — entire forecaster disabled without it)
- `scipy.stats.norm` (optional — for P(up) conversion)
- `types_shared.ForecasterSignal`
