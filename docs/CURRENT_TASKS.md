# Current Tasks

## Active Phase: Phase 4 — Production Hardening

### Completed

**Phase 1 — Core ML Pipeline**
- [x] Core ML pipeline: data download, feature engineering, RF model, signal generation — 2026-02-15
- [x] Broker abstraction with LogBroker (paper trading) — 2026-02-15

**Phase 2 — TUI & Integrations**
- [x] Bloomberg-style Textual TUI with 3-column grid layout — 2026-02-28
- [x] Claude API integration for signal generation + chat + recommendations — 2026-03-01
- [x] Weighted ensemble scoring (sklearn 50% + claude 30% + news 20%) — 2026-03-05
- [x] Trading 212 live broker implementation — 2026-03-08
- [x] Background news agent with RSS + Claude sentiment — 2026-03-10
- [x] Watchlist management, trade modal, price charts, AI chat — 2026-03-14

**Phase 2.5 — 1000-Analyst Ensemble Pipeline**
- [x] Advanced feature engineering (V2: 31 features × 6 analyst groups) — 2026-03-17
- [x] Multi-model ensemble (12 diverse ML classifiers) — 2026-03-18
- [x] Multi-timeframe signal generation (1d/5d/20d horizons) — 2026-03-18
- [x] Market regime detection, Claude personas, consensus engine — 2026-03-20
- [x] Portfolio risk manager (Kelly criterion + volatility sizing) — 2026-03-20
- [x] SQLite persistence, pipeline visualization — 2026-03-21
- [x] ARIMA/ETS statistical baseline forecasters — 2026-03-21

**Phase 2.9 — MiroFish Multi-Agent Simulation**
- [x] 1000 heterogeneous agents (9 types) × 16 Monte Carlo sims — 2026-03-27

**Phase 3.0 — Backtesting Engine**
- [x] Walk-forward validation with parallel fold execution — 2026-03-27
- [x] Trade simulation (stops, slippage, sizing), Sharpe/Sortino/Calmar metrics — 2026-03-27

**Phase 3.05 — Multi-Strategy + Stress Testing**
- [x] 5 strategy profiles, regime-aware selection, crisis period testing — 2026-03-28

**Phase 3.1 — Multi-Asset Expansion**
- [x] Crypto package (8 files) + Polymarket package (10 files) — 2026-03-29
- [x] Asset registry pattern, TUI/desktop asset switching — 2026-03-29

**Phase 3.15 — Autoconfig (Autonomous Optimisation)**
- [x] Claude Opus 4.6 CLI sessions, walk-forward backtesting, 23+ experiments — 2026-04-01

**Phase 3.2 — PySide6 Desktop App**
- [x] Bloomberg-dark GUI with QDockWidget panels — 2026-04-02
- [x] PyInstaller build + Inno Setup installer — 2026-04-02

**Phase 3.5 — Commercialisation**
- [x] License server (FastAPI + SQLite on Render) — 2026-04-07
- [x] Remote admin config enforcement (kill switch, maintenance, force update) — 2026-04-07
- [x] First-run setup wizard (Claude CLI + T212 instructions) — 2026-04-08
- [x] News agent data sync fix + AI availability guards — 2026-04-08
- [x] Admin panel simplified (removed fine-tuning knobs) — 2026-04-08
- [x] Code signing support in build pipeline — 2026-04-08

**Phase 3.6 — Simple App + Reorganisation**
- [x] Simple edition: card-based UI matching website aesthetic — 2026-04-08
- [x] Root cleanup: 29 core modules moved to `core/` package — 2026-04-08
- [x] Two separate installers: Bloomberg + Simple editions — 2026-04-08
- [x] Dead files removed (ai.py, daily_agent.py, prompt.txt, proxy/) — 2026-04-08
- [x] Documentation overhaul — 2026-04-08

### In Progress
- [ ] Test coverage expansion (pytest suite for ensemble, timeframe, regime, consensus, risk_manager)

### Up Next
- [ ] Integration tests for Trading 212 broker (mocked API)
- [ ] Production monitoring and alerting
- [ ] Auto-update mechanism (check server version endpoint)
- [ ] Outfit font bundling for Simple edition

### Blocked
- [ ] (none currently)

## How to Pick Up Work

1. Read `docs/ARCHITECTURE.md` for context
2. Check "In Progress" — don't duplicate active work
3. Pick from "Up Next" in order
4. Move task to "In Progress" with your name/agent-id
5. Complete the task + update all relevant docs
6. Move task to "Completed" with date
