# Research Swarm — Design Spec

**Date:** 2026-04-16  
**Status:** Approved  
**Scope:** 20-agent research swarm with Playwright browser automation and Grok/X integration

---

## Overview

A continuously-running research swarm of 20 specialised agent roles that independently research stocks, mine social media intelligence via Grok AI on X/Twitter, and feed structured findings back to the existing supervisor agent (AgentRunner) for trading decisions.

The swarm runs 24/7 alongside the existing ScraperRunner. Agents go off on tangents, follow leads, and bring recommendations back. The supervisor reads aggregated intelligence before each trading iteration.

---

## Architecture

### Two-Tier Agent Roles

**Tier 1 — Quick-Reaction Squad (10 roles)**

Fast-cycling roles (2-5 min per task) using Haiku for throughput. React to breaking developments.

| # | Role ID | Focus |
|---|---------|-------|
| 1 | `tech_watcher` | Tech sector breaking news + price spikes |
| 2 | `healthcare_watcher` | Healthcare/biotech FDA decisions, trial results |
| 3 | `energy_watcher` | Energy sector, oil, renewables, geopolitics |
| 4 | `finance_watcher` | Banks, rates, Fed signals |
| 5 | `consumer_watcher` | Consumer/retail earnings, sentiment shifts |
| 6 | `reddit_scanner` | WSB, r/stocks, r/investing hot threads |
| 7 | `stocktwits_scanner` | StockTwits trending tickers + sentiment |
| 8 | `grok_miner` | X/Twitter intelligence via Grok AI |
| 9 | `news_scanner` | Google News + BBC + MarketWatch breaking |
| 10 | `earnings_watcher` | Earnings calendar, pre/post-market movers |

**Tier 2 — Deep Research Squad (10 roles)**

Long-cycling roles (15-60 min per task) using Sonnet for analytical depth.

| # | Role ID | Focus |
|---|---------|-------|
| 11 | `sector_analyst_tech` | Deep tech sector analysis, competitive dynamics |
| 12 | `sector_analyst_health` | Biotech pipelines, regulatory landscape |
| 13 | `sector_analyst_industrial` | Industrials, commodities, supply chain |
| 14 | `macro_researcher` | Interest rates, inflation, GDP, central bank policy |
| 15 | `geopolitical_researcher` | Trade wars, sanctions, political risk |
| 16 | `sentiment_aggregator_social` | Cross-platform sentiment synthesis (Reddit + StockTwits + X) |
| 17 | `sentiment_aggregator_news` | News sentiment trends across multiple sources |
| 18 | `contrarian_hunter` | Find where crowd consensus is wrong, short squeeze candidates |
| 19 | `catalyst_scanner` | Upcoming catalysts: earnings dates, FDA dates, splits, buybacks |
| 20 | `technical_researcher` | Chart patterns, support/resistance, volume analysis |

### Worker Pool (Not 20 Concurrent Sessions)

20 logical roles rotate through a bounded worker pool:

- **Max concurrent workers**: configurable, default 4 (max 8)
- **Priority scheduling**: quick-reaction roles get 2x weight
- **Rotation**: all roles cycle continuously; quick roles fire ~every 10 min, deep roles ~every 30 min
- **Cost control**: Haiku for tier 1, Sonnet for tier 2, Opus reserved for supervisor only

### Component Hierarchy

```
MainWindow
  ├── AgentPool (existing)
  │   ├── AgentRunner (supervisor, Opus) ← reads research_findings
  │   └── ChatWorker[] (user chat)
  │
  ├── SwarmCoordinator (NEW)
  │   ├── ResearchWorker[0..max_workers] (QThread pool)
  │   ├── ResearchQueue (priority task scheduler)
  │   └── RoleRegistry (20 role definitions + prompts)
  │
  └── ScraperRunner (existing, unchanged)
```

---

## Grok Integration via Playwright

### How It Works

Research agents get a `query_grok` tool that uses headless Chromium to interact with Grok AI on X (grok.x.ai). Grok has native access to X/Twitter data, making it the best proxy for mining social media intelligence without needing X API access.

### Tool: `query_grok`

