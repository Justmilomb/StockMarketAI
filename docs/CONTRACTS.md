# Interface Contracts

Contracts between every subsystem pair that communicates. Breaking
any of these is a regression — the Phase 3 rewrite deliberately
narrowed the app's surface to a handful of well-typed seams.

---

## AgentRunner ↔ claude-agent-sdk

**Access pattern:** `AgentRunner._run_one_iteration` spawns one fresh
Claude Code subprocess per iteration via `claude_agent_sdk.query()`.

**Calls on the SDK:**
| Function | When | Returns |
|----------|------|---------|
| `query(prompt, options)` | Once per iteration | Async iterator of messages |
| `create_sdk_mcp_server(name, version, tools)` | Once per iteration | In-process MCP server object passed to `ClaudeAgentOptions.mcp_servers` |

**Invariants:**
- The `options.allowed_tools` list is hard-capped to the `mcp__blank__*`
  namespace. No Bash / Read / Write / Glob; the agent cannot escape
  the tool bus.
- `permission_mode="bypassPermissions"` — every tool in our bus is
  safe-by-construction, so we don't want the SDK to prompt.
- `max_turns = agent.max_tool_calls_per_iter` (config, default 40).
- Wall-clock deadline is checked in Python on every message
  boundary, independent of the SDK.
- Iterating the async generator can be broken out of at any time;
  the SDK cleans up the subprocess in its `finally`.

---

## AgentRunner ↔ MainWindow

**Access pattern:** `MainWindow` owns a single `AgentRunner` QThread
instance created lazily when the user starts the agent.

**Qt signals emitted by AgentRunner:**
| Signal | Payload | Meaning |
|--------|---------|---------|
| `status_changed` | `bool` | `True` when the loop is alive |
| `iteration_started` | `str iteration_id` | New subprocess about to spawn |
| `iteration_finished` | `str iteration_id, str summary` | `end_iteration` return or wall-clock hit |
| `tool_use` | `dict {name, input, iteration_id}` | An MCP tool call fired |
| `tool_result` | `dict {content, is_error, iteration_id}` | Tool call result streamed back |
| `text_chunk` | `str` | Raw assistant text block |
| `log_line` | `str` | Pre-formatted journal line |
| `error_occurred` | `str` | Fatal runner error |

**Calls on AgentRunner from MainWindow:**
| Call | When | Effect |
|------|------|--------|
| `send_user_message(text)` | Chat submit while agent is alive | Queues a user message and sets `_interrupt_sleep` so the next iteration fires immediately |
| `request_stop()` | Stop button / Kill button | Soft-stop flag checked at every message boundary and during sleep |

**Invariants:**
- All signals are auto-marshalled onto the GUI thread via
  `Qt.QueuedConnection`, so slots are safe to touch widgets.
- Chat messages sent via `send_user_message` are prepended to the
  next iteration's prompt, not dropped.
- Stop is soft: the current iteration can finish cleanly. Kill is
  the same soft-stop plus a 3-second `wait()` before `terminate()`.

---

## Tool bus ↔ core.agent.context

**Access pattern:** every tool module calls `get_agent_context()` to
reach the current iteration's broker service, sqlite DB, risk
manager, and config.

**Context shape (`core.agent.context.AgentContext`):**
| Field | Type | Set by |
|-------|------|--------|
| `config` | `dict` | Runner, loaded fresh from `config.json` each iteration |
| `broker_service` | `BrokerService` | Runner — paper-mode uses a forced-`log` copy |
| `db` | `HistoryManager` | Runner |
| `risk_manager` | `RiskManager` | Runner |
| `iteration_id` | `str` | Runner (8-char uuid hex) |
| `paper_mode` | `bool` | Runner, copied from `agent.paper_mode` |
| `end_requested` | `bool` | `end_iteration` tool |
| `next_wait_minutes` | `int` | `end_iteration` tool (0 = use default cadence) |
| `end_summary` | `str` | `end_iteration` tool |

