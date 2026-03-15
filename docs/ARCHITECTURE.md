# Architecture

## System Graph

```
                         ┌──────────────────────────────┐
                         │       ENTRY POINTS           │
                         │  ai.py  │  terminal/app.py   │
                         └────┬────┴────────┬───────────┘
                              │             │
                    ┌─────────┘     ┌───────┘
                    ▼               ▼
            ┌──────────────┐  ┌─────────────────────────┐
            │ daily_agent  │  │  TradingTerminalApp      │
            │ (CLI runner) │  │  (Textual TUI — hub)     │
            └──────┬───────┘  └──┬───┬───┬───┬───┬──────┘
                   │             │   │   │   │   │
        ┌──────────┘   ┌─────────┘   │   │   │   └──────────┐
        ▼              ▼             ▼   │   ▼              ▼
  ┌───────────┐  ┌───────────┐  ┌──────┐ │ ┌──────────┐ ┌──────────┐
  │ AiService │  │ AutoEngine│  │State │ │ │NewsAgent │ │ terminal │
  │ (hub)     │  │           │  │      │ │ │(bg thrd) │ │ views/   │
  └──┬──┬──┬──┘  └───────────┘  └──────┘ │ └──────────┘ │ charts   │
     │  │  │                              │              └──────────┘
     │  │  └──────────────────┐           │
     │  │                     ▼           ▼
     │  │              ┌─────────────┐  ┌──────────────┐
     │  │              │gemini_client│  │BrokerService │
     │  │              │ (Gemini API)│  │  (facade)    │
     │  │              └─────────────┘  └──┬───────┬───┘
     │  │                                  │       │
     │  ▼                                  ▼       ▼
     │ ┌────────┐                   ┌─────────┐ ┌──────────────┐
     │ │strategy│                   │LogBroker│ │Trading212    │
     │ └────────┘                   │(paper)  │ │Broker (live) │
     │                              └─────────┘ └──────────────┘
     ▼
  ┌──────────────┐
  │ ML Pipeline  │
  │ data_loader  │──► features ──► model
  │ (yfinance)   │    (tech ind)   (RandomForest)
  └──────────────┘
```

## Data Flow

```
yfinance  →  CSV cache  →  feature engineering  →  RandomForest P(up)
                                                          │
                                                          ▼
Gemini API  →  P(up) + reason  ──────────────────►  weighted ensemble
                                                     (sklearn × 0.5 +
                                                      gemini × 0.3 +
                                                      news   × 0.2)
                                                          │
                                                          ▼
RSS feeds  →  Gemini sentiment  ─────────────────►  strategy signals
                                                     (buy/sell/hold)
                                                          │
                                                          ▼
                                                   broker execution
                                                   (log or T212 API)
```

## Subsystem Responsibilities

| System | Owns | Must NOT |
|--------|------|----------|
| data_loader | OHLCV download, CSV caching | Touch model or strategy logic |
| features | Technical indicator calculation, label creation | Import model or broker |
| model | RF training, validation, serialisation | Know about tickers or strategy |
| gemini_client | All Gemini API communication | Access broker or data_loader |
| strategy | Probability → signal conversion | Train models or call APIs |
| broker / broker_service | Order submission, position/account queries | Know about ML or features |
| auto_engine | Automated signal → order loop | Modify broker or AI logic |
| news_agent | RSS fetching, sentiment via Gemini | Submit orders or modify state directly |
| terminal/app | TUI lifecycle, action routing, view wiring | Implement business logic |
| terminal/state | Shared AppState dataclass | Contain methods or logic |
| terminal/views | UI rendering, user input | Call broker or AI directly |
| terminal/charts | Sparkline rendering | Fetch data directly |

## Key Types / Schemas

| Type | Location | Purpose |
|------|----------|---------|
| ConfigDict | `Dict[str, Any]` | Runtime config loaded from `config.json` |
| AppState | `terminal/state.py` | Shared TUI state (signals, positions, chat, etc.) |
| AiService | `ai_service.py` | ML + Gemini orchestrator |
| BrokerService | `broker_service.py` | Broker-agnostic facade |
| Broker (ABC) | `broker.py` | Abstract broker interface |
| StrategyConfig | `strategy.py` | Buy/sell thresholds, position limits |
| ModelConfig | `model.py` | RF hyperparams, model path, train split |
| GeminiConfig | `gemini_client.py` | Model name, API key env var |
| TickerNews | `news_agent.py` | Per-ticker sentiment + headlines |
| FEATURE_COLUMNS | `features.py` | Canonical list of model input features |

## Phase Map

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Core ML pipeline: data → features → model → signals → broker | Done |
| 2 | TUI terminal, Gemini integration, news agent, Trading 212 | Done |
| 3 | Testing, backtesting, advanced strategies, multi-model | Planned |
| 4 | Production hardening, monitoring, deployment | Planned |
