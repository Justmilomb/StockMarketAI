# Profit Optimization Systems Implementation Plan

**Goal:** Add 10 profit-optimization systems to blankv1: order book depth, smart limit-order execution, momentum triggers, correlation engine, pre-market wake, multi-timeframe data, volume profile, whisper-weighting prompt edit, faster news cadence, and a backtest replay script.

**Architecture:** Five new MCP tool modules (`order_book_tools`, `multi_timeframe_tools`, `volume_profile_tools`, `momentum_tools`, `correlation_tools`), one new core module (`correlation_engine`), one new `momentum_triggers` JSON store on the paper broker, edits to `runner.py` for pre-market wake and to `broker_tools.place_order` for smart limit execution, scraper cadence floor + default reduced to 30s, prompt patch for whisper weighting, and a `scripts/backtest_replay.py` runner.

**Tech Stack:** Python 3.12, Claude Agent SDK MCP tools, pandas/numpy, yfinance, FMP provider (when active), pytest.

---

## Implementation order

The systems are mostly independent. Build them in this order to minimise rework:

1. #6 Multi-timeframe (pure MCP tool, no side effects)
2. #7 Volume profile (pure MCP tool)
3. #1 Order book (pure MCP tool, FMP-aware)
4. #3 Momentum triggers (new MCP tools + stop engine extension)
5. #4 Correlation engine (new module + MCP tools + scraper hook)
6. #2 Smart limit execution (mod to `place_order`)
7. #5 Pre-market wake (runner cadence patch)
8. #9 Faster news cadence (config + floor)
9. #8 Whisper weighting (prompt edit)
10. #10 Backtest replay script

Each system gets its own commit. After all 10, run `pytest tests/ -v` (best-effort; many ML tests need optional deps), commit any fixes, push to `main`.

---

## System #6 — Multi-timeframe MCP tool

**File created:** `core/agent/tools/multi_timeframe_tools.py`

Returns 1m, 5m, 15m, 1h candles for one ticker in a single call. Internally calls yfinance four times in parallel (ThreadPoolExecutor); accepts an `intervals` array so callers can shrink the set. Each interval returns the last N bars (default 60), normalised to pounds for `.L` tickers like the existing intraday tool.

Register in `core/agent/mcp_server.py`:
- import `MULTI_TIMEFRAME_TOOLS`
- splat into `ALL_TOOLS`

---

## System #7 — Volume profile MCP tool

**File created:** `core/agent/tools/volume_profile_tools.py`

`get_volume_profile(ticker, days)` — pulls daily OHLCV via `data_loader.fetch_ticker_data`, bins price levels into 20 buckets between window low and high, sums volume per bucket, returns sorted by volume desc. Top 5 buckets surface as "value area" support/resistance. Pure pandas — no new deps.

Register in `mcp_server.py`.

---

## System #1 — Order book / Level 2 MCP tool

**File created:** `core/agent/tools/order_book_tools.py`

`get_order_book(ticker)` — branches on the active provider:

- **FMP active:** placeholder for FMP order-book v3 endpoint. FMP's quote endpoint exposes `bid`, `ask`, `bidSize`, `askSize` only (no depth). Use that as the populated path; mark `depth_available: false` so the agent knows it's L1, not L2.
- **Default (yfinance):** call `yf.Ticker(t).fast_info` for `last_price`, `bid`, `ask`, plus `info["bidSize"]`, `info["askSize"]` when present. Return `{best_bid, best_ask, bid_size, ask_size, spread, spread_pct, depth_available: false}`.

Register in `mcp_server.py`.

---

## System #3 — Momentum detection in stop engine

**Files created:**
- `core/agent/tools/momentum_tools.py` — three tools: `set_momentum_trigger`, `list_momentum_triggers`, `cancel_momentum_trigger`.

**Files modified:**
- `core/paper_broker.py` — add `add_momentum_trigger`, `remove_momentum_trigger`, `list_momentum_triggers`, persisted in `paper_state.json` under `momentum_triggers`.
- `core/stop_engine.py` — extend `tick()` to also walk `paper_broker.list_momentum_triggers()`. For each trigger, maintain a rolling `_recent_prices: Dict[str, deque[(ts, price)]]` window of the last 10 seconds; when price moves `>= threshold_pct` in that window in the trigger's direction, fire a `submit_order` via the broker.
- `core/agent/mcp_server.py` — register `MOMENTUM_TOOLS`.

A trigger is `{trigger_id, ticker, direction: "up"|"down", threshold_pct, action: "buy"|"sell", quantity, ttl_ts}`. Triggers with `ttl_ts < now` are reaped on each tick.

---

## System #4 — Correlation trading engine

