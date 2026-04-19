# Architecture

## Overview

**blank** (rebranded StockMarketAI) is a desktop trading terminal where
Claude is the decision-maker. The old hand-rolled ML pipeline
(ensemble → regime → consensus → auto-engine) has been deleted.
Python is now a typed **tool bus** — a small set of MCP-registered
functions that Claude calls whenever it wants: fetch prices, read
news, compute Kelly sizing, place orders, etc.

```
┌─────────────────────────────────────────────────────────────────────┐
│ desktop/app.py  (Qt MainWindow, terminal-dark panels)               │
│                                                                     │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│   │ Chart    │ │ Positions│ │ News     │ │ Chat     │               │
│   │ Orders   │ │ Watchlist│ │ Agent log│ │ Settings │               │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘               │
│        └────────────┴────────────┴────────────┘                     │
│                     ▼                                               │
│                  AppState                                           │
│                     ▲                                               │
└─────────────────────┼───────────────────────────────────────────────┘
                      │ Qt signals — streamed from the runner
                      │
┌─────────────────────┴───────────────────────────────────────────────┐
│ core/agent/runner.py  (AgentRunner QThread)                         │
│                                                                     │
│   while not stop_requested:                                         │
│     spawn Claude Code subprocess via claude-agent-sdk               │
│     stream tool-call + text events → AppState via Qt signals       │
│     sleep(agent.cadence_seconds)                                    │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ claude-agent-sdk query(prompt, options)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Claude Code CLI (one fresh subprocess per iteration)                │
│                                                                     │
│   System prompt: autonomous PM + risk rules + kill conditions       │
│   MCP server "blank" (in-process, registered per iteration):        │
│     broker_tools    market_tools    risk_tools                      │
│     memory_tools    watchlist_tools news_tools                      │
│     social_tools    flow_tools                                      │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ in-process MCP calls
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ core/agent/tools/*.py  (typed, stateless, JSON-return)              │
│                                                                     │
│   broker_tools   → core/broker_service.py (T212 / LogBroker)        │
│   market_tools   → yfinance + T212 live prices                      │
│   risk_tools     → core/risk_manager.py (Kelly + ATR sizing)        │
│   memory_tools   → sqlite agent_memory + agent_journal              │
│   news_tools     → sqlite scraper_items + core/scrapers/*           │
│   social_tools   → sqlite scraper_items + core/scrapers/*           │
│   watchlist_tools→ config.json round-trip                           │
│   flow_tools     → end_iteration, sleep_until                       │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ core/scrapers/runner.py  (background daemon thread)                 │
│                                                                     │
│   Every 5 min:                                                      │
│     for scraper in SCRAPERS (10 sources):                           │
│       items = scraper.safe_fetch(tickers=watchlist)                 │
│       items = [score_item(i) for i in items]  # VADER sentiment    │
│       db.save_scraper_items(items)                                  │
│     db.purge_old_scraper_items(keep_days=7)                         │
│                                                                     │
│   Sources: google_news, yahoo_finance, bbc, bloomberg,              │
│            marketwatch, youtube, youtube_transcripts (captions),    │
│            stocktwits, reddit, x (via gnews)                        │
└─────────────────────────────────────────────────────────────────────┘
```

## Data flow invariants

1. **Every read is a tool call.** The agent never acts on a cached
   snapshot. `place_order` re-fetches the broker portfolio before
   submitting, which makes the "sell 0 owned" class of bug impossible
   by construction.
2. **One Claude subprocess per iteration.** `AgentRunner` spawns a
   fresh `query()` call each cycle. No persistent process, no shared
   conversation state beyond what's persisted in sqlite
   (`agent_memory`, `agent_journal`).
3. **Paper by default.** `agent.paper_mode = true` forces
   `broker.type = log` in the effective config, so live trading only
   kicks in when the user flips the Paper/Live toggle *and*
   configures a real broker.
4. **Scrapers never raise.** `ScraperBase.safe_fetch` wraps every
   source in a try/except; a broken endpoint returns `[]`, increments
   the health counter, and never kills the runner.
5. **Cadence floor.** 30 s minimum between iterations. The earlier
   per-iteration caps (40 tool calls, 360 s) were removed so the
   supervisor is not cut off mid-thought. Kill switch in the Agent
   menu exits within 3 s.

## Directory layout

