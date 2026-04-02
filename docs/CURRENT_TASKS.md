# Current Tasks

## Active Phase: Phase 3 — Testing, Backtesting, Advanced Strategies

### Completed

**Phase 1 — Core ML Pipeline**
- [x] Core ML pipeline: data download, feature engineering, RF model, signal generation — 2026-02-15
- [x] Broker abstraction with LogBroker (paper trading) — 2026-02-15
- [x] CLI daily agent (`daily_agent.py`) — 2026-02-15

**Phase 2 — TUI & Integrations**
- [x] Bloomberg-style Textual TUI with 3-column grid layout — 2026-02-28
- [x] Claude API integration for signal generation + chat + recommendations — 2026-03-01
- [x] Weighted ensemble scoring (sklearn 50% + claude 30% + news 20%) — 2026-03-05
- [x] Trading 212 live broker implementation — 2026-03-08
- [x] Background news agent with RSS + Claude sentiment — 2026-03-10
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
- [x] Claude persona analyzer (5 specialised analysts) — 2026-03-19
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

**Phase 2.9 — MiroFish Multi-Agent Simulation**
- [x] MiroFish core types and agent taxonomy (9 types, 1000 agents) — 2026-03-27
- [x] Vectorized agent belief updates with numpy (trend, reversion, sentiment, noise) — 2026-03-27
- [x] Social interaction engine (herding + contrarian convolution dynamics) — 2026-03-27
- [x] Core simulation engine with price feedback loop (100 ticks per run) — 2026-03-27
- [x] Monte Carlo orchestrator with ProcessPoolExecutor (all CPU cores) — 2026-03-27
- [x] Signal extraction: net sentiment, momentum, agreement, volatility, order flow — 2026-03-27
- [x] Integration into ai_service.py pipeline (step 4d, between meta-blend and Claude personas) — 2026-03-27
- [x] Pipeline tracker stage, AppState fields, config.json section — 2026-03-27
- [x] Contract documentation and architecture updates — 2026-03-27

**Phase 3.0 — Backtesting Engine**
- [x] Backtesting types (BacktestConfig, WalkForwardSplit, TradeRecord, PerformanceMetrics) — 2026-03-27
- [x] Data preparation (feature pre-computation, walk-forward split generation) — 2026-03-27
- [x] Trade simulator (stop-loss, take-profit, slippage, position sizing, equity tracking) — 2026-03-27
- [x] Core backtest engine (per-fold: train → predict → simulate → metrics) — 2026-03-27
- [x] Performance metrics (Sharpe, Sortino, Calmar, drawdown, win rate, profit factor, attribution) — 2026-03-27
- [x] Parallel walk-forward runner (ProcessPoolExecutor across all cores, serial fallback) — 2026-03-27
- [x] CLI entry point `backtest.py` with --fast/--full/--ticker/--folds flags — 2026-03-27
- [x] Backtesting config section in config.json — 2026-03-27

**Phase 3.05 — Multi-Strategy System + Stress Testing**
- [x] Strategy types in types_shared.py (StrategyProfile, StrategyAssignment, StrategyProfileName) — 2026-03-28
- [x] 5 strategy profiles (conservative, day_trader, swing, crisis_alpha, trend_follower) in strategy_profiles.py — 2026-03-28
- [x] Regime-aware strategy selector with 5-step cascade (strategy_selector.py) — 2026-03-28
- [x] Per-ticker config support in strategy.py — 2026-03-28
- [x] Small capital fixes: min_position £1, fractional shares (risk_manager.py) — 2026-03-28
- [x] Crisis period definitions and stress testing in autoconfig (universe.py, experiment.py) — 2026-03-28
- [x] Hub integration: config.json (capital=10, strategy_profiles), ai_service.py (selector injection), terminal state/views (Strategy column, regime→strategy display) — 2026-03-28
- [x] Backtesting integration: per-ticker overrides in simulator, regime-aware strategy per fold in engine — 2026-03-28

**Phase 3.1 — Multi-Asset Expansion (Stocks + Crypto + Polymarket)**
- [x] AssetClass type + asset_class fields on all signal/consensus/risk dataclasses (types_shared.py) — 2026-03-29
- [x] Asset registry pattern (asset_registry.py) — 2026-03-29
- [x] Multi-asset config expansion (config.json: crypto, polymarket sections) — 2026-03-29
- [x] Per-asset AppState with switch_asset_class() (terminal/state.py, desktop/state.py) — 2026-03-29
- [x] Multi-broker routing (broker_service.py: get_broker(asset_class)) — 2026-03-29
- [x] Database asset_class column + migration (database.py) — 2026-03-29
- [x] ai_service.py asset-class-aware config routing — 2026-03-29
- [x] Crypto package: 8 files (data_loader, features, ensemble, regime, broker, strategy, types, __init__) — 2026-03-29
- [x] Polymarket package: 8 files (data_loader, features, model, regime, broker, strategy, types, __init__) — 2026-03-29
- [x] TUI asset switching (1/2/3 keybindings, header, per-asset watchlist columns, help modal) — 2026-03-29
- [x] Desktop asset switching (1/2/3 shortcuts, header, status bar) — 2026-03-29

