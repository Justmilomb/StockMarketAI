# Ensemble

## Purpose
12-model heterogeneous ensemble (RandomForest, XGBoost, LightGBM, LogisticRegression, SVM, KNN) across different feature subsets. Weighted soft voting combines predictions. Graceful degradation when optional libraries unavailable.

## Default 12-Model Matrix
| # | Name | Type | Feature Group |
|---|------|------|---------------|
| 1 | rf_all | RandomForest | all (31 features) |
| 2 | rf_trend | RandomForest | trend (7) |
| 3 | rf_momentum | RandomForest | momentum (8) |
| 4 | xgb_all | XGBoost | all |
| 5 | xgb_volatility | XGBoost | volatility (6) |
| 6 | lgbm_all | LightGBM | all |
| 7 | lgbm_trend_mom | LightGBM | trend+momentum (15) |
| 8 | lr_all | LogisticRegression | all |
| 9 | lr_momentum | LogisticRegression | momentum |
| 10 | svm_vol_vol | SVM | volatility+volume (10) |
| 11 | knn_momentum | KNN | momentum |
| 12 | rf_volume | RandomForest | volume (4) |

## Public API
- `generate_diverse_specs(n_models) -> List[ModelSpec]` — Default diversity matrix
- `EnsembleModel.train(X, y, meta, columns)` — Train all models, init equal weights
- `EnsembleModel.predict_ensemble(features_df, meta_df) -> (probs, per_ticker_signals)` — Weighted soft vote
- `EnsembleModel.update_weights(actual_outcomes)` — Online reweighting (70% recent + 30% historical)
- `EnsembleModel.save/load(path)` — Joblib persistence

## Configuration
- ensemble.n_models (12), ensemble.min_model_weight (0.02), ensemble.model_dir

## Dependencies
- features_advanced.py, types_shared.py, sklearn, xgboost (optional), lightgbm (optional)
