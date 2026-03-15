# System Overview

## Project Goal

An AI-driven stock trading terminal that combines machine learning predictions (RandomForest) with LLM analysis (Google Gemini) to generate actionable buy/sell/hold signals, displayed in a Bloomberg-style terminal UI. Supports paper trading via log broker and live trading via Trading 212 API.

## Runtime Lifecycle

### CLI Mode (`python daily_agent.py`)
1. Load `config.json` → extract tickers, date range, strategy params
2. Download OHLCV data via yfinance (with CSV caching)
3. Engineer technical features across all tickers
4. Train or load RandomForest model
5. Predict P(tomorrow up) for each ticker's latest features
6. Generate buy/sell/hold signals via strategy thresholds
7. Route buy signals through LogBroker → `logs/orders.jsonl`

### TUI Mode (`python terminal/app.py`)
1. Load `config.json` → initialise AppState, AiService, BrokerService
2. Initialise Gemini client + NewsAgent (background thread)
3. Mount Textual grid: metrics | watchlist | chat | positions | chart | news
4. Start refresh timer (default 15s)
5. Each refresh cycle:
   - AutoEngine checks mode + signals → submits orders if full_auto
   - AiService computes weighted ensemble (sklearn 50% + gemini 30% + news 20%)
   - BrokerService fetches positions + account info
   - NewsAgent fetches RSS headlines + Gemini sentiment (async)
   - All views update from shared AppState
6. User interacts via keybindings: trade, add/remove tickers, chat, chart, AI recommendations

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.12+ | Ecosystem for ML + data + TUI |
| ML Model | scikit-learn (RandomForest) | Simple, interpretable, fast to train |
| LLM | Google Gemini API | Signal generation, sentiment, chat |
| Market Data | yfinance | Free, reliable OHLCV data |
| Data Processing | pandas + numpy | Industry standard for tabular data |
| TUI Framework | Textual | Rich terminal UIs with grid layout |
| Model Serialisation | joblib | scikit-learn standard |
| Live Broker | Trading 212 REST API v0 | User's chosen broker |
| News | feedparser (RSS) | Lightweight headline fetching |

## Key Constraints

- All secrets (API keys) via environment variables, never in code or config
- Broker defaults to paper mode (LogBroker) unless API key configured
- Model artifacts saved to `models/`, not git-tracked
- CSV cache in `data/`, not git-tracked
- No real money trades without explicit broker API key + practice=false
- Gemini API calls are synchronous; rate limits apply
- News agent runs on a daemon thread — no cleanup guarantees on crash
