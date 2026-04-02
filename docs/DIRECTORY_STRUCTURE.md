# Directory Structure

```
StockMarketAI/
│
│  ── Entry Points ──────────────────────────────────────────────────────
├── ai.py                          ← Legacy CLI pipeline runner (calls daily_agent)
├── backtest.py                    ← CLI entry point for walk-forward backtesting
│
│  ── Core AI / ML Pipeline ─────────────────────────────────────────────
├── ai_service.py                  ← Hub: 1000-analyst ensemble orchestrator (wires all ML + Claude)
├── accuracy_tracker.py            ← Sliding-window hit-rate tracking for per-source accuracy
├── asset_registry.py              ← Factory registry mapping AssetClass → data/features/ensemble/broker
├── consensus.py                   ← Investment committee: aggregates all model signals into one score
├── cpu_config.py                  ← Centralised CPU core caps (prevents memory thrashing)
├── data_loader.py                 ← yfinance OHLCV download + CSV cache
├── ensemble.py                    ← 12-model ML ensemble (RF, XGB, LGB, LR, SVM, KNN); quant desk
├── features.py                    ← Legacy 10-feature technical indicators + label creation
├── features_advanced.py           ← 31 V2 features grouped into 6 analyst specialties
├── forecaster_deep.py             ← N-BEATS neural forecaster (optional PyTorch; gracefully skipped)
├── forecaster_statistical.py      ← ARIMA(1,1,1) + Holt-Winters ETS baseline forecasters
├── meta_ensemble.py               ← Three-family combiner: ML (50%) + Statistical (25%) + Deep (25%)
├── model.py                       ← Legacy RandomForest train/load/predict
├── pipeline_tracker.py            ← Thread-safe progress tracking for TUI pipeline view
├── regime.py                      ← Market regime detector (bull/bear/range/high-vol)
├── risk_manager.py                ← Position sizing: Kelly criterion + ATR + portfolio concentration
├── strategy.py                    ← Consensus score → buy/sell/hold signal conversion
├── strategy_profiles.py           ← Immutable trading-style profiles (conservative, swing, etc.)
├── strategy_selector.py           ← Regime-aware per-ticker strategy profile assignment
├── timeframe.py                   ← Multi-horizon ensemble wrappers (1d / 5d / 20d)
├── types_shared.py                ← Canonical shared dataclasses (ModelSignal, ConsensusResult, etc.)
│
│  ── Claude Integration ────────────────────────────────────────────────
├── claude_client.py               ← Claude API wrapper (signals, news sentiment, chat)
├── claude_personas.py             ← 5 Claude analyst personas (technical, fundamental, sentiment, macro, risk)
│
│  ── Broker Layer ──────────────────────────────────────────────────────
├── broker.py                      ← Broker ABC + LogBroker (JSONL) + Trading212Broker
├── broker_service.py              ← Broker-agnostic facade used by AI pipeline
├── trading212.py                  ← Trading 212 REST API v0 client
│
│  ── Background Agents ─────────────────────────────────────────────────
├── auto_engine.py                 ← Automated signal → risk-managed order execution loop
├── daily_agent.py                 ← CLI pipeline runner: fetch → predict → log
├── news_agent.py                  ← Background RSS fetcher + Claude batch sentiment analysis
│
│  ── Persistence ───────────────────────────────────────────────────────
├── database.py                    ← SQLite persistence (snapshots, positions, PnL, chat history)
│
│  ── Config & Environment ──────────────────────────────────────────────
├── config.json                    ← Hub: all runtime configuration (watchlist, thresholds, broker mode)
├── requirements.txt               ← Hub: Python dependency manifest
├── .env.example                   ← Environment variable template (API keys)
├── .gitignore                     ← Excludes data/, models/, logs/, .env, __pycache__
├── CLAUDE.md                      ← AI agent entry point and project instructions
│
│  ── Desktop App (PySide6) ──────────────────────────────────────────────
├── desktop/
│   ├── __init__.py
│   ├── main.py                    ← Entry point: freeze_support, .env loading, QApplication launch
│   ├── app.py                     ← Hub: MainWindow — Bloomberg-dark 3×4 QGridLayout, timers, shortcuts
│   ├── state.py                   ← Qt-aware AppState wrapper (reuses terminal/state.AppState)
│   ├── theme.py                   ← Bloomberg-dark QSS stylesheet (black/gold/green/red)
│   ├── workers.py                 ← QThread background workers (RefreshWorker, BackgroundTask)
│   ├── panels/
│   │   ├── __init__.py
│   │   ├── chart.py               ← Price chart panel (sparkline/candlestick)
│   │   ├── chat.py                ← Claude chat panel with history
│   │   ├── news.py                ← News sentiment feed panel
│   │   ├── orders.py              ← Open orders + order history panel
│   │   ├── pipeline.py            ← AI pipeline progress and model dashboard panel
│   │   ├── positions.py           ← Portfolio positions + PnL panel
│   │   ├── settings.py            ← Live settings editor panel
│   │   └── watchlist.py           ← Watchlist panel with signal columns
│   └── dialogs/
│       ├── __init__.py
│       ├── add_ticker.py          ← Add ticker dialog (text input)
│       ├── ai_recommend.py        ← AI ticker recommendation dialog
│       ├── help.py                ← Keyboard shortcuts / help dialog
│       ├── history.py             ← Signal history modal
│       ├── instruments.py         ← Instrument search / browse dialog
│       ├── pies.py                ← Trading 212 pies management dialog
│       ├── search_ticker.py       ← Ticker search dialog
│       └── trade.py               ← Place trade dialog (market/limit/stop)
│
│  ── TUI Terminal (Textual) ─────────────────────────────────────────────
├── terminal/
│   ├── app.py                     ← Hub: TradingTerminalApp — Textual lifecycle, action handlers
│   ├── state.py                   ← AppState shared dataclass (regime, consensus, ensemble metadata)
│   ├── views.py                   ← UI panels + Consensus/Confidence columns
│   ├── pipeline_view.py           ← Dual-mode: progress bars + model dashboard
│   ├── history_views.py           ← History/pies/instruments modals
│   ├── charts.py                  ← Sparkline price charts
│   └── terminal.css               ← Bloomberg-dark Textual CSS theme
│
│  ── Backtesting Engine ─────────────────────────────────────────────────
├── backtesting/
│   ├── __init__.py
│   ├── types.py                   ← BacktestConfig, TradeRecord, PerformanceMetrics dataclasses
│   ├── data_prep.py               ← Feature pre-computation + walk-forward split generation
│   ├── engine.py                  ← Per-fold: train → predict → simulate
│   ├── simulator.py               ← Trade execution: stops, slippage, position sizing
│   ├── metrics.py                 ← Sharpe, Sortino, Calmar, drawdown, attribution
│   └── runner.py                  ← Parallel fold executor across all CPU cores
│
│  ── MiroFish Multi-Agent Simulation ───────────────────────────────────
├── mirofish/
│   ├── __init__.py
│   ├── types.py                   ← AgentConfig, SimulationConfig, MiroFishSignal dataclasses
│   ├── agents.py                  ← 9 agent types (momentum, mean-reversion, sentiment, etc.), vectorised
│   ├── simulation.py              ← Per-tick engine: observe → interact → decide → aggregate
│   ├── orchestrator.py            ← Multi-process Monte Carlo across all CPU cores
│   └── signals.py                 ← Emergent behaviour → ModelSignal extraction
│
│  ── Autoconfig — Autonomous Optimisation ──────────────────────────────
├── autoconfig/
│   ├── run.py                     ← Launcher: repeatedly invokes Claude Code CLI sessions
│   ├── experiment.py              ← Single backtest with in-memory config overrides (never writes config.json)
│   ├── universe.py                ← ~250 diverse stocks for generalised optimisation backtests
│   ├── strategy_profiles.py       ← Bridge: named profile → config override dict
│   ├── .progress                  ← Experiment progress tracker (current session state)
│   └── results.tsv                ← Cumulative experiment results log
│
│  ── AutoResearch — Autonomous Strategy Improvement ────────────────────
├── autoresearch/
│   ├── __init__.py
│   ├── runner.py                  ← Autonomous loop: evaluate → propose → apply → repeat
│   └── evaluator.py               ← Accuracy measurement + simple backtest for strategy evaluation
│
│  ── Multi-Asset Packages ───────────────────────────────────────────────
├── crypto/
│   ├── __init__.py
│   ├── types.py                   ← ExchangeConfig and crypto-specific dataclasses
│   ├── data_loader.py             ← Crypto OHLCV fetching (exchange-agnostic)
│   ├── features.py                ← Crypto-specific technical features
│   ├── ensemble.py                ← ML ensemble adapted for crypto volatility
│   ├── regime.py                  ← Crypto market regime detection
│   ├── broker.py                  ← Crypto exchange broker implementation
│   └── strategy.py                ← Crypto-specific signal conversion
│
├── polymarket/
│   ├── __init__.py
│   ├── types.py                   ← PolymarketEvent and prediction-market dataclasses
│   ├── data_loader.py             ← Polymarket API + event data fetching
│   ├── features.py                ← Prediction-market feature engineering
│   ├── model.py                   ← Probability-edge ML model for binary markets
│   ├── regime.py                  ← Market sentiment / regime detection for prediction markets
│   ├── broker.py                  ← Polymarket order placement adapter
│   └── strategy.py                ← Edge → buy/sell decision logic
│
│  ── Tests ──────────────────────────────────────────────────────────────
├── tests/
│   ├── __init__.py
│   ├── conftest.py                ← pytest fixtures and shared test helpers
│   └── test_features.py           ← Feature engineering unit tests
│
│  ── Runtime Artifacts (git-ignored) ───────────────────────────────────
├── data/                          ← Cached OHLCV CSV files
├── models/                        ← Trained model artifacts (.joblib, .pt)
│   └── deep/                      ← N-BEATS PyTorch checkpoints (nbeats_h1/h5/h20.pt)
├── logs/                          ← LogBroker JSONL order logs
│
│  ── Documentation ──────────────────────────────────────────────────────
└── docs/
    ├── ARCHITECTURE.md            ← System graph, data flow, subsystem contracts
    ├── CHANGELOG.md               ← Architectural decisions and significant changes
    ├── CODING_STANDARDS.md        ← Type hints, naming, import order, docstrings
    ├── CONTRACTS.md               ← Interface contracts between system pairs
    ├── CURRENT_TASKS.md           ← Active tasks, backlog, done items
    ├── DIRECTORY_STRUCTURE.md     ← This file
    ├── SYSTEM_OVERVIEW.md         ← High-level product description
    ├── AGENT_WORKFLOW.md          ← Multi-agent dispatch protocol
    ├── TESTING.md                 ← pytest conventions and coverage targets
    ├── LINTING.md                 ← Linting and formatting standards
    ├── CLOUD_SETUP.md             ← GCP VM deployment guide for autoconfig
    └── systems/                   ← Atomic ~150-word docs per module
        ├── auto-engine.md
        ├── backtesting.md
        ├── broker.md
        ├── consensus.md
        ├── data-loader.md
        ├── ensemble.md
        ├── features.md
        ├── features-advanced.md
        ├── mirofish.md
        ├── model.md
        ├── news-agent.md
        ├── regime.md
        ├── risk-manager.md
        ├── strategy.md
        ├── terminal.md
        └── timeframe.md
```

## Rules

- Source files are flat in project root (no `src/` directory).
- TUI-specific code lives in `terminal/`; PySide6 desktop code lives in `desktop/`.
- Multi-asset packages (crypto/, polymarket/) mirror the root module structure.
- One class/module per file (hub files — ai_service.py, terminal/app.py, desktop/app.py — are the explicit exception).
- Tests mirror source structure in `tests/`.
- `docs/` is the authoritative knowledge base. Code comments supplement, not replace.
- `docs/systems/` contains one ~150-word doc per system/module.
- `data/`, `models/`, and `logs/` are runtime artifacts — never commit.
- `autoconfig/` must never import any project module except `backtesting/`; it operates via subprocess.
- `config.json` is never written by `autoconfig/experiment.py` — overrides are in-memory only.
