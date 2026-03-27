# Interface Contracts

Explicit contracts between every system pair that communicates.
Breaking any of these is a regression.

---

## AiService ↔ data_loader

**Access pattern:** AiService calls `fetch_universe_data()` to get raw OHLCV DataFrames.

**AiService calls on data_loader:**
| Function | When | Returns |
|----------|------|---------|
| `fetch_universe_data(tickers, start_date, end_date, data_dir, use_cache)` | On signal generation or retrain | `Dict[str, pd.DataFrame]` — ticker → OHLCV DataFrame |
| `fetch_live_prices(tickers)` | On TUI refresh | `Dict[str, Dict[str, float]]` — ticker → {price, change_pct} |

**Invariants:**
- Returned DataFrames always have columns: Open, High, Low, Close, Volume
- Index is DatetimeIndex named "Date"
- Empty DataFrame raises `ValueError`, never returns silently
- Cache files are CSV in `data/` directory

---

## AiService ↔ features_advanced

**Access pattern:** AiService calls V2 feature builder to create 31-dimensional feature vectors grouped by 6 analyst specialties.

**AiService calls on features_advanced:**
| Function | When | Returns |
|----------|------|---------|
| `get_feature_columns() → List[str]` | At initialisation | Ordered list of 31 feature names matching FEATURE_COLUMNS_V2 |
| `get_feature_groups() → Dict[str, List[str]]` | At initialisation | Mapping {group_name: [feature1, feature2, ...]} for 6 analyst groups |
| `build_advanced_features(universe_data) → (X, y, meta)` | Training | `X: ndarray (shape: N × 31)`, `y: ndarray (binary)`, `meta: DataFrame` |
| `latest_advanced_features(universe_data) → (features_df, meta_df)` | Inference | `features_df: DataFrame (indexed by ticker)`, `meta_df: DataFrame` |

