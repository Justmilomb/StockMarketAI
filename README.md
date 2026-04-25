# blank — autonomous AI trading terminal

**blank** by Certified Random is a desktop trading terminal where Claude is
the decision-maker. The old hand-rolled ML pipeline (ensembles, regime
detection, consensus committee, auto engine) has been deleted. Python is
now a typed **tool bus** — a small set of MCP-registered functions Claude
calls whenever it wants: fetch prices, read news, size positions, place
orders.

Terminal-dark panels, paper-mode by default, live broker support via
Trading 212, and a 24/7 scraper daemon pulling from 12 news and social
sources. A 21-role research swarm runs in parallel, continuously filing
findings for the supervisor to act on.

## How it works

```
Qt MainWindow ──▶ AgentPool
                     │
                     ├─ AgentRunner (supervisor QThread)
                     │    └─ one fresh Claude subprocess per iteration
                     │         claude-agent-sdk.query(prompt, options)
                     │                │
                     │                ▼ in-process MCP tools
                     │         core/agent/tools/*.py
                     │                │
                     │                ▼
                     │         broker / market / risk / news / social / memory
                     │
                     ├─ ChatWorker QThreads (one per user message)
                     │    └─ same tool bus, same broker, same SQLite memory
                     │
                     └─ SwarmCoordinator (daemon thread)
                          └─ ResearchWorker QThreads rotating through
                             21 specialised roles (quick / deep research)
```

Every supervisor iteration:

1. AgentPool spawns a fresh Claude subprocess via `claude-agent-sdk`.
2. System prompt tells Claude it is an autonomous PM with strict risk
   rules and kill conditions.
3. Claude calls MCP tools (`mcp__blank__get_portfolio`,
   `mcp__blank__place_order`, `mcp__blank__get_news`, …) — no Bash,
   no Read, no Write. The allowed-tools list is hard-capped.
4. Tool calls stream back to the UI as Qt signals — chart, positions,
   orders, agent log all update live.
5. A post-iteration assessor (Sonnet tier) grades the iteration and
   writes its review to `agent_journal`.
6. Runner sleeps for the configured cadence (default 45 s, floor 30 s)
   and loops.

Kill switch on the Agent menu sets a soft-stop flag and waits 3 seconds
before terminating the thread. The earlier per-iteration hard caps (40
tool calls, 360 s) were removed so the supervisor is not cut off
mid-thought; the cadence floor is the only enforced governor.

## Quick start

### Windows installer

1. Download `blank-setup.exe` from the latest release.
2. Run the installer.
3. Enter your license key on first launch.
4. Follow the setup wizard — it walks you through Claude Code CLI and
   Trading 212 configuration.

### Build from source — Windows

```
setup.bat                              # Create venv + install deps
build.bat                              # Build blank.exe + installer
```

Output: `dist/blank-setup.exe`.

### Build from source — macOS

```
python3 -m venv .venv-mac
source .venv-mac/bin/activate
pip install -r requirements-mac.txt
chmod +x build-mac.sh
./build-mac.sh
```

Output: `dist/blank.app` (and `dist/blank-setup.dmg` if `create-dmg` is
installed via `brew install create-dmg`).

Set `BLANK_CODESIGN_ID="Developer ID Application: Your Name (TEAMID)"`
before running to codesign the bundle. Without a signature the app
launches via right-click → Open the first time but is rejected by
Gatekeeper for download distribution.

Drop a `desktop/assets/icon.icns` next to the existing `icon.ico` for a
proper Dock icon — the spec falls back to the .ico when missing so a
fresh checkout still builds.

### Cutting a release

```
python scripts/release.py
```

Pick the **remote** path (default) and the GitHub Actions workflow at
`.github/workflows/release.yml` builds the Windows installer on a
hosted runner, attaches it to the GitHub Release, and POSTs the new
version into `/api/admin/releases` so every running desktop client
sees the update on its next heartbeat. Pick the **local** path to
build on this machine instead — same end result, more steps.

### Dev harness

```
python scripts/agent_repl.py           # spawn one agent iteration
```

Runs a single iteration against `LogBroker` (paper) with full tool
transcript streamed to stdout. Useful for smoke-testing tool wiring.

## Project layout

