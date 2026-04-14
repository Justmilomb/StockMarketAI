# Directory Structure

```
StockMarketAI/
│
│  ── Entry points ──────────────────────────────────────────────────────
├── backtest.py                    CLI walk-forward backtester (legacy, not
│                                  wired to the agent yet)
│
│  ── Core ──────────────────────────────────────────────────────────────
├── core/
│   ├── __init__.py
│   ├── agent/                     Claude-native agent runtime
│   │   ├── runner.py              AgentRunner QThread (asyncio inside)
│   │   ├── mcp_server.py          create_sdk_mcp_server wiring
│   │   ├── prompts.py             autonomous PM system prompt
│   │   ├── context.py             per-iteration AgentContext
│   │   └── tools/                 Typed MCP-exposed tool bus
│   │       ├── broker_tools.py    get_portfolio, place_order, cancel_order,
│   │       │                      get_pending_orders, get_order_history
│   │       ├── market_tools.py    get_live_price, get_intraday_bars,
│   │       │                      get_daily_bars, search_instrument
│   │       ├── risk_tools.py      size_position (Kelly + ATR)
│   │       ├── memory_tools.py    read/write_memory, read/append_journal
│   │       ├── watchlist_tools.py get/add/remove_from_watchlist
│   │       ├── news_tools.py      get_news, subscribe_news, get_scraper_health
│   │       ├── social_tools.py    get_social_buzz, get_market_buzz
│   │       └── flow_tools.py      end_iteration, sleep_until
│   ├── scrapers/                  24/7 news + social feeds
│   │   ├── base.py                ScraperBase, ScrapedItem, ScraperHealth
│   │   ├── runner.py              Background daemon thread
│   │   ├── google_news.py
│   │   ├── yahoo_finance.py
│   │   ├── bbc.py
│   │   ├── bloomberg.py
│   │   ├── marketwatch.py
│   │   ├── youtube.py
│   │   ├── stocktwits.py
│   │   ├── reddit.py
│   │   └── x_via_gnews.py
│   ├── asset_registry.py          AssetClass → modules factory
│   ├── broker.py                  Broker ABC + LogBroker
│   ├── broker_service.py          Broker-agnostic facade
│   ├── trading212.py              Trading 212 REST v0 client
│   ├── risk_manager.py            Kelly + ATR sizing (size_position)
│   ├── data_loader.py             yfinance OHLCV + CSV cache
│   ├── database.py                SQLite persistence
│   ├── news_agent.py              Legacy panel sentiment helper
│   ├── claude_client.py           Chat + ticker-search helper for panels
│   ├── cpu_config.py              Central CPU core caps
│   └── types_shared.py            Shared dataclasses
│
│  ── Desktop app (PySide6 Bloomberg edition) ────────────────────────────
├── desktop/
│   ├── main.py                    Shared bootstrap (license, wizard, launch)
│   ├── main_bloomberg.py          Entry point
│   ├── app.py                     Hub: MainWindow
│   ├── state.py                   DEFAULT_CONFIG + init_state
│   ├── theme.py                   Bloomberg-dark QSS
│   ├── design.py                  Palette / typography tokens
│   ├── license.py                 License validation client
│   ├── updater.py                 Auto-update checker
│   ├── workers.py                 Leftover generic QThread helpers
│   ├── assets/
│   │   └── icon.ico
│   ├── panels/
│   │   ├── agent_log.py           Live agent feed + start/stop/kill
│   │   ├── chart.py               Candlestick + volume chart
│   │   ├── chat.py                User chat → agent loop
│   │   ├── news.py                News sentiment feed
│   │   ├── orders.py              Open orders + history
│   │   ├── polymarket_markets.py  Polymarket markets (on ice)
│   │   ├── positions.py           Portfolio positions + PnL
│   │   ├── settings.py            Account + agent status readout
│   │   └── watchlist.py           Active tickers
│   └── dialogs/
│       ├── about.py
│       ├── add_ticker.py
│       ├── ai_recommend.py
│       ├── help.py
│       ├── history.py
│       ├── instruments.py
│       ├── license.py
│       ├── mode_selector.py
│       ├── pies.py
│       ├── search_ticker.py
│       ├── setup_wizard.py
│       └── trade.py
│
│  ── TUI terminal (Textual, dev-only) ──────────────────────────────────
├── terminal/                      Legacy Textual TUI, kept for dev only
│
│  ── Server & website ──────────────────────────────────────────────────
├── server/
│   ├── app.py                     FastAPI license server + admin API
│   └── blank.db                   License database
│
├── website/
│   ├── index.html                 Landing page
│   └── admin.html                 Admin panel
│
│  ── Backtesting engine (legacy) ───────────────────────────────────────
├── backtesting/
│   ├── types.py                   BacktestConfig, TradeRecord, PerformanceMetrics
│   ├── data_prep.py               Feature pre-compute + walk-forward split
│   ├── engine.py                  Per-fold: train → predict → simulate
│   ├── simulator.py               Trade execution simulation
│   ├── metrics.py                 Sharpe, Sortino, Calmar, drawdown
│   └── runner.py                  Parallel fold executor
│
│  ── Multi-asset packages (on ice) ─────────────────────────────────────
├── crypto/                        Crypto asset pipeline
├── polymarket/                    Polymarket prediction pipeline
│
│  ── Research (separate git repo, unrelated) ───────────────────────────
├── research/                      Autonomous strategy research side-project
│
│  ── Helpers ───────────────────────────────────────────────────────────
├── autoconfig/
│   └── universe.py                Ticker universe helper (used by research/)
│
│  ── Build & distribution ──────────────────────────────────────────────
├── installer/
│   ├── bloomberg.spec             PyInstaller spec
│   └── bloomberg.iss              Inno Setup script
├── build.bat                      Builds blank.exe + BlankSetup.exe
├── version_info.py                PyInstaller version resource
│
│  ── Tests & scripts ───────────────────────────────────────────────────
├── tests/
│   ├── conftest.py                pytest fixtures
│   └── test_features.py           Feature engineering regression
├── scripts/
│   ├── agent_repl.py              One-iteration smoke harness
│   └── generate_icon.py           Icon generation utility
│
│  ── Config & docs ─────────────────────────────────────────────────────
├── config.json                    Runtime configuration
├── requirements.txt               Python dependencies
├── .env.example                   Env var template
├── CLAUDE.md                      AI agent instructions
├── README.md                      Project readme
├── LICENSE                        Licence file
│
│  ── Runtime artifacts (git-ignored) ───────────────────────────────────
├── data/                          Cached OHLCV CSVs + terminal_history.db
├── logs/                          LogBroker order logs
├── dist/                          Built executables + installers
└── docs/
    ├── ARCHITECTURE.md            System diagram + data flow invariants
    ├── CHANGELOG.md
    ├── CODING_STANDARDS.md
    ├── CONTRACTS.md               Inter-subsystem interface contracts
    ├── CURRENT_TASKS.md           Phase tracker + up-next list
    ├── DIRECTORY_STRUCTURE.md     This file
    ├── SYSTEM_OVERVIEW.md         High-level runtime lifecycle
    ├── CODE_SIGNING.md
    ├── AGENT_WORKFLOW.md
    └── systems/                   Per-module documentation
        ├── agent-runner.md
        ├── scrapers.md
        ├── desktop-app.md
        ├── broker.md
        ├── claude-client.md
        ├── cpu-config.md
        ├── data-loader.md
        ├── database.md
        ├── news-agent.md
        ├── risk-manager.md
        ├── backtesting.md
        └── terminal.md
```

## Rules

- `core/agent/` owns everything Claude-native. All SDK calls live in
  `runner.py` and `mcp_server.py`; a version bump only touches two
  files.
- `core/scrapers/` is UI-framework agnostic — no PySide6 imports.
- `desktop/` is the only place Qt lives. Panels are one file per
  concern; the hub is `app.py`.
- `research/` is a separate git repo; never touch it from this codebase.
- `data/`, `logs/`, `dist/` are runtime artifacts — never commit.
- Hub files (`desktop/app.py`, `core/agent/runner.py`, `config.json`,
  `requirements.txt`) are Boss-owned; feature agents must not edit
  them without dispatching back.