**Invariants:**
- `init_agent_context` is called once at the start of every iteration,
  `clear_agent_context` in the `finally`.
- Tools never mutate `config` persistently — `watchlist_tools` is
  the one exception and it writes back to disk via `_save_config`.

---

## Scrapers ↔ HistoryManager

**Access pattern:** `ScraperRunner` fetches from every scraper in
`core.scrapers.SCRAPERS` on a schedule and writes results to
`scraper_items` via `db.save_scraper_items`. Agent tools
(`news_tools`, `social_tools`) read back via
`db.get_scraper_items`.

**Table: `scraper_items`**
| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `fetched_at` | TEXT | DB-side `datetime('now')` at insert |
| `source` | TEXT | `ScraperBase.name` |
| `kind` | TEXT | `"news"` or `"social"` |
| `ticker` | TEXT NULL | Normalised symbol (broker suffix stripped) |
| `title` | TEXT NOT NULL | Headline / post body |
| `url` | TEXT NULL | Link back to source |
| `ts` | TEXT NULL | Publisher timestamp (ISO) if available |
| `summary` | TEXT | Up to 500 chars |
| `meta_json` | TEXT | Source-specific extras (upvotes, channel, etc.) |
| `sentiment_score` | REAL NULL | VADER compound score in `[-1,+1]` |
| `sentiment_label` | TEXT NULL | `bullish` / `bearish` / `neutral` |

**Unique constraint:** `(source, url, title)` — `INSERT OR IGNORE`
dedupes across cycles.

**Invariants:**
- Scrapers **never raise** out of `safe_fetch`; failures increment
  health counters and return `[]`.
- `save_scraper_items` returns the number of *new* rows inserted
  (duplicates silently skipped).
- `get_scraper_items` orders by `COALESCE(ts, fetched_at) DESC`.
- `purge_old_scraper_items(keep_days=7)` is called on every cycle.
- **Sentiment scoring.** `ScraperRunner._run_cycle` calls
  `core.scrapers._sentiment.score_item` on every fetched item before
  `save_scraper_items`. VADER is pure-Python and runs in microseconds
  so it scales with the per-cycle item count; Haiku is reserved for
  transcript summarisation (`_transcript_summariser.py`).
- **Transcript source.** `YouTubeTranscriptsScraper` pulls captions
  from the @markets channel and the 24/7 live stream via
  `youtube-transcript-api`. Each video is summarised once (Haiku) and
  cached in-process by `video_id`; the class name references the
  data source only — UI copy never uses the brand.

---

## Tool bus ↔ BrokerService

**Access pattern:** `broker_tools` is a thin typed wrapper over
`BrokerService`, which is unchanged from the pre-rebuild codebase.

**Broker calls the tools make:**
| Tool | BrokerService method | Notes |
|------|---------------------|-------|
| `get_portfolio` | `get_account_info`, `get_positions` | Always re-fetched; no cache |
| `get_pending_orders` | `get_orders` | |
| `get_order_history` | `get_order_history(limit)` | |
| `place_order` | `place_order(ticker, side, qty, ...)` | Re-fetches portfolio first; auto-adds to watchlist on BUY |
| `cancel_order` | `cancel_order(order_id)` | |

**Invariants:**
- `place_order` is the **only** mutating broker call in the tool
  bus. Everything else is read-only.
- **Watchlist auto-add on BUY.** When `place_order` succeeds with
  `side="buy"`, the tool calls
  `watchlist_tools.add_to_watchlist_sync` and attaches the result
  under `watchlist_add` in the JSON payload. A watchlist failure
  never blocks the order.
- Paper-mode forces `broker.type="log"` via `_force_paper_config`
  in the runner; a `LogBroker` instance serves every read/write.

---

## Tool bus ↔ the web (browser_tools.fetch_page)

