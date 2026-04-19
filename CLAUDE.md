# StockMarketAI — AI Agent Entry Point

Desktop trading terminal where Claude is the decision-maker. Python is a typed tool bus of MCP-registered functions; the Claude Agent SDK drives an autonomous supervisor loop, a concurrent chat service, and a 21-role research swarm. Supports paper and live trading via Trading 212.

**Tech stack:** Python 3.12+, Claude Agent SDK, PySide6, yfinance, pandas, numpy, scikit-learn (forecasting meta-learner only)
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

The legacy ML pipeline (ensemble / features / consensus / regime /
forecaster / claude_personas / ai_service / backtesting / terminal TUI /
polymarket / crypto) has been retired — the Claude Agent loop now owns
every decision and the scraper runner owns every news signal.

```
desktop/main_desktop.py                (entry point)
  │
  ├─ core/                              (everything on sys.path)
  │   ├─ agent/                         (Claude Agent loop — the brain)
  │   │   ├─ pool                       (AgentPool — owns supervisor + chat workers + swarm)
  │   │   ├─ runner                     (AgentRunner QThread — supervisor iteration loop)
  │   │   ├─ chat_worker                (one QThread per user chat message)
  │   │   ├─ swarm                      (SwarmCoordinator daemon — 21-role research pool)
  │   │   ├─ research_worker            (one QThread per research task)
  │   │   ├─ research_roles             (20 role definitions — quick/deep tiers)
  │   │   ├─ assessor                   (post-iteration Sonnet grader)
  │   │   ├─ model_router               (model + effort selection per role)
  │   │   ├─ mcp_server                 (in-process MCP tool bus)
  │   │   ├─ prompts / prompts_research (system prompts)
  │   │   ├─ context                    (per-iteration AgentContext)
  │   │   └─ tools/                     (broker, market, news, risk, memory,
  │   │                                  watchlist, flow, backtest, browser,
  │   │                                  ensemble, sentiment, insider, alt_data,
  │   │                                  execution, rl, …)
  │   ├─ scrapers/                      (RSS + social + TV caption feed)
  │   │   ├─ runner                     (poll cycle + VADER sentiment scoring)
  │   │   ├─ youtube_transcripts        (@markets channel + live-stream captions)
  │   │   ├─ youtube_live_vision        (sampled-frame vision via yt-dlp + ffmpeg)
  │   │   ├─ sec_insider                (SEC Form 4 Atom feed)
  │   │   ├─ options_flow               (unusual options activity heuristic)
  │   │   └─ google_news / yahoo / bbc / bloomberg / marketwatch /
  │   │      stocktwits / reddit / x_via_gnews / youtube
  │   ├─ forecasting/                   (Chronos-2, TimesFM, TFT + XGBoost meta-learner)
  │   ├─ nlp/                           (FinBERT compound sentiment)
  │   ├─ alt_data/                      (analyst revision momentum)
  │   ├─ execution/                     (TWAP / VWAP slice planner)
  │   ├─ rl/                            (FinRL scaffold — regime-aware cold-start)
  │   ├─ paper_broker                   (ephemeral £100 GBP sandbox)
  │   ├─ broker_service                 (Trading 212 / LogBroker facade)
  │   ├─ risk_manager                   (Kelly + ATR sizing, regime-aware)
  │   ├─ data_loader                    (yfinance daily OHLCV cache)
  │   ├─ database                       (SQLite — journal, findings, scraper_items)
  │   ├─ config_schema                  (Pydantic AppConfig validator)
  │   └─ types_shared                   (AssetClass + tool contracts)
  │
  ├─ desktop/                           (PySide6 desktop app)
  │   ├─ main.py                        (shared bootstrap: license, wizard, launch)
  │   ├─ main_desktop.py                (desktop entry point)
  │   ├─ app.py                         (MainWindow — terminal-dark panels)
  │   ├─ state.py                       (AppState dataclass + config loader)
  │   ├─ panels/                        (positions, watchlist, news, chat,
  │   │                                  agent_log, chart, orders, exchanges, …)
  │   └─ dialogs/                       (setup wizard, license, trade, add_ticker, …)
  │
  ├─ server/                            (FastAPI license + admin API — deployed to Render)
  ├─ website/                           (landing / coming-soon / admin HTML)
  └─ installer/                         (PyInstaller specs + Inno Setup)
```

