# Meta-Ensemble

Three-family probability combiner: ML ensemble + statistical forecasters + deep learning, producing a single blended P(up) per ticker.

## Purpose

Sits between the ML timeframe ensemble and the consensus engine. Combines the three model families into one blended probability, handles graceful degradation when a family is unavailable (e.g. PyTorch not installed), and adapts statistical/deep signals into `ModelSignal` format for the investment committee vote.

## Pipeline Position

```
timeframe ensemble (ML probs)
    │
    ├── statistical forecaster (ARIMA+ETS signals)
    │
    ├── deep forecaster (N-BEATS signals, optional)
    │
    └── MetaEnsemble.combine() → MetaEnsembleResult per ticker
                                  └── MetaEnsemble.to_model_signals() → ModelSignal list for ConsensusEngine
```

## Default Family Weights

| Family | Default Weight | Notes |
|--------|---------------|-------|
| ML ensemble | 50% | Horizon-aggregated probability from timeframe module |
| Statistical (ARIMA+ETS) | 25% | Blended ARIMA and ETS signals per horizon |
| Deep learning (N-BEATS) | 25% | Redistributed to ML+Stat if PyTorch unavailable |

When deep learning is unavailable, its 25% weight is redistributed proportionally to ML and statistical families.

## Key Classes

```python
class MetaEnsemble:
    def combine(
        ml_probs: Dict[str, float],
        stat_signals: Dict[str, List[ForecasterSignal]],
        deep_signals: Dict[str, List[ForecasterSignal]],
        horizons: List[int],
    ) -> Dict[str, MetaEnsembleResult]

    def to_model_signals(
        stat_signals: Dict[str, List[ForecasterSignal]],
        deep_signals: Dict[str, List[ForecasterSignal]],
    ) -> Dict[str, List[ModelSignal]]
```

## MetaEnsembleResult Fields

`ticker, probability, confidence, ml_probability, stat_probability, deep_probability, family_weights`

## Configuration

```json
{
  "meta_ensemble": {
    "family_weights": {
      "ml": 0.50,
      "statistical": 0.25,
      "deep_learning": 0.25
    }
  }
}
```

## Dependencies

- `types_shared.py` (ForecasterSignal, MetaEnsembleResult, ModelSignal)
- `forecaster_statistical.py`, `forecaster_deep.py`, `timeframe.py`
