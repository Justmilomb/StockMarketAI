# StockMarketAI — AI Agent Entry Point

AI-driven stock trading terminal combining scikit-learn ML predictions with Claude LLM analysis, rendered in a Bloomberg-style Textual TUI. Supports paper and live trading via Trading 212.

**Tech stack:** Python 3.12+, scikit-learn, Textual, Claude CLI, yfinance, pandas, numpy, PySide6
**Platform:** Windows 10
**Language(s):** English British

---

## 2 — Rules (non-negotiable)

- Type hints on every function signature. No `Any` except at serialisation boundaries.
- No global mutable state. Config via dataclass or `config.json`, never module-level dicts.
- Tests use pytest. No unittest.TestCase subclasses.
- **File size guideline:** Leaf modules should stay under ~400 lines. Hub files (`app.py`, `ai_service.py`) and files that are the single logical owner of a complex concern may exceed this when splitting would hurt readability or create artificial seams. Use judgement — the goal is cohesion, not a line count.
- One class/module per file pair (hub files excepted — they wire multiple concerns by design).
- Comments explain *why*, not *what*.
- No TODO comments in code — track in `docs/CURRENT_TASKS.md`.
- **Don't ask permission.** Just execute. User trusts technical decisions.
- **No git operations.** User commits manually.
- No hardcoded API keys. All secrets via environment variables.
- Broker operations default to paper/log mode unless explicitly configured.

---

## 3 — Reading Order (cold start)

1. Read `E:\Coding\Second Brain\StockMarketAI\CONTEXT.md` — your project brain
2. Read `E:\Coding\Second Brain\_index\MASTER_INDEX.md` — cross-project awareness
3. Read `E:\Coding\Second Brain\_index\SKILL_TRANSFERS.md` — applicable lessons
4. `docs/ARCHITECTURE.md` — system graph + data flow
5. `docs/CURRENT_TASKS.md` — what's done, what's next
6. `docs/CONTRACTS.md` — interface contracts (do not break these)
7. `docs/systems/<relevant>.md` — deep-dive on the system you'll touch
8. The source file for the module you'll modify

---

## 4 — Architecture Quick Reference

```
ai.py / terminal/app.py / backtest.py / desktop/main.py / autoconfig/run.py  (entry points)
  │
  ├─ AiService              (ML ensemble + statistical + Claude orchestration)
  │   ├─ data_loader         (yfinance OHLCV + CSV cache)
  │   ├─ features            (10 basic features — legacy)
  │   ├─ features_advanced   (31 V2 features, 6 analyst groups)
  │   ├─ model               (legacy RandomForest train/predict)
  │   ├─ ensemble            (6 diverse ML models — quant desk)
  │   ├─ timeframe           (1d/5d/20d multi-horizon ensembles)
  │   ├─ regime              (market regime detector — macro strategist)
  │   ├─ forecaster_statistical (ARIMA/ETS baselines — statsmodels)
  │   ├─ consensus           (investment committee — signal aggregation)
  │   ├─ claude_client       (Claude CLI: signals, news, chat)
  │   ├─ claude_personas     (3 Claude analyst personas)
  │   ├─ risk_manager        (portfolio risk desk — Kelly + ATR sizing)
  │   └─ strategy            (probability → buy/sell/hold)
  │
  ├─ BrokerService           (broker-agnostic facade)
  │   ├─ LogBroker           (dev: logs to JSONL)
  │   └─ Trading212Broker    (live: REST API v0, trading212.py)
  │
  ├─ AutoEngine              (signal → risk-managed order execution)
  │
  ├─ NewsAgent               (background RSS + batch Claude sentiment)
  │
  ├─ HistoryManager          (SQLite persistence — database.py)
  │   ├─ snapshots           (signals, positions, PnL per refresh)
  │   ├─ config_changes      (AI self-tuning audit trail)
  │   ├─ watchlist_log       (AI additions/removals)
  │   └─ chat_history        (persists across sessions)
  │
  ├─ PipelineTracker          (thread-safe progress tracking)
  │
  ├─ backtesting/             (walk-forward validation engine)
  │   ├─ types                (BacktestConfig, TradeRecord, PerformanceMetrics)
  │   ├─ data_prep            (feature pre-computation, walk-forward splits)
  │   ├─ simulator            (trade execution: stops, slippage, sizing)
  │   ├─ engine               (per-fold: train → predict → simulate)
  │   ├─ metrics              (Sharpe, Sortino, Calmar, drawdown, attribution)
  │   └─ runner               (parallel fold executor, all CPU cores)
  │
  ├─ terminal/
  │   ├─ app.py              (TradingTerminalApp — TUI + AI autonomous loops)
  │   ├─ state.py            (AppState + regime/consensus/ensemble metadata)
  │   ├─ views.py            (panels + Consensus/Confidence columns)
  │   ├─ pipeline_view.py    (dual-mode: progress bars + model dashboard)
  │   ├─ history_views.py    (history/pies/instruments modals)
  │   ├─ charts.py           (sparkline price charts)
  │   └─ terminal.css        (Bloomberg-dark theme, 3×4 grid)
  │
  ├─ desktop/                (PySide6 Bloomberg-dark desktop app)
  │   ├─ main.py             (entry point — QApplication bootstrap)
  │   ├─ app.py              (main window, panel wiring)
  │   ├─ state.py            (shared AppState for desktop)
  │   ├─ theme.py            (Bloomberg-dark Qt stylesheet)
  │   ├─ workers.py          (background QThread workers)
  │   ├─ panels/             (individual UI panels)
  │   └─ dialogs/            (modal dialogs)
  │
  └─ autoconfig/             (autonomous parameter optimisation)
      ├─ run.py              (entry point — experiment loop)
      ├─ experiment.py       (single experiment: backtest + score)
      ├─ universe.py         (ticker universe definitions)
      └─ strategy_profiles.py (candidate config profiles)
```

