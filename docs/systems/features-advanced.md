# Features Advanced

## Purpose
Computes 31 engineered technical indicators grouped into 6 semantic categories (trend, momentum, volatility, volume, multi_tf, price). Extends the original 10-feature set to support specialist ensemble models.

## Key Types
- **FeatureGroup** — name, columns list, description
- **FEATURE_GROUPS** — Dict mapping group name to FeatureGroup
- **FEATURE_COLUMNS_V2** — All 31 feature column names (union of all groups)

## Public API
- `engineer_features_v2(df) -> DataFrame` — Full pipeline: normalise OHLCV, compute all 31 features + target_up, drop NaN rows
- `build_universe_dataset_v2(universe_data, feature_columns?) -> (X, y, meta)` — Training matrices from multi-ticker data
- `latest_feature_rows_v2(universe_data, feature_columns?) -> (features_df, meta_df)` — Latest row per ticker for inference
- `get_feature_group_columns(group_name) -> List[str]` — Column names for a named group
- 8 compute functions: `compute_macd`, `compute_bollinger_bands`, `compute_atr`, `compute_obv`, `compute_stochastic`, `compute_williams_r`, `compute_adx`, `compute_vwap_proxy`

## Feature Groups
| Group | Columns | Count |
|-------|---------|-------|
| price | open, prev_close | 2 |
| trend | ma_5/10/30d, macd, macd_signal, macd_hist, adx_14d | 7 |
| momentum | rsi_14d, stoch_k/d, williams_r, ret_1/5/10d, roc_10d | 8 |
| volatility | vol_5d, bb_upper/lower/width, atr_14d, atr_pct | 6 |
| volume | obv, obv_slope, volume_sma_ratio, vwap_proxy_ratio | 4 |
| multi_tf | ret_20/60d, weekly/monthly_momentum | 4 |

## Dependencies
- features.py (_compute_rsi, FEATURE_COLUMNS), types_shared.py (FeatureGroup), pandas, numpy
