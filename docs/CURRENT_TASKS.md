# Current Tasks

## Active Phase: Phase 3 — Testing, Backtesting, Advanced Strategies

### Completed
- [x] Core ML pipeline: data download, feature engineering, RF model, signal generation — Phase 1
- [x] Broker abstraction with LogBroker (paper trading) — Phase 1
- [x] CLI daily agent (`daily_agent.py`) — Phase 1
- [x] Bloomberg-style Textual TUI with 3-column grid layout — Phase 2
- [x] Gemini API integration for signal generation + chat + recommendations — Phase 2
- [x] Weighted ensemble scoring (sklearn 50% + gemini 30% + news 20%) — Phase 2
- [x] Trading 212 live broker implementation — Phase 2
- [x] Background news agent with RSS + Gemini sentiment — Phase 2
- [x] Watchlist management (add/remove/cycle/search/AI suggest) — Phase 2
- [x] Trade modal with market/limit/stop order types — Phase 2
- [x] Price sparkline charts — Phase 2
- [x] AI chat with full terminal context — Phase 2
- [x] Auto-trading engine with daily loss limits — Phase 2
- [x] Project documentation scaffolding (CLAUDE.md, docs/) — 2026-03-15

### In Progress
- [ ] (none currently)

### Up Next
- [ ] Add pytest test suite — unit tests for features, model, strategy, broker
- [ ] Backtesting engine — replay historical signals against price data
- [ ] Walk-forward validation — expanding window retrain + OOS evaluation
- [ ] MACD, Bollinger Bands, and volume profile features
- [ ] Multi-model ensemble (RF + XGBoost + logistic regression)
- [ ] Position sizing based on Kelly criterion or volatility-adjusted sizing
- [ ] Stop-loss and take-profit order generation
- [ ] Persistent trade log with performance tracking
- [ ] Integration tests for Trading 212 broker (mocked API)

### Blocked
- [ ] (none currently)

## How to Pick Up Work

1. Read `docs/ARCHITECTURE.md` for context
2. Check "In Progress" — don't duplicate active work
3. Pick from "Up Next" in order
4. Move task to "In Progress" with your name/agent-id
5. Complete the task + update all relevant docs
6. Move task to "Completed" with date