```
core/
├── agent/
│   ├── pool.py                — AgentPool: supervisor + chat workers + swarm
│   ├── runner.py              — AgentRunner QThread (supervisor loop)
│   ├── chat_worker.py         — one-shot QThread per user chat message
│   ├── swarm.py               — SwarmCoordinator daemon (20-role research pool)
│   ├── research_worker.py     — one QThread per research task
│   ├── research_roles.py      — 20 role definitions (quick / deep tiers)
│   ├── assessor.py            — post-iteration Sonnet grader
│   ├── model_router.py        — model + effort selection per role
│   ├── mcp_server.py          — create_sdk_mcp_server wiring
│   ├── prompts.py             — autonomous PM system prompt
│   ├── prompts_research.py    — research worker system prompts
│   ├── context.py             — per-iteration AgentContext
│   └── tools/
│       ├── broker_tools.py
│       ├── market_tools.py
│       ├── market_hours_tools.py
│       ├── risk_tools.py
│       ├── memory_tools.py
│       ├── watchlist_tools.py
│       ├── news_tools.py
│       ├── social_tools.py
│       ├── flow_tools.py
│       ├── backtest_tools.py
│       ├── browser_tools.py
│       ├── ensemble_tools.py
│       ├── sentiment_tools.py
│       ├── insider_tools.py
│       ├── alt_data_tools.py
│       ├── execution_tools.py
│       └── rl_tools.py
├── scrapers/
│   ├── base.py                — ScraperBase + ScrapedItem
│   ├── runner.py              — background daemon, VADER-scores every item
│   ├── youtube_transcripts.py — Haiku-summarised captions
│   ├── youtube_live_vision.py — sampled-frame vision via yt-dlp + ffmpeg
│   ├── sec_insider.py         — SEC Form 4 Atom feed
│   ├── options_flow.py        — unusual options activity heuristic
│   ├── _transcript_summariser.py — Haiku CLI + regex fallback
│   ├── _sentiment.py          — VADER scorer
│   ├── _vision_summariser.py  — Haiku vision summariser
│   ├── google_news.py
│   ├── yahoo_finance.py
│   ├── bbc.py
│   ├── bloomberg.py
│   ├── marketwatch.py
│   ├── youtube.py
│   ├── stocktwits.py
│   ├── reddit.py
│   └── x_via_gnews.py
├── forecasting/               — Chronos-2, TimesFM, TFT + XGBoost meta-learner
├── nlp/                       — FinBERT compound sentiment scorer
├── alt_data/                  — analyst revision momentum
├── execution/                 — TWAP / VWAP slice planner
├── rl/                        — FinRL scaffold (regime-aware cold-start allocator)
├── broker_service.py          — broker facade (T212 / LogBroker)
├── paper_broker.py            — ephemeral £100 GBP sandbox
├── trading212.py              — Trading 212 REST client
├── risk_manager.py            — Kelly + ATR sizing (regime-aware)
├── data_loader.py             — yfinance daily OHLCV cache
├── database.py                — sqlite persistence (agent_memory, agent_journal,
│                                scraper_items, research_findings)
├── config_schema.py           — Pydantic AppConfig validator
└── market_hours.py            — 13-exchange registry + status helper

desktop/
├── app.py                     — MainWindow, panel wiring, agent lifecycle
├── state.py                   — DEFAULT_CONFIG + init_state
├── main.py                    — shared bootstrap (license, wizard, launch)
├── main_desktop.py            — desktop edition entry point
├── panels/
│   ├── agent_log.py           — live log + start/stop/kill
│   ├── chart.py
│   ├── chat.py
│   ├── news.py
│   ├── orders.py
│   ├── positions.py
│   ├── exchanges.py           — 13-venue market-hours status panel
│   ├── settings.py            — account + agent status readout
│   └── watchlist.py
└── dialogs/                   — setup wizard, license, trade, add_ticker, etc.
```

## Key files (by owner)

- **Boss-owned hubs:** `desktop/app.py`, `desktop/main.py`,
  `core/agent/runner.py`, `config.json`, `requirements.txt`
- **Tool bus (one module per concern):** `core/agent/tools/*.py`
- **Scrapers (one file per source):** `core/scrapers/*.py`
- **Forecasters (one file per model):** `core/forecasting/*.py` +
  `core/kronos_forecaster.py`. See [docs/systems/forecasting.md](systems/forecasting.md).
- **NLP:** `core/nlp/finbert.py`. See [docs/systems/nlp.md](systems/nlp.md).
- **Alt-data:** `core/alt_data/` (analyst revisions), `core/scrapers/sec_insider.py`,
  `core/scrapers/options_flow.py`.
