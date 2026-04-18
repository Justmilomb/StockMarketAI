# Current Tasks

## Active Phase: Phase 4+ — Claude-native rebuild

The app has been rebuilt around the Claude Agent SDK. The hand-rolled
ML pipeline (ensemble, regime, consensus, auto-engine) has been
deleted. Claude is now the brain; Python is a typed tool bus.

### Completed

**Phase 1–3.6 — pre-rebuild milestones** (ML pipeline, TUI, desktop
app, commercialisation, simple edition). See `docs/CHANGELOG.md` for
the full history — everything before 2026-04-09 is legacy.

**Rebuild Phase 1 — Strangler fig skeleton** — 2026-04-09
- [x] `core/agent/` package created with empty tool modules
- [x] `agent` section added to `config.json`
- [x] `agent_memory` + `agent_journal` tables in sqlite
- [x] Agent menu added to desktop app (disabled)

**Rebuild Phase 2 — Tool bus + SDK integration** — 2026-04-10
- [x] `claude-agent-sdk==0.1.58` pinned in `requirements.txt`
- [x] `core/agent/tools/` — broker, market, risk, memory, watchlist, flow tools
- [x] `core/agent/mcp_server.py` — `create_sdk_mcp_server` wiring
- [x] `core/agent/context.py` — per-iteration context
- [x] `core/agent/prompts.py` — autonomous PM system prompt
- [x] `scripts/agent_repl.py` — one-iteration smoke harness

**Rebuild Phase 3 — Delete the ML pipeline** — 2026-04-11
- [x] 18 files deleted from `core/` (ai_service, auto_engine, consensus,
  claude_personas, ensemble, features*, forecaster_statistical, regime,
  strategy*, timeframe, model, accuracy_tracker, intraday_data,
  pipeline_tracker)
- [x] `desktop/app.py` stripped of pipeline refresh, TRADE_INSTRUCTIONS
  regex, two-phase refresh, strategy/risk auto-execute paths
- [x] `desktop/panels/pipeline.py` → `desktop/panels/agent_log.py`
- [x] `desktop/state.py` agent-centric shape; DEFAULT_CONFIG stripped
- [x] `desktop/main.py` remote config rewired to `agent.*` keys

**Rebuild Phase 4 — Agent runner + UI wiring** — 2026-04-12
- [x] `core/agent/runner.py` — `AgentRunner` QThread, asyncio loop,
  streaming tool calls, stop/kill, soft-stop on message boundary
- [x] `desktop/panels/agent_log.py` — start/stop/kill buttons, paper
  indicator, live log tail
- [x] `desktop/app.py` Agent menu + lifecycle slots, closeEvent
  agent shutdown, chat routed to running agent
- [x] `state.agent_running` / `agent_paper_mode` / `last_iteration_ts`
  / `agent_journal_tail` wired

**Rebuild Phase 5 — Scraper expansion 24/7** — 2026-04-13
- [x] `core/scrapers/base.py` — `ScraperBase` with rate-limited GET,
  UA rotation, per-source health tracking, safe-fail
- [x] 9 scrapers: google_news, yahoo_finance, bbc, bloomberg,
  marketwatch, youtube, stocktwits, reddit, x (via gnews)
- [x] `core/database.py` — `scraper_items` table + save/get/purge helpers
- [x] `core/scrapers/runner.py` — background daemon thread, cycles
  every 5 min, writes to sqlite, bounded retention (7 days)
- [x] `core/agent/tools/news_tools.py` — `get_news`, `subscribe_news`,
  `get_scraper_health`
- [x] `core/agent/tools/social_tools.py` — `get_social_buzz`,
  `get_market_buzz`
- [x] `desktop/app.py` — scraper runner started at boot, stopped on close

### Completed (cont.)

**Rebuild Phase 6 — UI polish + verification** — 2026-04-13
- [x] Settings panel rewired to show agent/account info instead of
  dead ML pipeline fields
- [x] `README.md`, `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`,
  `docs/SYSTEM_OVERVIEW.md`, `docs/DIRECTORY_STRUCTURE.md` rewritten
  for the Claude-native architecture
- [x] `docs/systems/*.md` cleanup — deleted 12 stale ML-module docs
  (auto-engine, consensus, ensemble, features*, regime, strategy,
  timeframe, model, claude-personas, forecaster-statistical,
  autoconfig), added `agent-runner.md` and `scrapers.md`, rewrote
  `desktop-app.md`
- [x] `website/index.html` copy updated to the "autonomous AI trader"
  story (`claude drives · news & social 24/7 · terminal-dark ui`)
