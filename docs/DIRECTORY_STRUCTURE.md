# Directory Structure

```
StockMarketAI/
├── ai.py                       ← Legacy entry point (calls daily_agent)
├── ai_service.py               ← Hub: ML + Gemini orchestration
├── auto_engine.py              ← Automated signal → order execution
├── broker.py                   ← Broker ABC + LogBroker + Trading212Broker
├── broker_service.py           ← Broker-agnostic facade
├── config.json                 ← Hub: all runtime configuration
├── daily_agent.py              ← CLI pipeline runner
├── data_loader.py              ← yfinance download + CSV caching
├── features.py                 ← Technical indicator engineering
├── gemini_client.py            ← Google Gemini API wrapper
├── model.py                    ← RandomForest train/load/predict
├── news_agent.py               ← Background RSS + sentiment agent
├── strategy.py                 ← Probability → signal conversion
├── requirements.txt            ← Hub: Python dependencies
├── setup.bat                   ← Windows: create venv + install deps
├── run.bat                     ← Windows: activate venv + launch TUI
├── CLAUDE.md                   ← AI agent entry point (this scaffold)
├── README.md                   ← Human-facing project readme
├── MASTER_PROMPT.md            ← Template used to generate this scaffold
│
├── terminal/                   ← TUI presentation layer
│   ├── app.py                  ← Hub: TradingTerminalApp (Textual App)
│   ├── state.py                ← AppState shared dataclass
│   ├── views.py                ← UI panels + modal screens
│   ├── charts.py               ← Sparkline price charts
│   └── terminal.css            ← Bloomberg-dark CSS theme
│
├── data/                       ← Cached OHLCV CSV files (git-ignored)
├── models/                     ← Trained model artifacts (git-ignored)
├── logs/                       ← Order logs from LogBroker (git-ignored)
│
├── tests/                      ← Test files (to be created)
│   ├── test_features.py
│   ├── test_model.py
│   ├── test_strategy.py
│   └── test_broker.py
│
└── docs/                       ← All documentation (authoritative)
    ├── ARCHITECTURE.md
    ├── SYSTEM_OVERVIEW.md
    ├── CURRENT_TASKS.md
    ├── CONTRACTS.md
    ├── CODING_STANDARDS.md
    ├── AGENT_WORKFLOW.md
    ├── TESTING.md
    ├── LINTING.md
    ├── DIRECTORY_STRUCTURE.md
    ├── CHANGELOG.md
    ├── plans/                  ← Design docs (date-prefixed)
    └── systems/                ← Atomic per-system docs (~150 words)
        ├── data-loader.md
        ├── features.md
        ├── model.md
        ├── gemini-client.md
        ├── strategy.md
        ├── broker.md
        ├── news-agent.md
        ├── auto-engine.md
        └── terminal.md
```

## Rules

- Source files are flat in project root (no `src/` directory).
- TUI-specific code goes in `terminal/`.
- One class/module per file.
- Tests mirror source structure in `tests/`.
- `docs/` is the authoritative knowledge base. Code comments supplement, not replace.
- `docs/systems/` contains one ~150-word doc per system/module.
- `docs/plans/` contains dated design documents for major features.
- `data/`, `models/`, and `logs/` are runtime artifacts — never commit.