- **Execution:** `core/execution/vwap.py` (TWAP/VWAP planner).
- **RL / fine-tune seams:** `core/rl/finrl_scaffold.py`,
  `core/finetune/terminal_finetune.py`.
- **Panels (one file per panel):** `desktop/panels/*.py`

## Config surface

```json
{
  "agent": {
    "enabled": false,
    "cadence_seconds": 45,
    "paper_mode": true,
    "daily_max_drawdown_pct": 3.0,
    "max_position_pct": 20.0,
    "max_trades_per_hour": 10,
    "max_chat_workers": 5
  },
  "ai": {
    "model_complex": "claude-opus-4-7",
    "model_medium": "claude-sonnet-4-6",
    "model_simple": "claude-haiku-4-5-20251001",
    "model_assessor": "claude-sonnet-4-6",
    "effort_supervisor": "max",
    "effort_decision": "high",
    "effort_info": "medium",
    "effort_research_deep": "high",
    "effort_research_quick": "medium",
    "effort_assessor": "medium"
  },
  "news": {
    "refresh_interval_minutes": 5,
    "scrapers_enabled": true
  },
  "broker": {
    "type": "log",
    "api_key_env": "T212_API_KEY",
    "secret_key_env": "T212_SECRET_KEY",
    "practice": true
  }
}
```

## Model routing + effort

The agent runs on the Claude Agent SDK with per-role model + effort
tiers. A separate post-iteration assessor (`core/agent/assessor.py`)
runs on the Sonnet tier after each supervisor iteration and writes its
`good/mediocre/bad` review into `agent_journal`.

| Role                        | Model                        | Effort   |
|-----------------------------|------------------------------|----------|
| Supervisor (runner loop)    | `claude-opus-4-7`            | `max`    |
| Chat — decision tier        | `claude-opus-4-7`            | `high`   |
| Chat — info tier            | `claude-sonnet-4-6`          | `medium` |
| Research — deep tier        | `claude-sonnet-4-6`          | `high`   |
| Research — quick tier       | `claude-haiku-4-5-20251001`  | `low`    |
| Post-iteration assessor     | `claude-sonnet-4-6`          | `medium` |
| Sentiment / summariser      | `claude-haiku-4-5-20251001`  | —        |

All slots are editable in `config.json` under the `ai` block
(`model_complex` / `model_medium` / `model_simple` / `model_assessor`
and the `effort_*` keys). The accessors live in
`core/agent/model_router.py`; `effort` is plumbed straight into
`ClaudeAgentOptions.effort` (SDK ≥ 0.1.59).

## Research swarm

Twenty-one specialised roles defined in
`core/agent/research_roles.py`, rotated through a bounded worker pool
by `core/agent/swarm.py`. Ten quick roles (Haiku, 2–3 min cadence)
scan breaking news and social buzz; ten deep roles (Sonnet, 10–15 min
cadence) do sector analysis, macro/geopolitical research, contrarian
hunting and technical pattern work; the new `market_scanner` role
(Sonnet) runs with `default_tickers=False` so it explicitly hunts
catalysts *outside* the current watchlist. All findings land in
`research_findings`; the Information panel surfaces the latest 20 in
the AGENT RESEARCH section.

## News pipeline

```
scraper.fetch()  →  score_item()  →  db.save_scraper_items()
                    (VADER, ±0.1)      (sentiment cols stored)
                                             │
                                             ▼
                       core/agent/tools/news_tools.get_news  (agent)
                                             │
                                             ▼
                       desktop/panels/news.py  WATCHLIST SENTIMENT
                                               AGENT RESEARCH
                                               MARKET NEWS  [+0.42]
```

Every `scraper_items` row carries `sentiment_score` (compound float
in `[-1,+1]`) and `sentiment_label` (`bullish`/`bearish`/`neutral`).
The Information panel reads these on refresh; the agent sees them
through `get_news`.

## What the agent cannot do (deliberately)

- Scrape Instagram or Facebook (both gate aggressively; rotations break).
- Tick-level data (requires paid feed).
- Arbitrary CLI execution (`allowed_tools` is hard-capped to the
  `mcp__blank__*` namespace; no Bash, no Read, no Write).
- Cancel its own kill switch (the Qt thread flag is set on the GUI
  thread, never inside the subprocess).
