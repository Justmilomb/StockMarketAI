# Changelog

Architectural decisions and significant changes. Newest first.

---

## 2026-03-15

- Scaffolded full project documentation from MASTER_PROMPT template (CLAUDE.md, docs/)
- Documented all interface contracts between system pairs
- Created per-system atomic docs in docs/systems/

## Pre-documentation (prior commits)

- Built Bloomberg-style Textual TUI with 3-column grid layout
- Added Google Gemini integration for signal generation, news analysis, and chat
- Implemented weighted ensemble scoring (sklearn 50% + gemini 30% + news 20%)
- Added Trading 212 live broker via REST API v0
- Built background news agent with RSS + Gemini sentiment scoring
- Added watchlist management (add/remove/cycle/search/AI suggest/AI recommend)
- Added trade modals with market/limit/stop order types
- Added sparkline price charts
- Built auto-trading engine with daily loss limits
- Created core ML pipeline: yfinance → features → RandomForest → strategy → LogBroker
- Initial project setup with config.json-driven architecture
