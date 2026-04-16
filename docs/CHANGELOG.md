# Changelog

Architectural decisions and significant changes. Newest first.

---

## 2026-04-02

### Gemini → Claude Migration (complete)
- Replaced all Google Gemini API calls with Claude API (`claude_client.py`, `claude_personas.py`, `news_agent.py`)
- Removed `gemini_client.py` and `gemini_personas.py` (dead files deleted)
- Removed `MASTER_PROMPT.md` (stale scaffold artefact)
- All LLM integration now routes through `ai_client.AIClient` using the Anthropic SDK
- No Gemini references remain in any active source file

### PySide6 Desktop App
- Added `desktop/` package: terminal-dark native GUI using PySide6 (replaces Textual TUI as primary interface)
- `desktop/main.py` — entry point with `freeze_support()` and PyInstaller `.env` loading
- `desktop/app.py` — `MainWindow` with 3×4 `QGridLayout`, background timers, keyboard shortcuts
- `desktop/theme.py` — terminal-dark QSS stylesheet matching Textual CSS palette
- `desktop/workers.py` — `QThread`-based `BackgroundTask` and `RefreshWorker`
- `desktop/panels/` — 8 panels: watchlist, positions, orders, chat, news, chart, pipeline, settings
- `desktop/dialogs/` — 8 modals: add ticker, AI recommend, help, history, instruments, pies, search, trade
- `desktop/state.py` — thin Qt wrapper reusing `terminal/state.AppState`

### Autoconfig System
- Added `autoconfig/` package: autonomous config optimisation via repeated Claude Code CLI sessions
- `autoconfig/run.py` — outer loop launcher (configurable batch size, max sessions, dry-run)
- `autoconfig/experiment.py` — single backtest runner with in-memory config overrides; never writes `config.json`
- `autoconfig/universe.py` — ~250 diverse stocks to prevent overfitting to the live watchlist
- `autoconfig/strategy_profiles.py` — bridge from named profiles to config override dicts
- Results persisted to `autoconfig/results.tsv`; progress state in `autoconfig/.progress`
- Deployed on GCP VM (12-core / 24-vCPU); see `docs/CLOUD_SETUP.md`

### Spawn Multiprocessing Fix
- Forced `multiprocessing.set_start_method("spawn")` globally in `desktop/main.py` and backtesting runner
- Prevents fork-related deadlocks (inherited locks, CUDA context duplication) on Linux GCP VM
- All `ProcessPoolExecutor` usage now safe under the spawn context

### CPU Core Cap Fix
- Introduced `cpu_config.py` as the single source of truth for parallelism limits
- `get_cpu_cores()`, `get_max_parallel_folds()`, `get_n_jobs_per_fold()` prevent over-subscription
- Fixes memory thrashing observed when running 24-vCPU backtest folds with n_jobs=-1

### PyInstaller .env Loading Fix
- `desktop/main.py` explicitly loads `.env` from the directory containing the executable
- Resolves `ANTHROPIC_API_KEY` not being found when running the packaged `.exe`
- `os.chdir(EXE_DIR)` also ensures relative paths in config.json resolve correctly

### Dead File Cleanup
- Deleted: `gemini_client.py`, `gemini_personas.py`, `MASTER_PROMPT.md`
- These had no remaining callers after the Claude migration

---

## 2026-03-15

- Scaffolded full project documentation from MASTER_PROMPT template (CLAUDE.md, docs/)
- Documented all interface contracts between system pairs
- Created per-system atomic docs in docs/systems/

## Pre-documentation (prior commits)

- Built terminal-style Textual TUI with 3-column grid layout
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
