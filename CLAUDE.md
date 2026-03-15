# StockMarketAI — AI Agent Entry Point

AI-driven stock trading terminal combining scikit-learn ML predictions with Google Gemini LLM analysis, rendered in a Bloomberg-style Textual TUI. Supports paper and live trading via Trading 212.

**Tech stack:** Python 3.12+, scikit-learn, Textual, Google Gemini API, yfinance, pandas, numpy
**Platform:** Windows 10
**Language(s):** English British

---

## 2 — Rules (non-negotiable)

- Type hints on every function signature. No `Any` except at serialisation boundaries.
- No global mutable state. Config via dataclass or `config.json`, never module-level dicts.
- Tests use pytest. No unittest.TestCase subclasses.
- No file over 400 lines. Split by logical concern.
- One class/module per file pair.
- Comments explain *why*, not *what*.
- No TODO comments in code — track in `docs/CURRENT_TASKS.md`.
- **Don't ask permission.** Just execute. User trusts technical decisions.
- **No git operations.** User commits manually.
- No hardcoded API keys. All secrets via environment variables.
- Broker operations default to paper/log mode unless explicitly configured.

---

## 3 — Reading Order (cold start)

1. **This file** (`CLAUDE.md`)
2. `docs/ARCHITECTURE.md` — system graph + data flow
3. `docs/CURRENT_TASKS.md` — what's done, what's next
4. `docs/CONTRACTS.md` — interface contracts (do not break these)
5. `docs/systems/<relevant>.md` — deep-dive on the system you'll touch
6. The source file for the module you'll modify

---

## 4 — Architecture Quick Reference

```
ai.py / terminal/app.py  (entry points)
  │
  ├─ AiService              (ML + Gemini orchestration)
  │   ├─ data_loader         (yfinance OHLCV + CSV cache)
  │   ├─ features            (technical indicators + labels)
  │   ├─ model               (RandomForest train/predict)
  │   ├─ gemini_client       (Gemini API: signals, news, chat)
  │   └─ strategy            (probability → buy/sell/hold)
  │
  ├─ BrokerService           (broker-agnostic facade)
  │   ├─ LogBroker           (dev: logs to JSONL)
  │   └─ Trading212Broker    (live: REST API v0)
  │
  ├─ AutoEngine              (signal → order execution)
  │
  ├─ NewsAgent               (background RSS + sentiment)
  │
  └─ terminal/
      ├─ app.py              (TradingTerminalApp — Textual App)
      ├─ state.py            (AppState dataclass)
      ├─ views.py            (panels + modals)
      ├─ charts.py           (sparkline price charts)
      └─ terminal.css        (Bloomberg-dark theme)
```

---

## 5 — Hub Files (BOSS ONLY — agents must not touch)

- `terminal/app.py` — main TUI wiring, lifecycle, action handlers
- `ai_service.py` — orchestrates ML + Gemini weighted ensemble
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
- **Phase 2:** TUI terminal + Gemini integration + news agent + Trading 212 — **done**
- **Phase 3:** Testing, backtesting engine, advanced strategies, multi-model ensemble — **planned**
- **Phase 4:** Production hardening, monitoring, deployment automation — **planned**
