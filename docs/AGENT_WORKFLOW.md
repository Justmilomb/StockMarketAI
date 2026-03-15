# Agent Workflow

How any agent (AI or human) should orient and safely make changes.

## Reading Order (cold start)

1. `CLAUDE.md` — project identity, rules, architecture quick reference
2. `docs/ARCHITECTURE.md` — full system graph + subsystem responsibilities
3. `docs/SYSTEM_OVERVIEW.md` — project goal, runtime lifecycle, tech stack
4. `docs/CURRENT_TASKS.md` — what's done, in progress, and next
5. `docs/CONTRACTS.md` — interface contracts between all system pairs
6. `docs/systems/<relevant>.md` — deep-dive on the system you'll touch
7. The source file for the module you'll modify

## Before Touching a File

1. **Read the full source** for the module you'll change.
2. **Search for all callers** of any function you'll modify or rename.
3. **Check `CURRENT_TASKS.md`** — is another task already touching this?
4. **Understand the `CONTRACTS.md` entry** — do not break call sequences or return types.
5. **Check `config.json`** — does the module depend on config keys?

## Making a Change

1. Edit interface first (function signatures, dataclass fields), then implementation.
2. Update `requirements.txt` if adding new packages.
3. Run the test suite: `pytest` (must pass with 0 failures).
4. Run type checking: `mypy --ignore-missing-imports *.py terminal/*.py`
5. Update docs in the same change:
   - `docs/systems/<system>.md` if behaviour changed
   - `docs/CONTRACTS.md` if any interface changed
   - `docs/ARCHITECTURE.md` if a module was added or removed
   - `docs/CHANGELOG.md` with a one-line entry
   - `docs/CURRENT_TASKS.md` to check off completed work

## Adding a New System / Module

1. Create the new file in the project root (or `terminal/` for TUI components).
2. Update `requirements.txt` if adding dependencies.
3. Create `docs/systems/<system-name>.md` (150 words max).
4. Add to the graph in `docs/ARCHITECTURE.md`.
5. Add all call contracts to `docs/CONTRACTS.md`.
6. Add a `docs/CHANGELOG.md` entry.
7. Update `docs/CURRENT_TASKS.md`.

## Never

- Never modify hub files (`terminal/app.py`, `ai_service.py`, `config.json`, `requirements.txt`) without Boss/orchestrator approval.
- Never skip the test suite.
- Never leave broken imports or unresolved references.
- Never add dependencies without updating `requirements.txt`.
- Never hardcode API keys, passwords, or secrets.
- Never submit real broker orders in test/dev without explicit confirmation.
- Never mutate `AppState` from views — only `terminal/app.py` mutates state.