---

## 5 — Hub Files (BOSS ONLY — agents must not touch)

- `desktop/app.py` — main desktop window wiring, lifecycle, action handlers
- `desktop/main.py` — shared app bootstrap (license, wizard, launch)
- `core/agent/pool.py` — AgentPool: owns supervisor, chat workers, and swarm coordinator
- `core/agent/runner.py` — supervisor loop, assessor hook, cadence control
- `config.json` — all runtime configuration (validated by `core/config_schema.py`)
- `requirements.txt` / `requirements-desktop.txt` — dependency manifests (lightweight web for Render / full desktop terminal)

---

## 6 — Multi-Agent Team

| Role | Model | Responsibilities | Owns |
|------|-------|-----------------|------|
| **Boss / Orchestrator** | opus | Plans, owns hub files, integrates, reviews | Hub files, architecture decisions |
| **Feature Agent** | sonnet | Implements one system at a time (2-6 files) | Leaf system files |
| **Support Agent** | haiku | Docs, review checklists, boilerplate, search | `docs/systems/*.md`, changelogs |

The runtime agent fleet inside the application uses separate model assignments:

| Runtime role | Model (config key) | Effort |
|---|---|---|
| Supervisor (AgentRunner) | `model_complex` (Opus) | `max` |
| Chat — decision tier | `model_complex` (Opus) | `high` |
| Chat — info tier | `model_medium` (Sonnet) | `medium` |
| Research — deep tier | `model_medium` (Sonnet) | `high` |
| Research — quick tier | `model_simple` (Haiku) | `low` |
| Post-iteration assessor | `model_assessor` (Sonnet) | `medium` |
| Sentiment / transcripts | `model_simple` (Haiku) | — |

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
- **Phase 2.5–2.85:** 1000-analyst ensemble, regime detection, ARIMA/ETS baselines, pipeline visualisation — **done**
- **Phase 2.9:** MiroFish multi-agent simulation (1000 agents × 16 MC sims) — **done**
- **Phase 3.0:** Backtesting engine (walk-forward, parallel folds, Sharpe/Sortino/Calmar) — **done**
- **Phase 3.1:** Multi-asset expansion (stocks, crypto, polymarket) — **done**
- **Phase 3.15:** Autoconfig — autonomous parameter optimisation, 23+ experiments — **done**
- **Phase 3.2:** PySide6 desktop app (terminal-dark GUI, build to exe) — **done**
- **Phase 3.5:** Commercialisation — license server, setup wizard, admin panel, code signing — **done**
- **Phase 3.6:** Root reorganisation — core/ package, installer — **done**
- **Phase 4:** Production hardening, test coverage, monitoring — **in progress**
- **Phase 4.9 (2026-04-16):** Opus 4.7 everywhere (supervisor `max`,
  decision/deep research `high`, info/medium research `medium`, quick
  research `low`); Haiku reserved for sentiment + transcript
  summarisation. New YouTube transcript scraper (@markets channel +
  24/7 live stream). VADER sentiment on every scraper item.
  Information panel surfaces research findings + per-item sentiment
  badges. Watchlist auto-add on BUY. 45 s default cadence. Small-capital
  prompt tuning. Dead watchlist columns removed.
- **Phase 5.0 (2026-04-17):** Legacy ML pipeline fully removed
  (`terminal/`, `backtesting/`, `research/`, `polymarket/`, `crypto/`,
  `core/ai_service.py`, `core/ai_client.py`, `core/news_agent.py` all
  deleted). Pydantic `AppConfig` schema validates `config.json` at
  startup. Website split into shared design-system CSS + polished
  landing/coming-soon copy. Admin dashboard gains a 15-template email
  library (Jinja2) with live preview. Post-iteration assessor agent
  (Sonnet 4.6, `medium` effort) grades every supervisor iteration and
  writes its review into `agent_journal`. Live finance-TV vision
  scraper samples 3 frames per cycle from the 24/7 stream via
  yt-dlp + ffmpeg + Haiku vision, capped to 500 calls/day.