```
core/
├── agent/                  Claude Agent SDK runner + tool bus
│   ├── runner.py           AgentRunner QThread (supervisor loop)
│   ├── pool.py             AgentPool — owns supervisor + chat workers + swarm
│   ├── chat_worker.py      one-shot QThread per user chat message
│   ├── swarm.py            SwarmCoordinator daemon (20-role research pool)
│   ├── research_worker.py  one QThread per research task
│   ├── research_roles.py   20 role definitions (quick / deep tiers)
│   ├── assessor.py         post-iteration Sonnet grader
│   ├── model_router.py     model + effort selection per role
│   ├── mcp_server.py       create_sdk_mcp_server wiring
│   ├── prompts.py          autonomous PM system prompt
│   ├── context.py          per-iteration context
│   └── tools/              broker, market, risk, memory, watchlist,
│                           news, social, flow, backtest, browser,
│                           ensemble, sentiment, insider, alt_data,
│                           execution, rl — one file per concern
├── scrapers/               24/7 background news + social feeds
│   ├── base.py             ScraperBase (rate-limit, UA rotation, safe-fail)
│   ├── runner.py           daemon thread, cycles every 5 min, VADER scoring
│   ├── youtube_transcripts.py   @markets channel + live-stream captions
│   ├── youtube_live_vision.py   sampled-frame vision feed via yt-dlp + ffmpeg
│   ├── sec_insider.py      SEC Form 4 insider-trade feed
│   ├── options_flow.py     unusual options activity heuristic
│   └── <9 headline scrapers>    google_news, yahoo_finance, bbc, bloomberg,
│                                marketwatch, youtube, stocktwits, reddit, x
├── forecasting/            Chronos-2, TimesFM, TFT + XGBoost meta-learner
├── nlp/                    FinBERT compound sentiment scorer
├── alt_data/               analyst revision momentum
├── execution/              TWAP / VWAP slice planner
├── rl/                     FinRL scaffold (regime-aware cold-start allocator)
├── broker_service.py       broker facade (Trading 212 / LogBroker)
├── paper_broker.py         ephemeral £100 GBP sandbox
├── trading212.py           Trading 212 REST client
├── risk_manager.py         Kelly + ATR sizing (regime-aware)
├── data_loader.py          yfinance daily OHLCV cache
├── database.py             sqlite persistence (agent_memory, agent_journal,
│                           scraper_items, research_findings)
└── config_schema.py        Pydantic AppConfig validator

desktop/
├── app.py                  MainWindow, panel wiring, agent lifecycle
├── main.py                 shared bootstrap (license, wizard, launch)
├── main_desktop.py         desktop edition entry point
├── state.py                DEFAULT_CONFIG + init_state
├── panels/
│   ├── agent_log.py        live log + start/stop/kill
│   ├── chat.py             user messages → agent pool
│   ├── exchanges.py        13-venue market-hours status panel
│   ├── chart.py / orders.py / positions.py / news.py / watchlist.py
│   └── settings.py         account + agent status readout
└── dialogs/                setup wizard, license, trade, add ticker, etc.
```

See `docs/ARCHITECTURE.md` for the full system diagram and
`docs/CONTRACTS.md` for interface contracts between subsystems.

## Configuration

All runtime config lives in `config.json`. The agent-relevant sections:

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
    "effort_supervisor": "max",
    "effort_decision": "high",
    "effort_info": "medium"
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

`agent.paper_mode = true` always forces `broker.type = "log"` at
runtime, so live trading only kicks in when you explicitly flip the
Paper/Live toggle **and** configure a real broker.

Model and effort tiers are all editable under the `ai` block. The
supervisor always runs at `max` effort; chat workers switch between
`high` (decision) and `medium` (info) based on the message content.

Broker secrets live in `.env` (see `.env.example`).

## Requirements

- Python 3.12+
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Trading 212 account (optional, only needed for live trading)
- Windows 10+ for the packaged desktop app

## Safety notes

- **Paper by default.** You have to opt into live trading per-session
  from the Agent menu.
- **Every read is a tool call.** `place_order` re-fetches the broker
  portfolio before submitting, so the "sell 0 owned" class of bug is
  impossible by construction.
- **Cadence floor.** The agent cannot run more than once every 30 s,
  regardless of config, to protect the AI subscription quota. Kill
  switch stops the loop within 3 s.
- **Scrapers never raise.** A broken source returns `[]` and increments
  a health counter — the runner keeps going.

## What the agent cannot do

- Execute arbitrary shell commands. Allowed tools are hard-capped to
  the `mcp__blank__*` namespace — no Bash, Read, Write.
- Cancel its own kill switch. The stop flag lives on the Qt thread,
  never inside the subprocess.
- Tick-level data. `yfinance` gives ~15-20 min delayed daily data and
  1m bars for the last 7 days; real tick feeds need a paid source.
- Scrape Instagram or Facebook — both gate too aggressively to stay
  stable.

## License

See `LICENSE`.
