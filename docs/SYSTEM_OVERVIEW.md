# System Overview

## Project Goal

An AI-driven stock trading terminal that combines a 1000-analyst ensemble ML pipeline with Claude LLM analysis to generate actionable buy/sell/hold signals, displayed in a Bloomberg-style terminal UI or PySide6 desktop app. Supports paper trading via log broker and live trading via Trading 212 API.

## Runtime Lifecycle

### TUI Mode (`python ai.py` or `python terminal/app.py`)
1. Load `config.json` → initialise AppState, AiService, BrokerService
2. Initialise Claude client + NewsAgent (background thread)
3. Mount Textual grid: metrics | watchlist | chat | positions | chart | news
4. Start refresh timer (default 15s)
5. Each refresh cycle:
   - AutoEngine checks mode + signals → submits orders if `full_auto` enabled
   - AiService runs the full 1000-analyst pipeline (see Pipeline section below)
   - BrokerService fetches positions + account info from Trading 212
   - NewsAgent fetches RSS headlines + Claude sentiment (async)
   - All views update from shared AppState

### Desktop Mode (`python -m desktop.main`)
1. Load `config.json` → initialise QApplication, main window, shared AppState
2. Wire panels (watchlist, positions, chart, news, chat, pipeline)
3. Spawn background QThread workers for AI pipeline and broker polling
4. Each refresh cycle: same AI pipeline as TUI, results pushed to Qt UI via signals

### CLI Backtest (`python backtest.py`)
1. Parse CLI args → build `BacktestConfig`
2. Pre-compute features across full date range
3. Split into walk-forward folds
4. Execute folds in parallel (ProcessPoolExecutor, all CPU cores)
5. Aggregate fold results → compute Sharpe, Sortino, Calmar, drawdown, attribution
6. Print formatted report to stdout

### Autoconfig (`python autoconfig/run.py`)
1. Launch a Claude Code CLI session pointing at `autoconfig/program.md`
2. Claude runs N backtest experiments, mutating config parameters
3. Session ends, results are appended to `autoconfig/results.tsv`
4. Best config is written to `autoconfig/best_config.json`
5. Loop restarts with a fresh session (fresh context window)

## The 1000-Analyst Pipeline

`AiService` orchestrates the full pipeline on every refresh. Each component produces a `ModelSignal` that is aggregated by the investment committee.

```
Data Layer
  data_loader.py       — yfinance OHLCV download + CSV cache

Feature Engineering
  features.py          — 10 basic features (legacy)
  features_advanced.py — 31 V2 features across 6 analyst groups

ML Families
  ensemble.py          — 12 diverse sklearn models (quant desk)
  timeframe.py         — 1d / 5d / 20d multi-horizon ensembles
  model.py             — legacy single RandomForest (still wired)

Statistical Family
  forecaster_statistical.py — ARIMA + ETS baselines (statsmodels)

Deep Learning Family
  forecaster_deep.py   — N-BEATS neural forecaster (optional, torch)

Meta-Ensemble
  meta_ensemble.py     — 3-family combiner: ML + Statistical + Deep

Agent Simulation
  mirofish/
    agents.py          — 9 agent types (trend-follower, mean-reversion, etc.)
    simulation.py      — per-tick: observe → interact → decide → aggregate
    orchestrator.py    — 16 Monte Carlo runs across all CPU cores
    signals.py         — emergent signal → ModelSignal extraction

Market Context
  regime.py            — bull / bear / sideways / volatile detector

LLM Analysis
  claude_client.py     — Claude CLI sessions: signals, news sentiment, chat
  claude_personas.py   — 5 analyst personas (fundamental, technical, macro,
                         sentiment, risk)

Signal Aggregation
  consensus.py         — investment committee: weights all families
  risk_manager.py      — Kelly criterion + ATR sizing, stop-loss levels
  strategy.py          — probability → BUY/SELL/HOLD + confidence score
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.12+ | Ecosystem for ML + data + TUI + desktop |
| ML Models | scikit-learn (12 model types) | Fast, diverse, no-GPU ensemble |
| Statistical | statsmodels (ARIMA, ETS) | Classical time-series baselines |
| Deep Learning | PyTorch / N-BEATS (optional) | Neural forecasting family |
| LLM | Claude CLI (Anthropic) | Signal generation, sentiment, chat — no separate API key needed |
| Agent Simulation | NumPy (vectorised) | 1000-agent Monte Carlo at native speed |
| Market Data | yfinance | Free, reliable OHLCV data |
| Data Processing | pandas + numpy | Industry standard for tabular data |
| TUI Framework | Textual | Rich terminal UIs with grid layout |
| Desktop Framework | PySide6 | Cross-platform Qt GUI |
| Model Serialisation | joblib | scikit-learn standard |
| Neural Model Serialisation | PyTorch (.pt) | N-BEATS checkpoints |
| Live Broker | Trading 212 REST API v0 | User's chosen broker |
| Persistence | SQLite (via database.py) | Snapshots, config audit trail, chat history |
| News | feedparser (RSS) | Lightweight headline fetching |

## Key Constraints

- All secrets (API keys) via environment variables, never in code or config
- Broker defaults to paper mode (LogBroker) unless `T212_API_KEY` is configured
- `T212_PRACTICE=true` must be set for practice account; false routes to live
- Model artifacts saved to `models/`, not git-tracked
- CSV cache in `data/`, not git-tracked
- N-BEATS deep forecaster is optional — if PyTorch is unavailable the meta-ensemble falls back to ML + Statistical only
- MiroFish uses `spawn` multiprocessing context for Windows compatibility
- News agent runs on a daemon thread — no cleanup guarantees on crash
- Claude LLM calls are async; pipeline continues with partial results if Claude is slow
