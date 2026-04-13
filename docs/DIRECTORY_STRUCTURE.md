# Directory Structure

```
StockMarketAI/
│
│  ── Entry Points ──────────────────────────────────────────────────────
├── backtest.py                    ← CLI entry point for walk-forward backtesting
│
│  ── Core AI / ML Pipeline ─────────────────────────────────────────────
├── core/
│   ├── __init__.py
│   ├── ai_service.py              ← Hub: 1000-analyst ensemble orchestrator
│   ├── accuracy_tracker.py        ← Sliding-window hit-rate tracking
│   ├── asset_registry.py          ← Factory registry mapping AssetClass → modules
│   ├── auto_engine.py             ← Signal → risk-managed order execution
│   ├── broker.py                  ← Broker ABC + LogBroker (JSONL)
│   ├── broker_service.py          ← Broker-agnostic facade
│   ├── claude_client.py           ← Claude CLI wrapper (signals, sentiment, chat)
│   ├── claude_personas.py         ← 5 Claude analyst personas
│   ├── consensus.py               ← Investment committee signal aggregator
│   ├── cpu_config.py              ← Centralised CPU core caps
│   ├── data_loader.py             ← yfinance OHLCV download + CSV cache
│   ├── database.py                ← SQLite persistence (snapshots, positions, PnL, chat)
│   ├── ensemble.py                ← 12-model ML ensemble (RF, XGB, LGB, LR, SVM, KNN)
│   ├── features.py                ← Base technical indicators + label creation
│   ├── features_advanced.py       ← 31 V2 features × 6 analyst specialties
│   ├── features_intraday.py       ← Intraday OHLC aggregation features
│   ├── forecaster_statistical.py  ← ARIMA(1,1,1) + Holt-Winters ETS baselines
│   ├── intraday_data.py           ← Sub-daily bar fetching
│   ├── model.py                   ← Legacy RandomForest train/load/predict
│   ├── news_agent.py              ← Background RSS + Claude batch sentiment
│   ├── pipeline_tracker.py        ← Thread-safe progress tracking
│   ├── regime.py                  ← Market regime detector (bull/bear/range/high-vol)
│   ├── risk_manager.py            ← Kelly criterion + ATR sizing + portfolio limits
│   ├── strategy.py                ← Probability → buy/sell/hold signal conversion
│   ├── strategy_profiles.py       ← Trading-style profiles (conservative, swing, etc.)
│   ├── strategy_selector.py       ← Regime-aware per-ticker profile assignment
│   ├── timeframe.py               ← Multi-horizon ensemble (1d / 5d / 20d)
│   ├── trading212.py              ← Trading 212 REST API v0 client
│   └── types_shared.py            ← Shared dataclasses (ModelSignal, ConsensusResult, etc.)
│
│  ── Desktop App (PySide6) — Two Editions ──────────────────────────────
├── desktop/
│   ├── __init__.py
│   ├── main.py                    ← Shared bootstrap: license, wizard, launch(mode)
│   ├── main_bloomberg.py          ← Entry point: Bloomberg edition
│   ├── main_simple.py             ← Entry point: Simple edition
│   ├── app.py                     ← Hub: MainWindow — Bloomberg-dark layout
│   ├── state.py                   ← Qt-aware AppState wrapper
│   ├── theme.py                   ← Bloomberg-dark QSS + mode overlays
│   ├── license.py                 ← License validation client
│   ├── updater.py                 ← Auto-update checker
│   ├── workers.py                 ← QThread background workers
│   ├── assets/
│   │   └── icon.ico               ← App icon
│   ├── panels/
│   │   ├── chart.py               ← Candlestick + volume chart
│   │   ├── chat.py                ← Claude chat panel
│   │   ├── news.py                ← News sentiment feed
│   │   ├── orders.py              ← Open orders + history
│   │   ├── pipeline.py            ← AI pipeline progress
│   │   ├── polymarket_markets.py  ← Polymarket markets panel
│   │   ├── positions.py           ← Portfolio positions + PnL
│   │   ├── settings.py            ← Settings editor
│   │   └── watchlist.py           ← Watchlist with signal columns
│   ├── dialogs/
│   │   ├── about.py               ← About dialog
│   │   ├── add_ticker.py          ← Add ticker input
│   │   ├── ai_recommend.py        ← AI recommendation dialog
│   │   ├── help.py                ← Keyboard shortcuts
│   │   ├── history.py             ← Signal history modal
│   │   ├── instruments.py         ← Instrument search
│   │   ├── license.py             ← License key entry dialog
│   │   ├── mode_selector.py       ← Stocks/Polymarket/Simple selector
│   │   ├── pies.py                ← T212 pies management
│   │   ├── search_ticker.py       ← Ticker search
│   │   ├── setup_wizard.py        ← First-run setup wizard
│   │   └── trade.py               ← Place trade dialog
│   └── simple/                    ← Simple edition (website aesthetic)
│       ├── __init__.py
│       ├── app.py                 ← SimpleWindow — card-based layout
│       ├── theme.py               ← Outfit font, black/green minimal QSS
│       └── widgets/
│           ├── header.py          ← Header bar with title + buttons
│           └── ticker_card.py     ← Stock card widget
│
│  ── TUI Terminal (Textual, dev-only) ──────────────────────────────────
├── terminal/
│   ├── app.py                     ← TradingTerminalApp — Textual lifecycle
│   ├── state.py                   ← AppState dataclass
│   ├── views.py                   ← UI panels
│   ├── pipeline_view.py           ← Pipeline progress view
│   ├── history_views.py           ← History modals
│   ├── charts.py                  ← Sparkline charts
│   └── terminal.css               ← Bloomberg-dark Textual CSS
│
│  ── Server & Website ──────────────────────────────────────────────────
├── server/
│   ├── app.py                     ← FastAPI license server + admin API
│   └── blank.db                   ← SQLite license database
│
├── website/
│   ├── index.html                 ← Landing page (Outfit font, minimal)
│   └── admin.html                 ← Admin panel (config, users, system status)
│
│  ── Backtesting Engine ────────────────────────────────────────────────
├── backtesting/
│   ├── types.py                   ← BacktestConfig, TradeRecord, PerformanceMetrics
│   ├── data_prep.py               ← Feature pre-computation + walk-forward splits
│   ├── engine.py                  ← Per-fold: train → predict → simulate
│   ├── simulator.py               ← Trade execution: stops, slippage, sizing
│   ├── metrics.py                 ← Sharpe, Sortino, Calmar, drawdown, attribution
│   └── runner.py                  ← Parallel fold executor
│
│  ── Multi-Asset Packages ──────────────────────────────────────────────
├── crypto/                        ← Crypto asset pipeline (8 files)
├── polymarket/                    ← Polymarket prediction pipeline (10 files)
│
│  ── Research (separate git repos) ─────────────────────────────────────
├── research/                      ← Autonomous strategy research
├── research_polymarket/           ← Polymarket edge research
│
│  ── Autoconfig ────────────────────────────────────────────────────────
├── autoconfig/
│   └── universe.py                ← Ticker universe definitions for backtesting
│
│  ── Build & Distribution ──────────────────────────────────────────────
├── installer/
│   ├── bloomberg.spec             ← PyInstaller spec: blank.exe
│   └── bloomberg.iss              ← Inno Setup: BlankSetup.exe
├── build.bat                      ← Builds blank.exe + BlankSetup.exe
├── version_info.py                ← PyInstaller Windows version resource
│
│  ── Tests & Scripts ───────────────────────────────────────────────────
├── tests/
│   ├── conftest.py                ← pytest fixtures
│   └── test_features.py           ← Feature engineering tests
├── scripts/
│   └── generate_icon.py           ← Icon generation utility
│
│  ── Config & Documentation ────────────────────────────────────────────
├── config.json                    ← Runtime configuration
├── requirements.txt               ← Python dependencies
├── .env.example                   ← API key template
├── CLAUDE.md                      ← AI agent instructions
├── README.md                      ← Project readme
├── LICENSE                        ← Licence file
│
│  ── Runtime Artifacts (git-ignored) ───────────────────────────────────
├── data/                          ← Cached OHLCV CSV files
├── models/                        ← Trained model artifacts
├── logs/                          ← LogBroker order logs
├── dist/                          ← Built executables + installers
└── docs/                          ← Markdown documentation
    ├── ARCHITECTURE.md
    ├── CHANGELOG.md
    ├── CODING_STANDARDS.md
    ├── CONTRACTS.md
    ├── CURRENT_TASKS.md
    ├── DIRECTORY_STRUCTURE.md     ← This file
    ├── SYSTEM_OVERVIEW.md
    ├── CODE_SIGNING.md
    └── systems/                   ← Per-module documentation
```

## Rules

- Core ML/AI modules live in `core/`. All entry points add `core/` to `sys.path`.
- TUI-specific code lives in `terminal/`; PySide6 desktop code lives in `desktop/`.
- Two separate installers: Bloomberg edition (stocks/polymarket) and Simple edition.
- Multi-asset packages (crypto/, polymarket/) mirror core module patterns.
- One class/module per file (hub files are the explicit exception).
- `data/`, `models/`, `logs/`, `dist/` are runtime artifacts — never commit.
- `research/` and `research_polymarket/` are independent git repos.