**Phase 3.15 — Autoconfig (Autonomous Parameter Optimisation)**
- [x] Autoconfig experiment runner (autoconfig/experiment.py) — run single backtest with config overrides — 2026-03-28
- [x] Autoconfig session launcher (autoconfig/run.py) — loops Claude CLI sessions, monitors progress — 2026-03-28
- [x] Autoconfig program spec (autoconfig/program.md) — instructions for the Claude agent — 2026-03-28
- [x] Stock universe module (autoconfig/universe.py) — small/medium/large/full ticker sets, sector groups, crisis periods — 2026-03-28
- [x] Autoconfig results persistence (results.tsv, best_config.json) — 2026-03-28
- [x] CPU config module (cpu_config.py) — centralised core allocation, env var overrides — 2026-03-30
- [x] Force spawn multiprocessing context for Linux VM compatibility — 2026-03-31
- [x] Cap max_parallel_folds at cpu_cores//2 to prevent over-subscription — 2026-04-01
- [x] GCP VM deployment support (12-core/24-vCPU/186GB) — 2026-04-01

### In Progress
- [ ] Autoconfig running on GCP VM — iterating parameter space (threshold_buy, threshold_sell, position_size, ATR multipliers, etc.)

### Up Next
- [ ] Add pytest test suite (features_advanced, ensemble, timeframe, regime, consensus, risk_manager, forecaster_statistical, forecaster_deep, meta_ensemble)
- [ ] Integration tests for Trading 212 broker (mocked API)
- [ ] Backtesting TUI integration (run from terminal, display results inline)
- [ ] Production hardening, monitoring, deployment automation (Phase 4)

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

- **Phase 2.9 complete:** MiroFish multi-agent simulation added. 1000 heterogeneous AI agents (9 types) run Monte Carlo simulations across all CPU cores. Emergent market behaviour produces sentiment, order flow, and volatility signals.
- **Key new modules:** `mirofish/types.py`, `mirofish/agents.py`, `mirofish/simulation.py`, `mirofish/orchestrator.py`, `mirofish/signals.py`.
- **Total model count:** 36 ML models + 12 ARIMA/ETS baselines + N-BEATS (optional) + 5 Claude personas + 1000 MiroFish agents × 16 Monte Carlo sims = 16,000+ independent agent simulations per ticker.
- **Phase 3.0 complete:** Backtesting engine built. Walk-forward validation with parallel fold execution, realistic trade simulation (stops, slippage, sizing), and comprehensive performance metrics (Sharpe, Sortino, Calmar, attribution by signal band). CLI: `python backtest.py --full` or `python backtest.py --fast`.
- **Key new modules:** `backtesting/types.py`, `backtesting/data_prep.py`, `backtesting/simulator.py`, `backtesting/engine.py`, `backtesting/metrics.py`, `backtesting/runner.py`, `backtest.py`.
- **Phase 3.05 complete:** Multi-strategy system added. 5 trading profiles selected per-ticker by regime, consensus quality, volatility, and historical performance. Stress testing against 5 crisis periods (2008 crash, COVID, 2022 bear, 2018 selloff, 2023 bank crisis). Small capital support (£10 with fractional shares). Backtesting integration with regime-aware per-fold strategy selection.
- **Key new modules:** `strategy_profiles.py`, `strategy_selector.py`. Modified: `types_shared.py`, `strategy.py`, `risk_manager.py`, `ai_service.py`, `config.json`, `terminal/state.py`, `terminal/views.py`, `terminal/app.py`, `backtesting/types.py`, `backtesting/simulator.py`, `backtesting/engine.py`, `autoconfig/universe.py`, `autoconfig/experiment.py`.
- **Phase 3.1 complete:** Multi-asset expansion. Three asset classes (stocks, crypto, polymarket) with full pipeline support. Registry pattern routes data loading, features, ensemble, regime, broker, and strategy to asset-specific implementations. Crypto reuses OHLCV pipeline with higher thresholds. Polymarket uses edge detection (AI_prob - market_prob) instead of classification. TUI/desktop switch via 1/2/3 keys. Zero breakage to existing stock functionality.
- **Key new packages:** `crypto/` (8 files), `polymarket/` (8 files). New files: `asset_registry.py`. Modified: `types_shared.py`, `config.json`, `ai_service.py`, `broker_service.py`, `database.py`, `terminal/state.py`, `terminal/app.py`, `terminal/views.py`, `desktop/state.py`, `desktop/app.py`.
- **Phase 3.15 complete:** Autoconfig runs Claude Opus 4.6 sessions autonomously to explore config parameter space via walk-forward backtesting. 23+ experiments completed. Best config found so far: threshold_buy=0.68, threshold_sell=0.48, position_size=0.05, atr_profit_multiplier=3.5 (81% win rate on medium universe validation).
- **Key new modules:** `autoconfig/experiment.py`, `autoconfig/run.py`, `autoconfig/program.md`, `autoconfig/universe.py`, `cpu_config.py`. Modified: `backtesting/runner.py`, `mirofish/orchestrator.py`, `config.json`.
- **Key fix:** max_parallel_folds now auto-caps at cpu_cores//2. ProcessPoolExecutor forces "spawn" context on Linux to prevent OpenBLAS deadlocks.
- **Next focus:** Pytest test suite coverage, then production hardening (Phase 4).