**Access pattern:** `browser_tools.fetch_page` is the only tool in
the bus that talks to arbitrary URLs. It's deliberately narrow — one
call, one URL, cleaned-article text back. Everything else (news,
social, prices) goes through typed readers backed by the scraper
daemon or the broker.

**Inputs / outputs:**
| Field | Type | Notes |
|-------|------|-------|
| `url` | `str` | `http://` or `https://` only |
| `max_chars` | `int` | Clamped to `[500, 20000]`; default `8000` |
| returns | `dict` | `{url, host, status, title, text, truncated, bytes, fetch_count, fetches_remaining}` on success; `{error, url, ...}` on failure |

**Invariants:**
- **Hard cap of 10 fetches per iteration**, tracked on
  `ctx.stats["browser_fetches"]`. Errors still burn budget.
- **Body cap of 1 MB** — streamed with `urlopen().read(chunk)` and
  truncated mid-stream if the server sends more.
- **SSRF guard**: localhost, `::1`, `0.`, `10.`, `127.`, `169.254.`,
  `172.16-31.`, `192.168.` hosts are rejected before any network hit.
- **Scheme guard**: only `http` / `https` allowed.
- **Content-type filter**: only responses whose Content-Type contains
  `html`, `xml`, `text`, or `json` are returned; everything else
  errors out with `unsupported content-type`.
- **Stdlib urllib**, not `requests`/`httpx`, because Python 3.14 +
  OpenSSL 3 on Windows doesn't plumb the system trust store through
  urllib3's custom SSL context. `ssl.create_default_context()`
  does the right thing.
- **Not a price feed**: the system prompt explicitly forbids using
  `fetch_page` to poll quote pages. Agents must call `get_live_price`
  for anything price-shaped.
- Every attempt writes one row to `agent_journal` with
  `kind='browser_fetch'`, `tool='fetch_page'`, `tags='browser'` so
  the UI log can show fetches in real time.

---

## Research swarm ↔ HistoryManager

**Access pattern:** Every worker in the research swarm writes findings
through `research_tools.submit_finding`, which calls
`db.save_research_finding`. The supervisor (and the Information
panel, via `get_research_findings`) reads them back.

**`submit_finding` inputs:**
| Field | Type | Notes |
|-------|------|-------|
| `ticker` | `str` NULL | **Nullable.** `null` means market-wide signal; any other value is accepted, even if not on the current watchlist (discovery path) |
| `finding_type` | `str` | One of `alert`, `sentiment`, `catalyst`, `thesis`, `pattern` |
| `headline` | `str` | Required — short one-liner |
| `confidence_pct` | `int` | Clamped to `[0, 100]`; discovery findings capped at 60 by prompt |
| `detail` | `str` | Optional — free-form notes |
| `source` | `str` | Optional — where it came from |
| `methodology` | `str` | Optional |
| `evidence` | `str` | Optional — stored as JSON-wrapped text |

**Invariants:**
- `ticker=null` is stored as `NULL`; the Information panel renders it
  as `MKT` (market-wide).
- Tickers outside the active watchlist are valid — the supervisor
  decides whether to promote them via `add_to_watchlist`.
- `role` is read from the agent's contextvars (`ctx.stats["research_role"]`)
  so the worker can't spoof another role's attribution.
- Findings never expire silently — `purge_old_research_data` runs
  hourly from the swarm coordinator with `keep_days=30`.

---

## Tool bus ↔ market hours

**Access pattern:** `market_hours_tools.get_market_status` reads the
static exchange registry in `core.market_hours` and joins it against
the broker's current positions. No HTTP, no broker writes, no
filesystem touches outside the journal row.

**Tool surface:**
| Tool | Returns |
|------|---------|
| `get_market_status()` | `{exchanges: [{code, name, country, timezone, is_open, next_open, next_close, local_now, positions_count, position_tickers}], open_count, total_positions, unmapped_tickers}` |

