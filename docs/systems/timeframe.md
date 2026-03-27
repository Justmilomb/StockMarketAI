# Timeframe (Multi-Timeframe Ensemble)

## Purpose
Trains independent EnsembleModel instances for 3 prediction horizons (1/5/20 days), aggregates via weighted average (50%/30%/20%). Captures short-, medium-, and long-term market views.

## Public API
- `build_horizon_labels(universe_data, horizon_days) -> Dict[str, DataFrame]` — Re-label targets for N-day prediction
- `MultiTimeframeEnsemble.train_all_horizons(universe_data)` — Train one ensemble per horizon
- `MultiTimeframeEnsemble.predict(features_df, meta_df) -> Dict[horizon, (probs, signals)]` — Per-horizon predictions
- `MultiTimeframeEnsemble.aggregate(horizon_results) -> (final_probs, horizon_breakdown)` — Weighted combination
- `MultiTimeframeEnsemble.get_all_signals(features_df, meta_df)` — Convenience: predict + aggregate
- `MultiTimeframeEnsemble.save/load(base_dir)` — Persist each horizon to horizon_{N}.joblib

## Total Signal Count
12 models x 3 horizons = 36 ML signals per ticker

## Configuration
- timeframes.horizons (default [1, 5, 20])
- timeframes.weights (default {1: 0.5, 5: 0.3, 20: 0.2})

## Dependencies
- ensemble.py (EnsembleModel), features_advanced.py, types_shared.py
