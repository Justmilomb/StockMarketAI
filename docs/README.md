# StockMarketAI

AI-driven stock trading terminal combining a 1000-analyst ensemble ML pipeline with Claude LLM analysis. Renders in a terminal-style Textual TUI or a PySide6 desktop app. Supports paper and live trading via Trading 212.

> **Warning:** This is for research and experimentation only. Do not trade real money without fully understanding and testing the system.

---

## Quick Start

```bash
# 1. Clone and create virtual environment
git clone <repo>
cd StockMarketAI
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
# Fill in T212_API_KEY and optionally ANTHROPIC_API_KEY

# 4. Run the TUI terminal
python ai.py

# 5. Or run the desktop app
python -m desktop.main

# 6. Or run a backtest
python backtest.py --ticker AAPL MSFT --start 2023-01-01
```

---

## Architecture

StockMarketAI runs a 1000-analyst ensemble pipeline on each refresh cycle. Every signal source is treated as one "analyst vote" and the investment committee aggregates them into a final buy/sell/hold recommendation.

### Signal Families

| Family | Components | Description |
|--------|-----------|-------------|
| ML Ensemble | 12 diverse models × 3 horizons | Random Forest, Gradient Boosting, Ridge, SVM, KNN, and more across 1d/5d/20d horizons |
| Statistical | ARIMA, ETS | Classical time-series baselines via statsmodels |
| Deep Learning | N-BEATS | Neural basis expansion forecaster (optional, requires PyTorch) |
| Meta-Ensemble | 3-family combiner | Weighted combination of ML + Statistical + Deep families |
| MiroFish | 1000 agents × 9 types × 16 Monte Carlo simulations | Agent-based market simulation across all CPU cores |
| Claude LLM | 5 analyst personas | Fundamental, technical, macro, sentiment, and risk analysts via Claude CLI |
| Regime Detector | Bull / bear / sideways / volatile | Conditions the ensemble weights on current market regime |
| Risk Manager | Kelly criterion + ATR sizing | Position sizing and stop-loss levels |
| Investment Committee | Consensus aggregator | Weights all signal families into a final signal with confidence score |

### Pipeline Flow

```
Market Data (yfinance)
  │
  ├─ Feature Engineering (31 V2 features, 6 analyst groups)
  │
  ├─ ML Ensemble (12 models × 3 horizons)
  ├─ Statistical Forecasters (ARIMA/ETS)
  ├─ Deep Forecaster (N-BEATS, optional)
  │   └─ Meta-Ensemble (combines all three families)
  │
  ├─ MiroFish Simulation (1000 agents, Monte Carlo)
  ├─ Regime Detection
  ├─ Claude LLM Personas (5 analysts, async)
  │
  └─ Investment Committee Consensus
        └─ Risk Manager → Strategy → Signal (BUY/SELL/HOLD + confidence)
```

---

## Entry Points

| File | Purpose |
|------|---------|
| `ai.py` | TUI terminal — launches the Textual terminal-style interface |
| `desktop/main.py` | PySide6 desktop app — GUI with the same pipeline |
| `backtest.py` | Walk-forward backtesting CLI |
| `autoconfig/run.py` | Autonomous parameter optimisation (Claude CLI sessions) |

---

## Configuration

### `config.json`
All runtime settings. Key sections:

- `tickers` — watchlist of symbols to analyse
- `strategy` — buy/sell thresholds, `max_positions`, `position_size_fraction`
- `capital` — notional account size for position sizing
- `model_path` — where trained ML artifacts are saved
- `data_dir` — CSV cache location
- `auto_engine` — full-auto trading settings
- `mirofish` — simulation parameters (agents, ticks, Monte Carlo runs)

### `.env`
Secrets only — never in `config.json` or source code:

```
T212_API_KEY=your_trading212_api_key
T212_PRACTICE=true                   # Set false for live account
ANTHROPIC_API_KEY=your_key           # Optional: for Claude API calls
```

---

## TUI Terminal

Terminal-dark Textual TUI with a 3x4 grid layout:

- Watchlist panel with per-ticker signal, confidence, and regime
- Consensus and ensemble metadata columns
- Real-time pipeline progress bars (per model family)
- Model dashboard with per-model vote breakdown
- News feed with sentiment scores
- Positions and account panel (live T212 data)
- Interactive chart with sparklines
- AI chat interface (persisted across sessions)
- History modals: snapshots, PnL, instrument breakdown

Key bindings: `r` refresh, `t` trade, `a` add ticker, `c` chart, `h` history, `?` help.

---

## Desktop App

PySide6 GUI with terminal-dark theme, wrapping the same AI pipeline. Suitable for running as a standalone executable.

### Build executable

```bash
pyinstaller trading.spec --clean
```

Output: `dist/trading.exe`. Place a `.env` file next to it for broker credentials. Or just run `build.bat`.

---

## Backtesting

Walk-forward validation engine with parallel fold execution across all CPU cores.

```bash
# Full backtest on all watchlist tickers
python backtest.py

# Specific tickers and date range
python backtest.py --ticker AAPL MSFT TSLA --start 2022-01-01

# Fast mode: signal accuracy only, no trade simulation
python backtest.py --fast

# Print fold-by-fold breakdown
python backtest.py --folds

# Limit CPU cores
python backtest.py --cores 4
```

Metrics reported: Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor, signal accuracy, return attribution by model family.

---

## Autoconfig

Autonomous parameter optimisation that uses Claude Code CLI sessions to explore the config parameter space via repeated backtesting.

```bash
python autoconfig/run.py                   # Default: 10 experiments per session
python autoconfig/run.py --batch-size 20   # 20 experiments per session
python autoconfig/run.py --max-sessions 50 # Stop after 50 sessions
python autoconfig/run.py --dry-run         # Print the command without running
```

Results are persisted to `autoconfig/results.tsv`. The best configuration found is saved to `autoconfig/best_config.json`. Press `Ctrl+C` at any time to stop — progress is saved.

---

## Broker Integration

The broker layer is abstracted behind `BrokerService`:

| Broker | When used | What it does |
|--------|----------|--------------|
| `LogBroker` | Default (no API key) | Logs orders to `logs/orders.jsonl` |
| `Trading212Broker` | `T212_API_KEY` set | Submits orders via Trading 212 REST API v0 |

Set `T212_PRACTICE=true` in `.env` to use the T212 practice (paper) account. Never set `false` without fully understanding what you are doing.

---

## Project Structure

See `docs/DIRECTORY_STRUCTURE.md` for a full annotated file tree.

---

## Docs

| File | Contents |
|------|---------|
| `docs/ARCHITECTURE.md` | System graph and data flow |
| `docs/SYSTEM_OVERVIEW.md` | Runtime lifecycle and tech stack |
| `docs/CONTRACTS.md` | Public interface contracts |
| `docs/CURRENT_TASKS.md` | Active and planned work |
| `docs/DIRECTORY_STRUCTURE.md` | Annotated file tree |
| `docs/systems/` | Deep-dives on individual subsystems |