**Invariants:**
- Exchange registry is **regular hours only** — weekends are closed,
  holidays are *not* modelled. The broker is the source of truth for
  "the market rejected my order".
- `exchange_for_ticker` covers every Trading 212 retail UK suffix
  (`_US_EQ`, `_UK_EQ`/`_GB_EQ`/lowercase-l London, `_DE_EQ`, `_FR_EQ`,
  `_NL_EQ`, `_ES_EQ`, `_IT_EQ`, `_CH_EQ`, `_SE_EQ`, `_NO_EQ`,
  `_DK_EQ`, `_FI_EQ`, `_IL_EQ`). Unknown suffixes land under
  `unmapped_tickers`.
- All times are emitted in the exchange's local timezone (ISO,
  minute precision). `zoneinfo` handles DST.
- The standing rule in `prompts.py` tells Claude to call this tool
  early and feed `next_check_in_minutes` from the longest "next
  open" gap when its positions' markets are closed.

---

## Tool bus ↔ historical backtest sim

**Access pattern:** `backtest_tools.simulate_stop_target` calls
`data_loader.fetch_ticker_data` (the same yfinance path the rest of
the app uses) and runs an in-process loop. No engine, no ML imports,
no parallelism. Cheap.

**Tool surface:**
| Tool | Returns |
|------|---------|
| `simulate_stop_target(ticker, stop_pct, target_pct, hold_days, lookback_days)` | `{ticker, stop_pct, target_pct, hold_days, lookback_days, bars_used, first_bar, last_bar, n_trades, wins, losses, flats, win_rate, avg_return_pct, expectancy_pct, best_trade_pct, worst_trade_pct}` or `{error, ticker}` |

**Invariants:**
- Long-only. Entry simulated at each bar's close; exit on first of
  stop, target, or `hold_days` bars (close-out at that point).
- Same-bar stop/target collisions resolve to the **stop** (pessimistic).
- `stop_pct` clamped to `[0.1, 50]`, `target_pct` to `[0.1, 200]`,
  `hold_days` to `[1, 30]`, `lookback_days` to `[30, 730]`.
- Does **not** revive `backtesting/engine.py` — that module's lazy
  imports still reference deleted ML files (`features_advanced`,
  `ensemble`, `strategy_selector`, `strategy_profiles`) and will
  raise at runtime. Treat the engine as dead code until/unless we
  either rewrite or delete it.

---

## Risk Manager ↔ tool bus

**Access pattern:** `risk_tools.size_position` is the only
tool-exposed entry point. `RiskManager.generate_risk_enhanced_orders`
was deleted in Phase 3 along with the ML pipeline.

**Tool surface:**
| Tool | Returns |
|------|---------|
| `size_position(ticker, conviction, stop_loss_pct)` | `{ticker, suggested_qty, dollar_amount, rationale}` |

**Invariants:**
- `conviction` is in `[0.0, 1.0]`.
- `size_position` never places an order — only the agent (via
  `place_order`) can do that.

---

## DesktopApp ↔ config.json

**Access pattern:** `MainWindow.config` is loaded at boot by
`desktop/state.py:load_config`, and written back on every mutation
via `_save_config`. The agent runner reads `config.json` fresh on
every iteration so cadence/cap changes take effect live.

**Required sections:**
- `agent.*` — runner cadence, caps, paper mode, risk knobs
- `broker.*` — type, practice flag, env var names
- `watchlists.<name>` — list of tickers
- `active_watchlist` — key into `watchlists`
- `news.refresh_interval_minutes`, `news.scraper_cadence_seconds`

**Invariants:**
- `agent.paper_mode = true` always forces `broker.type = "log"` at
  runtime (enforced in `AgentRunner._force_paper_config`).
- The legacy `strategy`, `consensus`, `regime`, `timeframe`,
  `strategy_profiles`, `claude_personas`, `forecasters`, `pipeline`
  sections are **gone**. Loading an old config that still has them
  is tolerated (they're ignored).