**Invariants:**
- `X` columns always match `FEATURE_COLUMNS_V2` in exact order (31 features)
- 6 feature groups: momentum, volatility, trend, valuation, macro, flow
- `y` is binary: 0 or 1 (tomorrow's close higher)
- `meta` always has columns `[ticker, date]`
- `features_df` is indexed by ticker symbol
- NaN rows are dropped before return — callers can assume clean data
- No feature is NaN after computation (all rows are complete)

---

## AiService ↔ ensemble

**Access pattern:** AiService calls EnsembleModel to train on 12 diverse ML models and generate predictions.

**AiService calls on ensemble:**
| Function | When | Returns |
|----------|------|---------|
| `train_ensemble(X, y, meta, config) → EnsembleModel` | First run or retrain | Trained ensemble with 12 models (RF, XGB, LR, SVM, GB, etc.) |
| `load_ensemble(model_path) → EnsembleModel` | Subsequent runs | Deserialised EnsembleModel from disk |
| `predict_ensemble(X_latest) → ndarray` | Inference per-ticker | `ndarray` shape (n_tickers, n_models) — raw model probabilities |
| `get_model_metadata() → Dict` | Introspection | Names and hyperparams of all 12 models |
| `save(model_path)` | After training | Serialised to joblib/pickle at model_path |

**Invariants:**
- 12 diverse models to reduce overfitting and improve generalisation
- `predict_ensemble()` returns shape (n_samples, n_models) — row = sample, col = model probability P(up)
- All probabilities clamped to [0.0, 1.0]
- Model expects input shape matching `FEATURE_COLUMNS_V2` length (31 features)
- `train_ensemble()` always saves to `config.model_path` before returning
- `load_ensemble()` raises `FileNotFoundError` if model file missing

---

## AiService ↔ timeframe

**Access pattern:** AiService calls TimeframeEnsemble to generate horizon-specific signals (1d, 5d, 20d).

**AiService calls on timeframe:**
| Function | When | Returns |
|----------|------|---------|
| `train_timeframe_ensembles(X, y, meta, config) → Dict[str, TimeframeEnsemble]` | Training | `{horizon: ensemble}` for ["1d", "5d", "20d"] |
| `predict_all_horizons(X_latest) → Dict[str, ndarray]` | Inference | `{horizon: ndarray of shape (n_tickers, n_models)}` |
| `get_horizon_weights() → Dict[str, float]` | Configuration | Default weights for consensus aggregation |

**Invariants:**
- Three horizons always present: "1d", "5d", "20d"
- `predict_all_horizons()` returns 36 total signals (12 models × 3 horizons)
- Each horizon's ensemble is independent and trained with horizon-specific labels
- All probabilities in [0.0, 1.0]

---

## AiService ↔ regime

**Access pattern:** AiService calls RegimeDetector to classify market conditions.

**AiService calls on regime:**
| Function | When | Returns |
|----------|------|---------|
| `detect(universe_data) → RegimeState` | Before ensemble prediction | Current market regime + confidence |

**Invariants:**
- RegimeState includes: `regime` (bull/bear/range/high_vol), `confidence` (0.0–1.0), `macro_context: str`
- Used to weight ensemble predictions (bullish regimes increase buy signal weight)
- Regime detection is fast and deterministic based on recent price action

---

## AiService ↔ gemini_personas

**Access pattern:** AiService routes per-ticker features to 5 specialised Gemini personas.

**AiService calls on gemini_personas:**
| Function | When | Returns |
|----------|------|---------|
| `analyze_batch(ticker_features, regime_state) → Dict[str, List[GeminiPersonaSignal]]` | Per refresh | `{ticker: [signal1, signal2, ...]}` for 5 personas |

**GeminiPersonaSignal structure:**
```
{
  "persona": str,           # One of: technical, fundamental, sentiment, macro, risk
  "ticker": str,
  "p_up": float,            # Probability up [0.0, 1.0]
  "confidence": float,      # [0.0, 1.0]
  "reason": str             # Natural language explanation
}
```

**Invariants:**
- 5 personas always present: technical, fundamental, sentiment, macro, risk
- All `p_up` and `confidence` values clamped to [0.0, 1.0]
- On API failure, returns defaults (p_up=0.5, confidence=0.3, reason="Could not parse")
- Responses are parsed as JSON; markdown code blocks stripped

---

## AiService ↔ forecaster_statistical

**Access pattern:** AiService calls StatisticalForecaster for ARIMA/ETS baseline predictions.

**AiService calls on forecaster_statistical:**
| Function | When | Returns |
|----------|------|---------|
| `fit_and_predict(universe_data, horizons, on_progress)` | After ML ensemble (step 4a) | `Dict[str, List[ForecasterSignal]]` — ticker → signals per horizon |

**ForecasterSignal structure:**
```
{
  "family": "statistical",
  "ticker": str,
  "probability": float,       # P(up) via normal CDF [0.05, 0.95]
  "confidence": float,        # [0.0, 1.0]
  "forecast_return": float,   # Expected return over horizon
  "horizon_days": int,
  "model_name": str           # "arima" or "ets"
}
```

**Invariants:**
- Uses ARIMA(1,1,1) + Holt-Winters ETS, blended via simple average
- P(up) = 1 - Φ(-μ/σ) where Φ is standard normal CDF, clamped to [0.05, 0.95]
- Parallel fitting via ThreadPoolExecutor(max_workers=4)
- Graceful degradation: returns empty dict if statsmodels not installed
- Each ticker produces 2 signals per horizon (one ARIMA, one ETS)

---

## AiService ↔ forecaster_deep

**Access pattern:** AiService calls DeepForecaster for N-BEATS neural predictions.

**AiService calls on forecaster_deep:**
| Function | When | Returns |
|----------|------|---------|
| `fit_and_predict(universe_data, horizons, on_progress)` | After statistical (step 4b) | `Dict[str, List[ForecasterSignal]]` — ticker → signals per horizon |
| `is_available` (property) | Before calling fit | `bool` — whether PyTorch is installed |

**Invariants:**
- N-BEATS architecture: 2 generic stacks × 3 blocks with FC layers
- Trains on pooled cross-sectional return windows across all tickers
- Caches trained models to `models/deep/nbeats_h{horizon}.pt`
- Graceful degradation: returns empty dict if torch not installed
- `is_available` returns False when torch is missing — never raises

---

## AiService ↔ meta_ensemble

**Access pattern:** AiService calls MetaEnsemble to combine three model families.

**AiService calls on meta_ensemble:**
| Function | When | Returns |
|----------|------|---------|
| `combine(ml_probs, stat_signals, deep_signals, horizons)` | After all forecasters (step 4c) | `Dict[str, MetaEnsembleResult]` |
| `to_model_signals(stat_signals, deep_signals)` | Converting for consensus engine | `Dict[str, List[ModelSignal]]` |

**MetaEnsembleResult structure:**
```
{
  "ticker": str,
  "probability": float,        # Weighted-average P(up)
  "confidence": float,
  "ml_probability": float,
  "stat_probability": float,
  "deep_probability": float,   # 0.5 if unavailable
  "family_weights": Dict[str, float]
}
```

**Invariants:**
- Default weights: ML=50%, Statistical=25%, Deep=25%
- When deep unavailable: auto-redistribute → ML≈67%, Statistical≈33%
- `to_model_signals()` output is compatible with consensus engine's `all_model_signals` format
- All probabilities clamped to [0.0, 1.0]

---

## AiService ↔ PipelineTracker

**Access pattern:** AiService pushes progress updates; TUI polls for state snapshots.

**AiService calls on PipelineTracker:**
| Function | When | Returns |
|----------|------|---------|
| `begin()` | Start of signal generation | None — resets all 10 stages to pending |
| `start_stage(name, total)` | Entering a pipeline stage | None |
| `update_stage(name, current, detail)` | Per-model/ticker progress | None |
| `complete_stage(name, detail)` | Stage finished | None |
| `skip_stage(name, reason)` | Optional stage skipped | None |
| `end()` | Pipeline complete | None — records duration, sets is_running=False |
| `update_dashboard_stats(family_stats)` | After pipeline completes | None — updates idle dashboard data |

**TUI calls on PipelineTracker:**
| Function | When | Returns |
|----------|------|---------|
| `get_state()` | Every 250ms poll | `PipelineState` deep-copy snapshot |

**10 Pipeline Stages (in order):**
1. `data_fetch` — Downloading OHLCV data
2. `features` — Computing 31 V2 features
3. `regime` — Detecting market regime
4. `ml_ensemble` — 12 models × 3 horizons
5. `statistical` — ARIMA/ETS per ticker
6. `deep_learning` — N-BEATS per ticker (skippable)
7. `meta_blend` — Three-family combination
8. `gemini` — 5 Gemini personas
9. `consensus` — Investment committee aggregation
10. `risk` — Position sizing

**Invariants:**
- All methods are thread-safe (protected by threading.Lock)
- `get_state()` always returns a deep copy — safe to read from another thread
- Stages can only transition: pending → running → done/error, or pending → skipped
- `begin()` always resets all stages — safe to call multiple times

---

## AiService ↔ consensus

**Access pattern:** AiService calls ConsensusEngine to aggregate signals into unified recommendation.

**AiService calls on consensus:**
| Function | When | Returns |
|----------|------|---------|
| `compute_all(ensemble_probs, personas_signals, regime, timeframe_signals) → Dict[str, ConsensusResult]` | Signal generation | `{ticker: ConsensusResult}` |

**ConsensusResult structure:**
```
{
  "ticker": str,
  "consensus_prob": float,      # Weighted average [0.0, 1.0]
  "confidence": float,          # [0.0, 1.0]
  "ensemble_weight": float,     # Contribution of ensemble
  "personas_weight": float,     # Contribution of Gemini personas
  "regime_adjusted": bool,      # Whether regime weighting applied
  "component_breakdown": Dict   # Per-source probabilities for debugging
}
```

**Invariants:**
- Meta-ensemble (ML + Statistical + Deep models) ≈ 50% weight
- Gemini personas (5 analysts) ≈ 30% weight
- Regime context applied as multiplier (0.8–1.2)
- Final `consensus_prob` always in [0.0, 1.0]
- Output sorted by consensus_prob descending

---

## AiService ↔ risk_manager

**Access pattern:** AiService calls RiskManager to generate position sizes before strategy signal conversion.

**AiService calls on risk_manager:**
| Function | When | Returns |
|----------|------|---------|
| `generate_risk_enhanced_orders(consensus_signals, portfolio, config) → Dict[str, float]` | Order generation | `{ticker: position_size}` |

**Invariants:**
- Position size is always non-negative
- Kelly criterion: f* = (p × b - q) / b, capped to max_kelly_fraction
- Volatility adjustment: size ∝ 1 / volatility
- Portfolio concentration check: no single position > max_concentration_pct
- Sum of all positions ≤ available_capital

---

## AiService ↔ strategy

**Access pattern:** AiService passes consensus probabilities to `generate_signals()`.

**AiService calls on strategy:**
| Function | When | Returns |
|----------|------|---------|
| `generate_signals(prob_up, meta_latest, config, held_tickers)` | Signal generation | `DataFrame` with columns [ticker, date, prob_up, signal] |

**Invariants:**
- `signal` is always one of: `"buy"`, `"sell"`, `"hold"`
- Buy signals limited to `config.max_positions` count
- Sell signals only emitted for tickers in `held_tickers`
- Output sorted by `prob_up` descending

---

## TradingTerminalApp ↔ BrokerService

**Access pattern:** App calls BrokerService facade; never touches Broker directly.

**App calls on BrokerService:**
| Function | When | Returns |
|----------|------|---------|
| `get_positions()` | Each refresh | `List[Dict]` with keys: ticker, quantity, avg_price, current_price, unrealised_pnl |
| `get_account_info()` | Each refresh | `Dict` with keys: free, invested, result, total |
| `submit_order(ticker, side, quantity, order_type, ...)` | Trade execution | `Dict` with keys: ticker, side, quantity, status |
| `get_pending_orders()` | Each refresh | `List[Dict]` |
| `cancel_order(order_id)` | User action | `bool` |

**Invariants:**
- BrokerService falls back to LogBroker if Trading 212 API key is missing
- `side` is always `"BUY"` or `"SELL"` (uppercase)
- `order_type` is one of: `"market"`, `"limit"`, `"stop"`, `"stop_limit"`
- Failed orders return `status: "FAILED"` with `error` key, never raise

---

## AutoEngine ↔ AiService + BrokerService

**Access pattern:** AutoEngine calls AiService for signals, then BrokerService for execution.

**Invariants:**
- AutoEngine only runs when `state.mode == "full_auto_limited"`
- Daily loss check: if unrealised PnL < -(capital × max_daily_loss), skip all orders
- Orders are always market orders with quantity 1.0

---

## NewsAgent ↔ GeminiClient

**Access pattern:** NewsAgent calls `gemini_client.analyze_news()` for sentiment scoring.

**Invariants:**
- NewsAgent runs on a daemon thread — no guarantee of clean shutdown
- `sentiment` is always in [-1.0, 1.0]
- Headlines capped at 15 per ticker
- News data stored as `TickerNews` dataclass instances

---

## terminal/app ↔ terminal/state

**Access pattern:** App writes to AppState; views read from AppState.

**Invariants:**
- Only `terminal/app.py` mutates AppState (via `_update_state_and_views`)
- Views only read from state in `refresh_view()` — never mutate
- `signals` can be `None` before first refresh completes
- `chat_history` entries always have keys: `role` ("user" or "ai"), `text`
- AppState now includes: `regime_state`, `consensus_signals`, `ensemble_metadata`, `meta_ensemble_data`, `statistical_model_count`, `deep_model_available`, `pipeline_last_duration`