---

## 9 — Dependency Management

```
requirements.txt          ← Render server deploy only (fastapi, uvicorn, pydantic, …)
requirements-desktop.txt  ← full desktop terminal (ML, UI, agent loop, tests, build)
```

**Rules:**
- Never add desktop/ML/test dependencies to `requirements.txt` — it is the Render server manifest
- All desktop deps (including `pytest`, `pytest-mock`, `pyinstaller`) belong in `requirements-desktop.txt`
- Add a comment explaining any dependency whose purpose isn't obvious from its name
- Update dependencies intentionally — review changelogs before bumping major versions
- Install for local dev: `pip install -r requirements-desktop.txt`
- Render uses `requirements.txt` automatically via its build command

---

## 10 — Environment & Config

```
.env.example     ← committed: template with all required keys, no values
.env             ← NOT committed: actual secrets (in .gitignore)
config.json      ← committed: all runtime configuration (no secrets)
```

**Required environment variables** (see `.env.example`):
- `T212_API_KEY` — Trading 212 live trading API key (not needed in paper mode)
- `T212_SECRET_KEY` — Trading 212 secret

**Rules:**
- Secrets (API keys, broker credentials) come from environment variables — never from `config.json`
- Runtime config (thresholds, model params, feature flags) lives in `config.json`
- `config.json` is validated at startup by `core/config_schema.py` (Pydantic `AppConfig`) — bad config fails fast before anything starts
- Never read `os.environ` directly in business logic; go through `AppConfig` fields
- Broker operations always default to paper/log mode unless the config field is explicitly `true`

---

## 11 — Testing

| Layer | What to test | Command |
|-------|-------------|---------|
| Unit | Feature calculations, strategy logic, risk maths | `pytest tests/ -v` |
| Integration | Database reads/writes (SQLite), broker interface | `pytest tests/ -v` |
| Smoke | Full startup + signal pipeline | `python scripts/agent_repl.py` |

**Rules:**
- Tests live in `tests/` and mirror the source module they cover
- Mock only at system boundaries: yfinance HTTP calls, Trading 212 REST API, Claude CLI subprocess
- Never mock `database.py` — use a temp SQLite file or in-memory DB
- New code requires new tests unless it is pure wiring or UI glue
- Run `pytest tests/ -v` before marking any task done

### Smoke Test Checklist
- [ ] App starts without errors: `python desktop/main_desktop.py`
- [ ] Signal pipeline produces a buy/sell/hold recommendation for a valid ticker
- [ ] Broker defaults to paper mode — no real orders placed
- [ ] No error-level logs during normal startup and one full analysis cycle

---

## 12 — Error Handling

- **Fail loudly at startup** for missing required env vars when live mode is enabled, or for corrupt `config.json`. Use `sys.exit(1)` with a clear message — never a logged warning that gets ignored.
- **Broker operations:** errors from the Trading 212 API must never be silently dropped — raise with full context so the `AutoEngine` can back off correctly.
- **Never swallow exceptions silently.** `except Exception: pass` is a bug. At minimum, log with context.
- **Log at the right level:** `debug` for noise, `info` for expected events, `warning` for unexpected-but-handled, `error` for failures requiring attention.
- **Include actionable detail in error messages.** `"API call failed"` is useless. `"T212 order rejected: insufficient margin for AAPL buy 100 shares at $185.20"` is actionable.

---

## 13 — Before You Finish (Session Write-Back)

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

---

## 14 — CI/CD

CI runs on every push and pull request to `main`. See `.github/workflows/ci.yml`.

**Pipeline:** checkout → setup Python 3.12 → install deps → run pytest

**Rules:**
- Main branch must always pass CI — never push broken code directly to `main`
- All secrets (T212 keys, license server keys) go in repository secrets (GitHub → Settings → Secrets and variables → Actions), never in committed files
- Tests that call external services (yfinance, Trading 212) must mock those calls — no real HTTP in CI
- If CI is red, fix it before starting new work
