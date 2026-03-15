## 📉 Stock Market AI – Minimal Autonomous Agent

This repo now contains a **minimal, end-to-end trading agent** that:

- Downloads historical daily stock data with `yfinance`
- Builds technical-indicator features
- Trains a classifier to predict whether **tomorrow’s close will be higher than today’s**
- Generates daily **buy/hold signals** across a configurable universe of tickers
- Sends intended orders to a **pluggable broker layer** (currently a logging broker)

> **Warning:** This is for learning and experimentation only.  
> Do **not** trade real money based on this without fully understanding and testing it.

---

## 🧩 Project structure

- `data_loader.py` – downloads and caches OHLCV data for a list of tickers using `yfinance`.
- `features.py` – builds technical features (returns, moving averages, volatility, RSI) and a binary label: *will tomorrow's close be higher than today's?*
- `model.py` – trains a `RandomForestClassifier` with a **time-based** train/validation split and saves/loads the model with `joblib`.
- `strategy.py` – converts prediction probabilities into ranked **buy/hold** signals based on configurable thresholds.
- `broker.py` – defines a `Broker` interface and a `LogBroker` that logs orders to `logs/orders.jsonl` instead of placing real trades.
- `daily_agent.py` – orchestrator script that runs the full pipeline using `config.json`.
- `ai.py` – thin wrapper that just calls `daily_agent.main()` for backwards compatibility.
- `config.json` – configuration for tickers, date range, strategy thresholds, and capital assumptions.
- `requirements.txt` – Python dependencies.

---

## 🚀 Quick Start (Windows)

The easiest way to get started is to use the provided batch scripts:

1. **First time setup:** Run `setup.bat`. This creates a virtual environment and installs all dependencies.
2. **Run the app:** Run `run.bat`. This activates the environment and starts the terminal.

---

## 🛠 Manual Setup

1. **Create a virtual environment (recommended)**

   ```bash
   cd StockMarketAI
   python -m venv .venv
   .venv\Scripts\activate  # on Windows
   # source .venv/bin/activate  # on macOS / Linux
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

The agent is configured via `config.json`:

- `tickers`: list of symbols to evaluate each day.
- `start_date`, `end_date`: historical period to download for training.
- `data_dir`: folder where downloaded CSVs are cached.
- `model_path`: where the trained classifier is stored.
- `strategy`:
  - `threshold_buy`: minimum probability that tomorrow will be up to emit a **buy**.
  - `threshold_sell`: reserved for more advanced strategies (not yet used).
  - `max_positions`: maximum number of simultaneous buy signals.
  - `position_size_fraction`: fraction of notional capital per position.
- `capital`: notional account size, used to size positions conceptually.

You can edit `config.json` to change tickers, thresholds, and risk preferences.

---

## 🧠 How the agent works

1. **Data & features**
   - Downloads OHLCV data for all configured tickers.
   - Builds technical features such as short/medium-term returns, volatility, moving averages, and RSI.
   - Creates a binary label: `1` if tomorrow’s close is higher than today’s, else `0`.

2. **Model training**
   - Builds a combined dataset across all tickers.
   - Uses the `date` column to perform a time-based train/validation split.
   - Trains a `RandomForestClassifier` and prints validation metrics.
   - Saves the trained model to `models/rf_tomorrow_up.joblib`.

3. **Daily signals**
   - For each ticker, computes the **most recent** feature row.
   - Uses the trained model to estimate `P(up tomorrow)` for each ticker.
   - Ranks tickers by that probability and emits **buy** signals for those above `threshold_buy` (up to `max_positions`).

4. **Broker integration**
   - Uses `LogBroker`, which implements the `Broker` interface and simply logs orders.
   - Each order is appended as a JSON line to `logs/orders.jsonl`.
   - This makes it easy to later replace `LogBroker` with a real broker that talks to a trading API.

---

## ▶️ Running the agent

From the project root:

```bash
python daily_agent.py
```

Or, using the legacy entry point:

```bash
python ai.py
```

What happens:

- If no model file exists yet, it will train one and save it.
- It will print validation metrics (once per training).
- It will print today’s ranked signals and log any **buy** orders to `logs/orders.jsonl`.

---

## 🔌 Plugging in a real broker (future work)

The `Broker` abstraction in `broker.py` is designed so you can later:

- Implement a `CustomBroker(Broker)` that talks to your preferred trading API (Alpaca, IBKR, etc.).
- Wire in API keys using environment variables or a separate, private config file.
- Swap `LogBroker` for `CustomBroker` in `daily_agent.py` without changing any of the ML or strategy code.

Until that’s implemented and thoroughly tested, this project should be treated as a **paper-trading / signal-generation demo only**.

