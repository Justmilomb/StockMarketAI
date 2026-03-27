# Current Tasks

## Active Phase: Phase 3 — Testing, Backtesting, Advanced Strategies

### Completed

**Phase 1 — Core ML Pipeline**
- [x] Core ML pipeline: data download, feature engineering, RF model, signal generation — 2026-02-15
- [x] Broker abstraction with LogBroker (paper trading) — 2026-02-15
- [x] CLI daily agent (`daily_agent.py`) — 2026-02-15

**Phase 2 — TUI & Integrations**
- [x] Bloomberg-style Textual TUI with 3-column grid layout — 2026-02-28
- [x] Gemini API integration for signal generation + chat + recommendations — 2026-03-01
- [x] Weighted ensemble scoring (sklearn 50% + gemini 30% + news 20%) — 2026-03-05
- [x] Trading 212 live broker implementation — 2026-03-08
- [x] Background news agent with RSS + Gemini sentiment — 2026-03-10
- [x] Watchlist management (add/remove/cycle/search/AI suggest) — 2026-03-12
- [x] Trade modal with market/limit/stop order types — 2026-03-12
- [x] Price sparkline charts — 2026-03-12
- [x] AI chat with full terminal context — 2026-03-13
- [x] Auto-trading engine with daily loss limits — 2026-03-14
- [x] Project documentation scaffolding (CLAUDE.md, docs/) — 2026-03-15

**Phase 2.5 — 1000-Analyst Ensemble Pipeline**
- [x] Advanced feature engineering (V2: 31 features × 6 analyst groups) — 2026-03-17
- [x] Multi-model ensemble (12 diverse ML classifiers) — 2026-03-18
- [x] Multi-timeframe signal generation (1d/5d/20d horizons, 36 signals) — 2026-03-18
- [x] Market regime detection (bull/bear/range/high_vol classifier) — 2026-03-19
- [x] Gemini persona analyzer (5 specialised analysts) — 2026-03-19
- [x] Investment committee consensus engine (weighted aggregation) — 2026-03-20
- [x] Portfolio risk manager (Kelly criterion + volatility sizing) — 2026-03-20
- [x] Terminal UI updates (regime panel, consensus confidence, ensemble breakdown) — 2026-03-20
- [x] SQLite persistence for regime history, consensus results, ensemble metadata — 2026-03-20

**Phase 2.75 — Three-Family Meta-Ensemble + Pipeline Visualization**
- [x] ARIMA/ETS statistical baseline forecasters (`forecaster_statistical.py`) — 2026-03-21
- [x] N-BEATS deep learning forecaster with graceful torch degradation (`forecaster_deep.py`) — 2026-03-21
- [x] Three-family meta-ensemble combiner: ML + Statistical + Deep (`meta_ensemble.py`) — 2026-03-21
- [x] Thread-safe pipeline progress tracker (`pipeline_tracker.py`) — 2026-03-21
- [x] Bloomberg-style pipeline visualization with dual-mode display (`terminal/pipeline_view.py`) — 2026-03-21
- [x] Full integration into ai_service.py signal pipeline (steps 4a/4b/4c) — 2026-03-21
- [x] Grid layout expanded to 3×4, pipeline panel mounted as full-width row 4 — 2026-03-21

### In Progress
- [ ] (none currently)

### Up Next
- [ ] Add pytest test suite — unit tests for features_advanced, ensemble, timeframe, regime, consensus, risk_manager, forecaster_statistical, forecaster_deep, meta_ensemble
- [ ] Backtesting engine — replay historical signals against price data
- [ ] Walk-forward validation — expanding window retrain + OOS evaluation
- [ ] Integration tests for all new ensemble modules
- [ ] Advanced position sizing strategies (volatility-adjusted Kelly, asymmetric risk/reward)
- [ ] Stop-loss and take-profit order generation
- [ ] Persistent trade log with performance tracking per signal source (ensemble vs personas vs regime)
- [ ] Integration tests for Trading 212 broker (mocked API)
- [ ] Dashboard views for model performance and consensus breakdowns

### Blocked
- [ ] (none currently)

## How to Pick Up Work

1. Read `docs/ARCHITECTURE.md` for context
2. Check "In Progress" — don't duplicate active work
3. Pick from "Up Next" in order
4. Move task to "In Progress" with your name/agent-id
5. Complete the task + update all relevant docs
6. Move task to "Completed" with date

## Notes

- **Phase 2.75 complete:** Three-family meta-ensemble added (ML ensemble + ARIMA/ETS + N-BEATS deep learning). Pipeline visualization shows real-time progress bars during model training/prediction.
- **Key new modules:** `forecaster_statistical.py`, `forecaster_deep.py`, `meta_ensemble.py`, `pipeline_tracker.py`, `terminal/pipeline_view.py`.
- **Total model count:** 36 ML models + 12 ARIMA/ETS baselines + N-BEATS (optional, requires PyTorch) + 5 Gemini personas = 53+ independent analyses per ticker.
- **Phase 3 focus:** Testing & validation. The core system is feature-complete; next priority is pytest coverage, backtesting, and walk-forward validation.