---

## 5 — Hub Files (BOSS ONLY — agents must not touch)

- `terminal/app.py` — main TUI wiring, lifecycle, action handlers
- `desktop/app.py` — main desktop window wiring, lifecycle, action handlers
- `ai_service.py` — orchestrates ML ensemble + statistical + Claude pipeline
- `config.json` — all runtime configuration
- `requirements.txt` — dependency manifest

---

## 6 — Multi-Agent Team

| Role | Model | Responsibilities | Owns |
|------|-------|-----------------|------|
| **Boss / Orchestrator** | opus | Plans, owns hub files, integrates, reviews | Hub files, architecture decisions |
| **Feature Agent** | sonnet | Implements one system at a time (2-6 files) | Leaf system files |
| **Support Agent** | haiku | Docs, review checklists, boilerplate, search | `docs/systems/*.md`, changelogs |

### Dispatch Protocol

**Phase 1 — Prepare (Boss, sequential):**
1. Update shared types/schemas with any new structures needed
2. Update `requirements.txt` if adding modules
3. Define public API signatures in hub files
4. Write dispatch prompts with ONLY the context each agent needs

**Phase 2 — Parallel Work (Feature agents, simultaneous):**
- Each agent receives ONLY its owned files + read-only deps
- Each agent creates/modifies ONLY files in its stream
- Use `isolation: "worktree"` for git-based conflict avoidance
- Return completed code for Boss review

**Phase 3 — Integrate (Boss, sequential):**
1. Review each agent's output
2. Wire new systems into hub files
3. Resolve any API mismatches
4. Final consistency check

**Phase 4 — Verify (parallel, Support agents):**
- Code reviewer: scan for type errors, missing imports, contract violations
- Doc writer: update system docs for everything that changed

### Dispatch Prompt Template (Feature Agent)

```
You are {agent-name}, working on the {system} system for StockMarketAI — an AI trading terminal.

FILES YOU OWN (create/modify these only):
{file list}

CONTEXT (read-only reference):
{paste relevant interface/type contents}

TASK:
{specific implementation task}

CONSTRAINTS:
- Do NOT modify any file outside your owned list
- Do NOT add imports for modules outside your context
- Type hints on every function. No `Any` except at serialisation boundaries.
- No global mutable state.
- Return the complete file contents when done
```

---

## 7 — Key Conventions

- Classes: PascalCase. Functions/variables: snake_case. Constants: UPPER_SNAKE.
- Private members: `_leading_underscore`. No dunder abuse.
- Imports: stdlib → third-party → local (isort compatible).
- Docstrings: Google style on public functions. None on obvious internals.
- Booleans: `is_`/`has_` prefix where clarity helps.
- Config access: always via `config.get("key", default)` — never assume keys exist.

---

## 8 — Current Phase

- **Phase 1:** Core ML pipeline (data → features → model → signals → broker) — **done**
- **Phase 2:** TUI terminal + Claude integration + news agent + Trading 212 — **done**
- **Phase 2.5:** Self-learning AI loops, SQLite persistence, chat history, T212 price fallback — **done**
- **Phase 2.75:** ML ensemble (6 models × 3 horizons, regime detection, Claude personas, consensus engine, risk management) — **done**
- **Phase 2.85:** ARIMA/ETS statistical baseline + pipeline visualization — **done**
- **Phase 3.0:** Backtesting engine (walk-forward validation, trade simulation, Sharpe/Sortino/Calmar metrics, parallel folds, CLI) — **done**
- **Phase 3.1:** Multi-asset expansion (stocks, crypto, polymarket) — **done**
- **Phase 3.15:** Autoconfig — autonomous parameter optimisation via Claude CLI, GCP VM deployment, 23+ experiments — **done**
- **Phase 3.2:** PySide6 desktop app (Bloomberg-dark GUI, build to exe) — **done**
- **Phase 3.3:** Testing, pytest coverage, integration tests — **in progress**
- **Phase 4:** Production hardening, monitoring, deployment automation — **planned**

---

## Before You Finish

### Minimum write-back (every session):
1. `E:\Coding\Second Brain\StockMarketAI\SESSION_LOG.md` — add entry if anything important happened
2. `E:\Coding\Second Brain\StockMarketAI\KNOWN_ISSUES.md` — add/remove bugs if any changed

### Full write-back (when project state materially changed):
3. `E:\Coding\Second Brain\StockMarketAI\CONTEXT.md` — update changed sections only
4. `E:\Coding\Second Brain\StockMarketAI\PATTERNS.md` — add if you learned something new
5. `E:\Coding\Second Brain\_index\MASTER_INDEX.md` — update if you added new knowledge files
6. `E:\Coding\Second Brain\_index\SKILL_TRANSFERS.md` — add if lesson applies elsewhere

### Notion database updates (use Notion MCP tools):

Database IDs are in `E:\Coding\Second Brain\_system\conventions\notion-config.md`.
Use `data_source_id` (not `database_id`) when creating pages via `notion-create-pages`.

7. **Projects database** — update status/health for StockMarketAI after significant work
8. **Tasks database** — update status of any tasks you worked on
9. **Bugs database** — add/update bugs found or fixed
10. **Agent Log** — add entry ONLY if important (decision, error, breakthrough, blocker)

If Notion MCP is unavailable, log pending updates to `E:\Coding\Second Brain\StockMarketAI\SESSION_LOG.md` with `[NOTION_PENDING]` tag.

### If session is interrupted:
Prioritise: SESSION_LOG > KNOWN_ISSUES > CONTEXT > everything else.
Notion updates are non-critical — Obsidian is the source of truth.