- [x] `installer/blank.spec` hiddenimports cleaned (dropped 16
  deleted ML modules, added `core.agent.*`, `core.scrapers.*`,
  `claude_agent_sdk`)
- [x] `build.bat` produces `dist/blank.exe` successfully (291 MB);
  .exe launches, Qt event loop runs, no import errors.
  `blank-setup.exe` requires Inno Setup 6 (not installed on this
  machine) — `.iss` script is up to date.

**Rebuild Phase 7 — Research browser tool** — 2026-04-13
- [x] `core/agent/tools/browser_tools.py` — `fetch_page(url, max_chars)`
  with SSRF guard, per-iteration rate limit (10 fetches), 1 MB body
  cap, stdlib `urllib.request` + `ssl.create_default_context()` so
  the Python 3.14 / OpenSSL 3 Windows SSL trust-store issue doesn't
  bite, `lxml`-based article extraction preferring `<article>` →
  `<main>` → longest `<div>`, Content-Type filter
- [x] `core/agent/mcp_server.py` wires `BROWSER_TOOLS` into
  `ALL_TOOLS`; agent sees `mcp__blank__fetch_page`
- [x] `core/agent/prompts.py` tool-catalogue entry + standing rule
  #8 explicitly forbidding `fetch_page` as a price feed
- [x] `tests/test_browser_tools.py` — 10 pytest cases covering
  guard rails (empty URL, bad scheme, localhost, RFC1918, loopback,
  rate limit), happy path (article extraction, truncation, bad
  content-type), and journal row writes. `pytest` run: 10 passed
- [x] `docs/CONTRACTS.md` — added "Tool bus ↔ the web" section with
  input/output shape and full invariant list

**Rebuild Phase 8 — Market awareness, backtest sanity, integration
tests** — 2026-04-14
- [x] `core/scrapers/base.py` — custom `_StdlibSSLAdapter` mounted on
  `requests.Session` so the dev-box Python 3.14 + urllib3 + Windows
  trust-store bug stops biting. Verified live against example.com.
- [x] `core/market_hours.py` — 13-exchange registry (US, LSE, XETRA,
  Euronext Paris/Amsterdam, BME, Borsa Italiana, SIX, Nasdaq Nordics,
  Oslo, TASE), `Exchange` dataclass with timezone + weekday mask,
  `status()` returning is_open + next_open + next_close in local time,
  `exchange_for_ticker()` parsing T212 suffixes including the
  lowercase-'l' London convention.
- [x] `core/agent/tools/market_hours_tools.py` — `get_market_status`
  tool joining the registry to the broker's positions, returning
  per-exchange is_open + positions_count + position_tickers and a
  global open_count. Wired into `mcp_server.ALL_TOOLS`.
- [x] `core/agent/tools/backtest_tools.py` — lean
  `simulate_stop_target(ticker, stop_pct, target_pct, hold_days,
  lookback_days)` sliding stop/target sim over daily OHLCV from
  `core.data_loader`. Pessimistic same-bar collisions, returns
  win_rate/expectancy/best/worst/n_trades. Does **not** revive the
  deleted `backtesting/engine.py` ML pipeline.
- [x] `core/agent/prompts.py` — tool catalogue entries for
  market-hours + backtesting; standing rule #9 telling Claude to call
  `get_market_status` early and use it to drive
  `next_check_in_minutes` when the markets are closed.
- [x] `desktop/panels/exchanges.py` — terminal-style MARKETS panel
  (QGroupBox + QTableWidget + 30s QTimer) showing 13 venues with
  OPEN/CLOSED/local time/next transition/positions count. Wired
  into `desktop/app.py` MainWindow, included in the stocks dock
  group, and refreshed alongside POSITIONS in `_refresh_all_panels`.
- [x] `tests/test_agent_loop.py` — 12 integration tests covering
  context lifecycle, the full ALL_TOOLS shape (every tool has
  callable `.handler` + `.name`, no duplicates, allowed_tool_names
  matches), MCP server build, broker/place_order happy + ownership-
  refusal paths with a MagicMock broker, `get_market_status`
  bucketing, and `end_iteration` mutating runner signals. All 12
  green. Combined with `test_browser_tools.py` the agent test suite
  is 22 tests, ~7 s.
- [x] `installer/blank.spec` hiddenimports updated for
  `core.market_hours`, `core.agent.tools.market_hours_tools`,
  `core.agent.tools.backtest_tools`, `desktop.panels.exchanges`.

