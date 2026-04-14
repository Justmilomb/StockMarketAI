# System Overview

## Project goal

**blank** by Certified Random is a desktop trading terminal where
Claude is the decision-maker. The hand-rolled ML pipeline
(ensembles, regime, consensus, auto-engine) was deleted in Phase 3 of
the rebuild. Python is now a typed tool bus — a small set of
MCP-registered functions Claude calls on demand. Live trading via
Trading 212, paper-by-default via `LogBroker`, Bloomberg-dark PySide6
UI.

## Runtime lifecycle

### Desktop (`python desktop/main_bloomberg.py`)

1. `desktop/main.py` — PyInstaller `freeze_support`, `.env` load,
   license check, setup wizard if needed, QSS apply.
2. `MainWindow.__init__`:
   - `load_config("config.json")` → merged into `DEFAULT_CONFIG`
   - `init_state(config)` → `AppState` dataclass
   - `BrokerService(config)` constructed (LogBroker by default)
   - `HistoryManager("data/terminal_history.db")`
   - `NewsAgent` (legacy, for news panel sentiment only)
   - `ScraperRunner(db, watchlist_provider).start()` — 24/7 daemon
   - Panels built and wired into the grid
3. User chooses Agent → Start. `MainWindow.start_agent()`:
   - Lazy-constructs `AgentRunner(config_path, broker_service, db_path)`
   - Connects Qt signals to panel slots
   - Calls `runner.start()` (QThread entry)
4. Loop: AgentRunner spawns one fresh Claude Code subprocess per
   iteration, streams tool calls + text chunks via Qt signals, panels
   update live. `sleep(cadence)`, repeat.
5. User can chat at any time — `ChatPanel` calls
   `runner.send_user_message(text)` and the next iteration fires
   immediately with the message prepended.
6. Stop / Kill / closeEvent — soft-stop flag, 3 s wait, then
   `terminate()`. Scraper runner stopped too.

### Backtest CLI (`python backtest.py`)

Walk-forward engine that long-preceded the rebuild. Still functional
against the broker facade and data loader but **not** wired to the
agent (yet). Tracked under "Up Next" in `docs/CURRENT_TASKS.md` as
`backtest_tools`.

### Dev harness (`python scripts/agent_repl.py`)

Spawns one agent iteration against the LogBroker and prints the full
tool-call transcript to stdout. Useful for smoke-testing tool wiring
without launching Qt.

## Subsystems at a glance

```
core/agent/runner.py    AgentRunner QThread: Claude Agent SDK loop
core/agent/mcp_server   create_sdk_mcp_server(name, version, tools)
core/agent/context      per-iteration AgentContext (config, broker, db, risk)
core/agent/prompts      autonomous PM system prompt
core/agent/tools/       broker, market, risk, memory, watchlist,
                        news, social, flow — typed MCP-exposed

core/scrapers/          9 sources (google_news, yahoo_finance, bbc,
                        bloomberg, marketwatch, youtube, stocktwits,
                        reddit, x) + daemon runner
core/broker_service     Trading 212 / LogBroker facade
core/trading212         Trading 212 REST client
core/risk_manager       Kelly + ATR sizing (size_position tool)
core/data_loader        yfinance daily OHLCV + CSV cache
core/database           sqlite persistence (agent_memory,
                        agent_journal, scraper_items, history)
core/news_agent         legacy panel sentiment helper

desktop/app.py          MainWindow, panel wiring, agent lifecycle
desktop/state.py        DEFAULT_CONFIG + init_state
desktop/main_bloomberg  Bloomberg edition entry point
desktop/panels/         agent_log, chart, chat, news, orders,
                        positions, settings, watchlist
desktop/dialogs/        setup wizard, license, add ticker, trade…
```

## Tech stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.12+ | Primary ecosystem |
| Agent runtime | `claude-agent-sdk==0.1.58` | Subprocess-per-iteration; uses Claude Code subscription — no API key |
| UI | PySide6 (Qt6) | Windows-native look, rich panels |
| Persistence | SQLite via `core/database.py` | Zero-ops, handles agent memory + scraper cache + history |
| Market data | yfinance | Free daily OHLCV (15-20 min delayed) + 1m bars last 7 days |
| Live prices | Trading 212 `/equity/portfolio` | Free live price for held positions |
| News | feedparser + custom scrapers | Lightweight, 9 free sources |
| Broker | Trading 212 REST v0 | User's choice; LogBroker fallback for paper |
| Packaging | PyInstaller + Inno Setup | `build.bat` produces `BlankSetup.exe` |

## Key constraints

- **No paid API keys.** Agent loop uses the user's Claude Code
  subscription via `claude-agent-sdk`, never the Messages API.
- **Paper mode default.** `agent.paper_mode = true` forces
  `broker.type = "log"` at runtime. Live trading only via explicit
  opt-in.
- **Allowed tools capped.** `mcp__blank__*` only — no Bash, Read,
  Write. The agent cannot shell out.
- **Hard iteration caps.** 40 tool calls, 360 s wall clock, cadence
  floor 30 s. Kill switch on the Agent menu.
- **Scrapers never raise.** `safe_fetch` wraps every source; a broken
  endpoint returns `[]` and bumps a health counter.
- **Every read is a tool call.** `place_order` re-fetches the broker
  portfolio before submitting, which kills the "sell 0 owned" class of
  bug by construction.

## What got deleted

Phase 3 of the rebuild removed 18 files from `core/`: `ai_service`,
`auto_engine`, `consensus`, `claude_personas`, `ensemble`,
`features*`, `forecaster_statistical`, `regime`, `strategy*`,
`timeframe`, `model`, `accuracy_tracker`, `intraday_data`,
`pipeline_tracker`. The `autoconfig/` runner, `mirofish/` agent sim,
and N-BEATS deep forecaster are also gone. Only `autoconfig/universe.py`
remains as a ticker universe helper for `research/` (a separate
side-project with its own git history).

## Known limits

- yfinance daily data is 15-20 min delayed. Intraday 1m bars are
  capped at the last 7 days. Real tick data needs a paid feed.
- Instagram and Facebook scraping is not realistic — both gate too
  aggressively. StockTwits, Reddit, and Google News cover the rest.
- `LogBroker` (paper) doesn't simulate fills perfectly; it logs
  orders and marks them as filled at last price. Practice mode on
  Trading 212 is the more realistic option.