```
Input:
  query: str       — natural language question for Grok
  context: str     — optional context about what we're researching
  timeout: int     — max seconds to wait (default 60)

Output:
  response: str    — Grok's full text response
  source: "grok_x"
  query_used: str
  timestamp: str
```

### Browser Flow

1. Launch headless Chromium via Playwright
2. Navigate to `grok.x.ai`
3. Handle auth if needed (session cookies persisted in `data/grok_session/`)
4. Type research query into Grok's input
5. Wait for streaming response to complete (detect "stop generating" button disappearing)
6. Extract response text from DOM
7. Close browser context (reuse browser instance across calls within same worker)
8. Return extracted text as tool result

### Example Queries

- `grok_miner` role: "What are people on X saying about $NVDA right now? Any unusual buzz or rumours?"
- `contrarian_hunter` role: "Find X posts where retail traders are extremely bearish on $TSLA — is this a contrarian buy signal?"
- `sentiment_aggregator_social` role: "Summarise the overall mood on X about the tech sector today. Bull/bear ratio?"
- `catalyst_scanner` role: "Any X posts about upcoming FDA decisions or earnings surprises this week?"

### Session Management

- One Playwright browser instance per worker (not per query)
- Session cookies stored in `data/grok_session/` for persistence across restarts
- If Grok is rate-limited or down, tool returns graceful error (agent continues with other tools)
- Cookie refresh: if auth fails, emit a `grok_auth_needed` signal to the UI so user can re-login

---

## Supervisor Integration

The existing AgentRunner (Opus) becomes the swarm supervisor without changing its core loop:

### What Changes

1. **Before each iteration**: supervisor's system prompt includes a `## Swarm Intelligence Brief` section with:
   - Top 10 highest-confidence findings from last N hours
   - Any urgent alerts from quick-reaction agents
   - Active research goals and their progress

2. **New supervisor tools**:
   - `get_swarm_findings(since_minutes, min_confidence, limit)` — read aggregated findings
   - `set_research_goal(goal, priority, deadline_minutes)` — direct swarm focus
   - `get_swarm_status()` — which roles are active, last fire times, health

3. **Trading decisions informed by swarm**: supervisor sees structured findings with confidence scores, not raw news text. It can filter by role, ticker, finding type.

### What Stays The Same

- Supervisor still uses Opus, still has all broker/trading tools
- Same iteration loop, same end_iteration pattern
- Same agent_journal logging
- Chat workers unchanged

---

## Database Schema

### `research_tasks`

```sql
CREATE TABLE research_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    role        TEXT NOT NULL,           -- "grok_miner", "tech_watcher", etc.
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/running/completed/failed
    ticker      TEXT,                    -- nullable (some tasks are broad market)
    parameters  TEXT,                    -- JSON: custom params per role
    goal_id     INTEGER,                -- FK to research_goals (nullable)
    priority    INTEGER NOT NULL DEFAULT 5,  -- 1=highest, 10=lowest
    assigned_worker TEXT,               -- worker thread ID
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    completed_at TEXT,
    error       TEXT
);
CREATE INDEX idx_rt_status ON research_tasks(status);
CREATE INDEX idx_rt_role ON research_tasks(role);
CREATE INDEX idx_rt_priority ON research_tasks(priority);
```

### `research_findings`

```sql
CREATE TABLE research_findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         INTEGER,            -- FK to research_tasks
    role            TEXT NOT NULL,       -- which role produced this
    ticker          TEXT,               -- nullable for broad-market findings
    finding_type    TEXT NOT NULL,       -- "alert", "sentiment", "catalyst", "thesis", "pattern"
    headline        TEXT NOT NULL,       -- one-line summary
    detail          TEXT,               -- full analysis text
    confidence_pct  INTEGER NOT NULL,   -- 0-100
    source          TEXT,               -- "grok_x", "reddit", "google_news", etc.
    methodology     TEXT,               -- how the agent reached this conclusion
    evidence_json   TEXT,               -- supporting data points
    acted_on        INTEGER DEFAULT 0,  -- 1 if supervisor used this in a trade decision
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_rf_ticker ON research_findings(ticker);
CREATE INDEX idx_rf_confidence ON research_findings(confidence_pct);
CREATE INDEX idx_rf_created ON research_findings(created_at);
CREATE INDEX idx_rf_type ON research_findings(finding_type);
```