**Files created:**
- `core/correlation_engine.py` — defines `CORRELATION_RULES` (a hard-coded dict of trigger keys → list of `(ticker, direction, action)` tuples). Trigger keys are sector terms ("oil", "gold", "tech", "defense") and ticker symbols. Public function `match_correlations(text: str, watchlist: List[str]) -> List[CorrelationMatch]` lower-cases the text, scans for keys, and returns matches keyed to a side recommendation. Also exports `queue_correlation_action(match)` which writes a row into a sqlite table `correlation_signals` (created lazily) so the agent's next iteration can read pending suggestions.
- `core/agent/tools/correlation_tools.py` — three tools: `get_correlation_signals` (read pending), `acknowledge_correlation_signal` (mark resolved), `list_correlation_rules` (introspect).

**Files modified:**
- `core/scrapers/runner.py` — when items are saved, run `match_correlations(item["title"] + item["summary"], watchlist)` and `queue_correlation_action` for any matches. Reuse the existing `_wake_callback` to nudge the supervisor on a correlation hit.
- `core/database.py` — add `_init_correlation_signals` table init.
- `core/agent/mcp_server.py` — register `CORRELATION_TOOLS`.

Rules ship pre-populated: oil (`XOM`, `BP.L`, `SHEL.L`), tech (`NVDA`, `AAPL`, `MSFT`, `GOOGL`), gold (`GLD`, `NEM`, `GOLD`), defense (`BA.L`, `RR.L`, `LMT`).

---

## System #2 — Smart limit-order execution

**File modified:** `core/agent/tools/broker_tools.py`

When the agent calls `place_order` with `order_type="market"`, intercept:

1. Fetch L1 quote via `yf.Ticker.fast_info` (`bid`, `ask`).
2. If spread is `<= 0.5%` of mid, fall through to original market path (no edge to capture).
3. Otherwise:
   - Submit a limit order at the bid (buy) / ask (sell).
   - Sleep up to 30 s polling `get_order_executions(order_id)`. If filled, return the limit fill response.
   - If unfilled at 30 s, cancel the limit and submit market.
   - Journal both actions under `tags=["smart_exec", "limit_first"]`.

Wraps the smart logic in a helper `_smart_market_submit(...)` that's only reached for market orders; explicit limit/stop orders skip the helper and submit as-typed. Uses `asyncio.sleep` so the agent loop isn't blocked.

A new config flag `execution.smart_market_enabled` (default `true`) lets the user disable it.

---

## System #5 — Pre-market wake

**File modified:** `core/agent/runner.py`

Add `_seconds_until_pre_market_wake()` — checks `core.market_hours.next_open` for LSE and US, returns the wait in seconds until **30 minutes before** the next open (whichever is earlier). When that wait is **less than** the otherwise-computed cadence, override the sleep so the supervisor wakes pre-open.

The override applies during the closed-market sleep path only. When markets are open, we don't pre-empt cadence.

The hook lives in `_compute_wait_seconds`: after computing the closed-market default, take `min(default, pre_market_wait)`.

---

## System #9 — Faster news cadence (30 s)

**Files modified:**
- `core/scrapers/runner.py` — change `CADENCE_FLOOR_SECONDS = 60` → `30`.
- `core/config_schema.py` — change `NewsConfig.scraper_cadence_seconds` default `120` → `30`.
- `config.default.json` — change `news.scraper_cadence_seconds` `120` → `30`.

---

## System #8 — Earnings whisper weighting (prompt edit)

**File modified:** `core/agent/prompts.py`

Insert a new section after "## Hunting on your own initiative" titled "## Earnings whisper weighting" with the directive:

> Earnings whisper beats are more significant than consensus beats. When `earnings_whispers` data shows the actual EPS beat the *whisper* (not just the consensus), weight that signal higher in your decision: tighter sizing, faster reaction, longer hold. A consensus-only beat is already priced; a whisper beat is the surprise.

---

## System #10 — Paper-mode backtest replay

**File created:** `scripts/backtest_replay.py`

CLI: `python -m scripts.backtest_replay --days 30 [--ticker AAPL ...] [--output data/backtest_results.json]`.

Strategy: replay 30 days of yfinance daily bars per ticker on the active watchlist; for each day, run a simple rule-based stand-in for the agent (RSI/MACD cross signal from `core/agent/tools/indicator_tools` helpers) and simulate trades through an in-memory `PaperBroker` reset each run. Output JSON: `{tickers, days, win_rate, total_pnl, trades: [...], worst_trades: [top 5 by loss]}`.

This is a deterministic stand-in, not a fully-streamed agent replay. The user wants "logs what trades it would have made"; we use the same indicator logic the live agent uses, which is the closest deterministic proxy without spinning up the SDK.

The script registers under `python -m core.backtest --days 30` via a `core/backtest/__init__.py` + `__main__.py` entry that delegates to `scripts/backtest_replay.py`.

---

## Verification

After each system: import the module via `python -c "import core.agent.tools.<name>"` to catch syntax/import errors.

After all 10: `pytest tests/ -v` (best-effort — many tests need TF/HF that aren't installed).

`python -c "from core.agent.mcp_server import build_mcp_server; print(len(build_mcp_server().__dict__))"` to confirm registration sanity.

Then commit + push to `Justmilomb/blank` `main`.
