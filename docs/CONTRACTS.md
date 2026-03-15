# Interface Contracts

Explicit contracts between every system pair that communicates.
Breaking any of these is a regression.

---

## AiService ↔ data_loader

**Access pattern:** AiService calls `fetch_universe_data()` to get raw OHLCV DataFrames.

**AiService calls on data_loader:**
| Function | When | Returns |
|----------|------|---------|
| `fetch_universe_data(tickers, start_date, end_date, data_dir, use_cache)` | On signal generation or retrain | `Dict[str, pd.DataFrame]` — ticker → OHLCV DataFrame |
| `fetch_live_prices(tickers)` | On TUI refresh | `Dict[str, Dict[str, float]]` — ticker → {price, change_pct} |

**Invariants:**
- Returned DataFrames always have columns: Open, High, Low, Close, Volume
- Index is DatetimeIndex named "Date"
- Empty DataFrame raises `ValueError`, never returns silently
- Cache files are CSV in `data/` directory

---

## AiService ↔ features

**Access pattern:** AiService calls feature functions to build model inputs.

**AiService calls on features:**
| Function | When | Returns |
|----------|------|---------|
| `build_universe_dataset(universe_data)` | Training | `(X: ndarray, y: ndarray, meta: DataFrame)` |
| `latest_feature_rows_per_ticker(universe_data)` | Inference | `(features_df: DataFrame, meta_df: DataFrame)` |

**Invariants:**
- `X` columns always match `FEATURE_COLUMNS` in exact order
- `y` is binary: 0 or 1 (tomorrow's close higher)
- `meta` always has columns `[ticker, date]`
- `features_df` is indexed by ticker symbol
- NaN rows are dropped before return — callers can assume clean data

---

## AiService ↔ model

**Access pattern:** AiService trains or loads the RandomForest model.

**AiService calls on model:**
| Function | When | Returns |
|----------|------|---------|
| `train_model(X, y, meta, config)` | First run or retrain | `RandomForestClassifier` |
| `load_model(model_path)` | Subsequent runs | `RandomForestClassifier` |

**Invariants:**
- `train_model` always saves to `config.model_path` before returning
- `load_model` raises `FileNotFoundError` if model file missing
- Model expects input shape matching `FEATURE_COLUMNS` length (10 features)
- `predict_proba()[:, 1]` gives P(tomorrow up)

---

## AiService ↔ gemini_client

**Access pattern:** AiService creates GeminiClient and calls for per-ticker signals.

**AiService calls on gemini_client:**
| Function | When | Returns |
|----------|------|---------|
| `get_signal_for_ticker(ticker, recent_closes, features, ...)` | Per-ticker signal | `{"p_up_gemini": float, "reason": str}` |
| `analyze_portfolio(positions, signals_df)` | AI insights | `str` (natural language) |
| `suggest_ticker(current_tickers)` | Ticker suggestion | `str` (ticker symbol or "") |

**Invariants:**
- `p_up_gemini` is always clamped to [0.0, 1.0]
- On API failure, returns defaults (p_up=0.5, reason="Could not parse")
- GeminiClient raises `RuntimeError` if API key env var not set
- All Gemini responses are parsed as JSON; markdown code blocks stripped

---

## AiService ↔ strategy

**Access pattern:** AiService passes ensemble probabilities to `generate_signals()`.

**AiService calls on strategy:**
| Function | When | Returns |
|----------|------|---------|
| `generate_signals(prob_up, meta_latest, config, held_tickers)` | Signal generation | `DataFrame` with columns [ticker, date, prob_up, signal] |

**Invariants:**
- `signal` is always one of: `"buy"`, `"sell"`, `"hold"`
- Buy signals limited to `config.max_positions` count
- Sell signals only emitted for tickers in `held_tickers`
- Output sorted by `prob_up` descending

---

## TradingTerminalApp ↔ BrokerService

**Access pattern:** App calls BrokerService facade; never touches Broker directly.

**App calls on BrokerService:**
| Function | When | Returns |
|----------|------|---------|
| `get_positions()` | Each refresh | `List[Dict]` with keys: ticker, quantity, avg_price, current_price, unrealised_pnl |
| `get_account_info()` | Each refresh | `Dict` with keys: free, invested, result, total |
| `submit_order(ticker, side, quantity, order_type, ...)` | Trade execution | `Dict` with keys: ticker, side, quantity, status |
| `get_pending_orders()` | Each refresh | `List[Dict]` |
| `cancel_order(order_id)` | User action | `bool` |

**Invariants:**
- BrokerService falls back to LogBroker if Trading 212 API key is missing
- `side` is always `"BUY"` or `"SELL"` (uppercase)
- `order_type` is one of: `"market"`, `"limit"`, `"stop"`, `"stop_limit"`
- Failed orders return `status: "FAILED"` with `error` key, never raise

---

## AutoEngine ↔ AiService + BrokerService

**Access pattern:** AutoEngine calls AiService for signals, then BrokerService for execution.

**Invariants:**
- AutoEngine only runs when `state.mode == "full_auto_limited"`
- Daily loss check: if unrealised PnL < -(capital × max_daily_loss), skip all orders
- Orders are always market orders with quantity 1.0

---

## NewsAgent ↔ GeminiClient

**Access pattern:** NewsAgent calls `gemini_client.analyze_news()` for sentiment scoring.

**Invariants:**
- NewsAgent runs on a daemon thread — no guarantee of clean shutdown
- `sentiment` is always in [-1.0, 1.0]
- Headlines capped at 15 per ticker
- News data stored as `TickerNews` dataclass instances

---

## terminal/app ↔ terminal/state

**Access pattern:** App writes to AppState; views read from AppState.

**Invariants:**
- Only `terminal/app.py` mutates AppState (via `_update_state_and_views`)
- Views only read from state in `refresh_view()` — never mutate
- `signals` can be `None` before first refresh completes
- `chat_history` entries always have keys: `role` ("user" or "ai"), `text`