### `research_goals`

```sql
CREATE TABLE research_goals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal            TEXT NOT NULL,       -- "Analyse biotech sector before market open"
    status          TEXT NOT NULL DEFAULT 'active',  -- active/completed/cancelled
    priority        INTEGER NOT NULL DEFAULT 5,
    created_by      TEXT,               -- "supervisor" or "user"
    target_roles    TEXT,               -- JSON list of roles to activate
    deadline_at     TEXT,               -- optional deadline
    findings_count  INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT
);
```

---

## New Files

| File | Purpose |
|------|---------|
| `core/agent/swarm.py` | SwarmCoordinator class — lifecycle, worker pool, scheduling |
| `core/agent/research_worker.py` | ResearchWorker (QThread) — executes one research task |
| `core/agent/research_queue.py` | Priority queue, role definitions, task generation |
| `core/agent/research_roles.py` | 20 role configs: name, tier, model, cadence, prompt template |
| `core/agent/prompts_research.py` | System prompts per role specialisation |
| `core/agent/tools/research_tools.py` | submit_finding, get_findings, set_research_goal, get_swarm_status |
| `core/agent/tools/grok_tools.py` | query_grok, query_grok_trending (Playwright-based) |

### Modified Files

| File | Change |
|------|--------|
| `core/agent/mcp_server.py` | Register new research + grok tools in ALL_TOOLS |
| `core/agent/pool.py` | Wire SwarmCoordinator alongside supervisor |
| `core/agent/prompts.py` | Add swarm intelligence brief to supervisor prompt |
| `core/agent/context.py` | Add swarm-related fields to AgentContext |
| `core/database.py` | Add research_tasks, research_findings, research_goals tables + queries |
| `desktop/app.py` | Start SwarmCoordinator on launch, wire status signals |
| `config.json` | Add `swarm` config section |
| `installer/blank.spec` | Add new modules to hiddenimports |
| `requirements.txt` | Add `playwright` dependency |

---

## Config

```json
"swarm": {
    "enabled": true,
    "max_concurrent_workers": 4,
    "quick_reaction_cadence_seconds": 120,
    "deep_research_cadence_seconds": 600,
    "grok_enabled": true,
    "grok_session_path": "data/grok_session",
    "max_findings_per_hour": 200,
    "finding_retention_days": 30,
    "roles_enabled": [
        "tech_watcher", "healthcare_watcher", "energy_watcher",
        "finance_watcher", "consumer_watcher", "reddit_scanner",
        "stocktwits_scanner", "grok_miner", "news_scanner",
        "earnings_watcher", "sector_analyst_tech", "sector_analyst_health",
        "sector_analyst_industrial", "macro_researcher",
        "geopolitical_researcher", "sentiment_aggregator_social",
        "sentiment_aggregator_news", "contrarian_hunter",
        "catalyst_scanner", "technical_researcher"
    ]
}
```

---

## 24/7 Operation

### Startup

```
desktop/app.py __init__():
  ...existing services...
  self._start_scraper_runner()      # existing
  self._start_swarm_coordinator()   # NEW
```

### Continuous Loop

```
SwarmCoordinator.run():
  while not stop_requested:
    1. Check which roles are due to fire (based on cadence + last_fire_time)
    2. Generate tasks for due roles
    3. Assign tasks to idle workers (priority order)
    4. Collect completed findings
    5. Purge old findings (>retention_days)
    6. Sleep 5 seconds, repeat
```

### Graceful Shutdown

- SwarmCoordinator.stop() sets stop flag
- Waits for running workers to finish current task (max 60s)
- Workers call end_iteration on their current context
- All pending tasks reset to "pending" status

---

## Cost Projection

| Component | Model | Calls/hour | Estimated cost/hour |
|-----------|-------|-----------|-------------------|
| 10 quick-reaction roles | Haiku | ~60 | Low (Haiku is cheap) |
| 10 deep-research roles | Sonnet | ~20 | Moderate |
| 1 supervisor | Opus | ~6 | Moderate |
| Grok queries | Free (browser) | ~6 | $0 |

The worker pool cap (default 4) is the main cost lever. Users can reduce to 2 workers for lower spend or increase to 8 for more coverage.