**Rebuild Phase 9 — Opus 4.7 upgrade, transcript scraper, UI polish** — 2026-04-16
- [x] `config.json` — `ai` block rewritten with plain-string model IDs
  (no base64), supervisor pinned to `claude-opus-4-7`, workers to
  `claude-opus-4-7` / `claude-sonnet-4-6` / `claude-haiku-4-5-20251001`,
  plus `effort_supervisor=max` / `effort_decision=high` /
  `effort_info=medium` / `effort_research_deep=high` /
  `effort_research_quick=medium`.
- [x] `core/agent/model_router.py` — added `supervisor_effort`,
  `decision_effort`, `info_effort`, `chat_worker_effort`,
  `research_effort` accessors; `_coerce_effort` validator enforces
  the SDK's `low|medium|high|max` literal.
- [x] `core/agent/runner.py` / `chat_worker.py` / `research_worker.py`
  — pass `effort=<tier>` through to `ClaudeAgentOptions`; logged in
  the startup log_line.
- [x] `core/agent/tools/watchlist_tools.py` — extracted
  `add_to_watchlist_sync` plain helper; MCP tool calls it.
- [x] `core/agent/tools/broker_tools.py` — `place_order` auto-adds
  the ticker to the watchlist on successful BUY, never blocks the
  order on a watchlist failure.
- [x] `core/agent/prompts.py` — "Small capital, small wins" section
  (£200 accounts, pennies = wins, bank 0.5–2 % gains); "Operating
  mode" updated for the new 45 s default cadence.
- [x] `config.json` — `cadence_seconds: 90 → 45`.
- [x] `desktop/panels/positions.py` — currency-aware `_format_price`
  (`$` / `£` / `€`, GBX → £ via /100).
- [x] `desktop/panels/orders.py` — 6-column rewrite, 200-row cap,
  coloured `Status` column (FILLED / PENDING / CANCELLED / REJECTED).
- [x] `desktop/app.py` — `get_order_history(limit=200)`;
  `state.research_findings` populated via
  `history_manager.get_research_findings`.
- [x] `desktop/panels/watchlist.py` — removed Verdict / Signal /
  AI Rec / Consensus columns and the dead `compute_verdict` helper;
  7 columns now (Ticker, Live Px, Day %, Prob, Conf, Sentiment,
  Strategy).
- [x] `core/database.py` — schema migration: `sentiment_score REAL`
  and `sentiment_label TEXT` on `scraper_items`; included in
  `save_scraper_items` / `get_scraper_items`.
- [x] `core/scrapers/_sentiment.py` — VADER-based `score_text` +
  `score_item`, thresholds ±0.1 → bullish / bearish / neutral.
- [x] `core/scrapers/runner.py` — scores every item before save.
- [x] `core/agent/tools/news_tools.py` — `_row_to_public` returns
  `sentiment_score` + `sentiment_label` to the agent.
- [x] `desktop/panels/news.py` — full rewrite: WATCHLIST SENTIMENT,
  AGENT RESEARCH (role / ticker-or-MKT / confidence / type /
  relative time / headline, colour-coded), MARKET NEWS with a
  per-item VADER badge.
- [x] `core/agent/prompts_research.py` — rule #5 allows findings for
  unknown tickers and `ticker=null` market-wide signals, capped at
  60 % confidence.
- [x] `core/agent/research_roles.py` — new `market_scanner` deep
  role (Sonnet tier, 600 s cadence, `default_tickers=False`).
- [x] `core/scrapers/youtube_transcripts.py` +
  `_transcript_summariser.py` — new transcript scraper: @markets
  channel recent uploads + 24/7 live-stream rolling window,
  Haiku-summarised with a regex-extractive fallback.
- [x] `core/scrapers/__init__.py` — `YouTubeTranscriptsScraper`
  registered in `SCRAPERS`.
- [x] `requirements.txt` — `vaderSentiment>=3.3.2`,
  `youtube-transcript-api>=0.6.2`.

### Up Next

- [ ] (none currently — Phase 9 closed out this round of UX + model
  upgrades)

(Crypto + polymarket restore is deferred indefinitely; dormant code
stays bundled in the installer but is not exposed to the agent.)

### Blocked

- [ ] (none currently)

## How to Pick Up Work

1. Read `docs/ARCHITECTURE.md` for context.
2. Check "In Progress" — don't duplicate active work.
3. Pick from "Up Next" in order.
4. Complete the task + update the relevant docs.
5. Move the task to "Completed" with a date.
