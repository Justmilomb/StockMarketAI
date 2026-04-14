# blank — autonomous AI trading terminal

**blank** by Certified Random is a desktop trading terminal where Claude is
the decision-maker. The old hand-rolled ML pipeline (ensembles, regime
detection, consensus committee, auto engine) has been deleted. Python is
now a typed **tool bus** — a small set of MCP-registered functions Claude
calls whenever it wants: fetch prices, read news, size positions, place
orders.

Bloomberg-dark panels, paper-mode by default, live broker support via
Trading 212, and a 24/7 scraper daemon pulling from 9 news and social
sources.

## How it works

```
Qt MainWindow ──▶ AgentRunner (QThread)
                     │
                     ▼ one fresh Claude Code subprocess per iteration
                claude-agent-sdk.query(prompt, options)
                     │
                     ▼ in-process MCP tools
                core/agent/tools/*.py
                     │
                     ▼
                broker / market / risk / news / social / memory
```

Every iteration:

1. Runner spawns a fresh Claude Code subprocess via `claude-agent-sdk`.
2. System prompt tells Claude it is an autonomous PM with strict risk
   rules and kill conditions.
3. Claude calls MCP tools (`mcp__blank__get_portfolio`,
   `mcp__blank__place_order`, `mcp__blank__get_news`, …) — no Bash,
   no Read, no Write. The allowed-tools list is hard-capped.
4. Tool calls stream back to the UI as Qt signals — chart, positions,
   orders, agent log all update live.
5. Runner sleeps for the configured cadence (default 90s, floor 30s)
   and loops.

Hard caps per iteration: **40 tool calls, 360 s wall clock**. Kill switch
on the Agent menu sets a soft-stop flag and waits 3 seconds before
terminating the thread.

## Quick start

### Windows installer

1. Download `BlankSetup.exe` from the latest release.
2. Run the installer.
3. Enter your license key on first launch.
4. Follow the setup wizard — it walks you through Claude Code CLI and
   Trading 212 configuration.

### Build from source

```
setup.bat                              # Create venv + install deps
build.bat                              # Build blank.exe + installer
```

Output: `dist/BlankSetup.exe`.

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
│   ├── runner.py           AgentRunner QThread
│   ├── mcp_server.py       create_sdk_mcp_server wiring
│   ├── prompts.py          autonomous PM system prompt
│   ├── context.py          per-iteration context
│   └── tools/              broker, market, risk, memory, watchlist,
│                           news, social, flow — one file per concern
├── scrapers/               24/7 background news + social feeds
│   ├── base.py             ScraperBase (rate-limit, UA rotation, safe-fail)
│   ├── runner.py           daemon thread, cycles every 5 min
│   └── <9 source files>    google_news, yahoo_finance, bbc, bloomberg,
│                           marketwatch, youtube, stocktwits, reddit, x
├── broker_service.py       broker facade (Trading 212 / LogBroker)
├── trading212.py           Trading 212 REST client
├── risk_manager.py         Kelly + ATR sizing (size_position tool)
├── data_loader.py          yfinance daily OHLCV cache
├── database.py             sqlite persistence (agent_memory, agent_journal,
│                           scraper_items)
└── news_agent.py           legacy panel sentiment helper

desktop/
├── app.py                  MainWindow, panel wiring, agent lifecycle
├── main.py                 shared bootstrap (license, wizard, launch)
├── main_bloomberg.py       Bloomberg edition entry point
├── state.py                DEFAULT_CONFIG + init_state
├── panels/
│   ├── agent_log.py        live log + start/stop/kill
│   ├── chat.py             user messages → running agent loop
│   ├── chart.py / orders.py / positions.py / news.py / watchlist.py
│   └── settings.py         account + agent status readout
└── dialogs/                setup wizard, license, etc.
```

See `docs/ARCHITECTURE.md` for the full system diagram and
`docs/CONTRACTS.md` for interface contracts between subsystems.

## Configuration

All runtime config lives in `config.json`. The agent-relevant sections:

```json
{
  "agent": {
    "enabled": false,
    "cadence_seconds": 90,
    "max_tool_calls_per_iter": 40,
    "max_iter_seconds": 360,
    "paper_mode": true,
    "daily_max_drawdown_pct": 3.0,
    "max_position_pct": 20.0,
    "max_trades_per_hour": 10
  },
  "news": {
    "refresh_interval_minutes": 5,
    "scraper_cadence_seconds": 300
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
- **Hard caps.** 40 tool calls and 360 s per iteration; kill switch
  stops the loop within 3 s.
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
