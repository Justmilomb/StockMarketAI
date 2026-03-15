# Master Prompt — AI-Driven Project Scaffold

> **Purpose:** Copy this into any new project as `CLAUDE.md` (or your AI tool's config). Adapt the `[FILL]` placeholders for your stack. Delete sections that don't apply.
>
> **Works for:** C++, Python, TypeScript/JS, Rust, Go, web apps, AI/ML, game dev, CLI tools, APIs — anything.

---

## 1 — What This Is

`[FILL: one sentence]` — e.g. "UE5 grand strategy game with photorealistic Earth globe" or "FastAPI microservice for invoice processing" or "Next.js SaaS dashboard with Stripe billing."

**Tech stack:** Best for use case
**Platform:** Windows 10
**Language(s):** English British

---

## 2 — Rules (non-negotiable)

> These override all other guidance. Agents must obey these unconditionally.

- `[FILL: your hard constraints — examples below]`
- **Don't ask permission.** Just execute. User trusts technical decisions.
- **No git operations.** User commits manually.

<details>
<summary>Example constraints by stack (pick relevant ones, delete rest)</summary>

**C++ / Unreal:**
- C++ only. No Blueprint logic. No UMG/WBP assets.
- All UI is Slate C++ inside the viewport client. Never create widget Blueprints.
- Source/Public/ is flat. No subdirectories.

**Python:**
- Type hints on every function signature. No `Any` except at serialization boundaries.
- No global mutable state. Config via env vars or dataclass, never module-level dicts.
- Tests use pytest. No unittest.TestCase subclasses.

**TypeScript / Web:**
- Strict TypeScript (`strict: true`). No `any`. No `@ts-ignore`.
- Components are functional + hooks. No class components.
- CSS via Tailwind utility classes. No CSS-in-JS, no .css files.

**Rust:**
- No `unsafe` without a `// SAFETY:` comment explaining the invariant.
- All public types implement `Debug`. Error types implement `thiserror::Error`.

**Go:**
- No `interface{}` / `any` in public APIs. Use generics or concrete types.
- Errors are values. No panics except in `main()` or test setup.

**AI / ML:**
- All experiments logged (MLflow / W&B / Trackio). No untracked runs.
- Reproducibility: pin all seeds, log all hyperparams, version datasets.
- Model artifacts go to registry, not git.

**General (all stacks):**
- No file over 400 lines. Split by logical concern.
- One class/module per file pair.
- Comments explain *why*, not *what*.
- No TODO comments in code — track in `CURRENT_TASKS.md`.
</details>

---

## 3 — Reading Order (cold start)

> Every agent reads these in order before touching code. This is the onboarding path.

1. **This file** (`CLAUDE.md`)
2. `docs/ARCHITECTURE.md` — system graph + data flow
3. `docs/CURRENT_TASKS.md` — what's done, what's next
4. `docs/CONTRACTS.md` — interface contracts (do not break these)
5. `docs/systems/<relevant>.md` — deep-dive on the system you'll touch
6. The interface file (`.h`, `__init__.py`, `types.ts`, `mod.rs`) for the module you'll modify

---

## 4 — Architecture Quick Reference

> Paste your system's dependency graph here. ASCII art preferred — renders everywhere.

```
[FILL: your system graph — example below]

MyApp (entry point)
  ├─ AuthService          (JWT + sessions)
  ├─ DatabaseLayer        (SQLAlchemy / Prisma / etc.)
  │   ├─ UserRepository
  │   └─ InvoiceRepository
  ├─ APIRouter            (endpoints)
  │   ├─ /auth/*
  │   ├─ /users/*
  │   └─ /invoices/*
  ├─ BackgroundWorker     (Celery / BullMQ / etc.)
  └─ FrontendApp          (React / Vue / etc.)
      ├─ Pages
      ├─ Components
      └─ Hooks/Stores
```

---

## 5 — Hub Files (BOSS ONLY — agents must not touch)

> Hub files wire everything together. Only the orchestrator (Boss/opus) modifies these to prevent merge conflicts.

- `[FILL: e.g. src/app.py, src/index.ts, GlobeManager.h/.cpp]` — main wiring
- `[FILL: e.g. src/types.ts, BorderTypes.h, schemas/]` — shared data types
- `[FILL: e.g. pyproject.toml, package.json, Build.cs]` — dependency manifest

---

## 6 — Multi-Agent Team

> Model tiers for AI-assisted development. Adjust model names to your provider.

| Role | Model | Responsibilities | Owns |
|------|-------|-----------------|------|
| **Boss / Orchestrator** | opus (strongest) | Plans, owns hub files, integrates, reviews | Hub files, architecture decisions |
| **Feature Agent** | sonnet (balanced) | Implements one system at a time (2-6 files) | Leaf system files |
| **Support Agent** | haiku (fast) | Docs, review checklists, boilerplate, search | `docs/systems/*.md`, changelogs |

### Dispatch Protocol

**Phase 1 — Prepare (Boss, sequential):**
1. Update shared types/schemas with any new structures needed
2. Update dependency manifest if adding modules
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
- Code reviewer: scan for compile/type errors, missing imports, contract violations
- Doc writer: update system docs for everything that changed

### Dispatch Prompt Template (Feature Agent)

```
You are {agent-name}, working on the {system} system for [PROJECT DESCRIPTION].

FILES YOU OWN (create/modify these only):
{file list}

CONTEXT (read-only reference):
{paste relevant interface/type contents}

TASK:
{specific implementation task}

CONSTRAINTS:
- Do NOT modify any file outside your owned list
- Do NOT add imports for modules outside your context
- [STACK-SPECIFIC RULES]
- Return the complete file contents when done
```

---

## 7 — Key Conventions

> Naming and style rules. Replace with your stack's conventions.

<details>
<summary>C++ (Unreal)</summary>

- `A` = Actor, `U` = UObject/Component, `F` = struct, `b` = bool
- Functions: PascalCase. Locals: camelCase. Members: PascalCase.
- `UPROPERTY` only for editor/GC exposure. Runtime flags = plain C++.
- Null-check every `Cast<>`. Null-check `GEngine->GameViewport`.
</details>

<details>
<summary>Python</summary>

- Classes: PascalCase. Functions/variables: snake_case. Constants: UPPER_SNAKE.
- Private members: `_leading_underscore`. No dunder abuse.
- Imports: stdlib → third-party → local (isort compatible).
- Docstrings: Google style on public functions. None on obvious internals.
</details>

<details>
<summary>TypeScript</summary>

- Interfaces: PascalCase, no `I` prefix. Types over interfaces where possible.
- Functions/variables: camelCase. Constants: UPPER_SNAKE or camelCase.
- Components: PascalCase filenames matching export name.
- Barrel exports (`index.ts`) at module boundaries only.
</details>

<details>
<summary>Rust</summary>

- Types: PascalCase. Functions/variables: snake_case. Constants: UPPER_SNAKE.
- Modules: snake_case directories. `mod.rs` for public re-exports.
- Error types: `thiserror` for libraries, `anyhow` for binaries.
</details>

<details>
<summary>Go</summary>

- Exported: PascalCase. Unexported: camelCase.
- Packages: short, lowercase, no underscores.
- Interfaces: `-er` suffix when possible (Reader, Writer, Handler).
- Error wrapping: `fmt.Errorf("context: %w", err)`.
</details>

---

## 8 — Current Phase

> Track your project's development phases here. Check off completed work.

- **Phase 1:** `[FILL: foundation — e.g. project setup, core data layer]` — `[status]`
- **Phase 2:** `[FILL: primary features — e.g. API endpoints, UI shell]` — `[status]`
- **Phase 3:** `[FILL: advanced features — e.g. real-time, ML pipeline]` — `[status]`
- **Phase 4:** `[FILL: polish — e.g. auth, monitoring, deployment]` — `[status]`

---

# Documentation Structure

> Create these files in `docs/`. Each has a specific purpose. Together they form a complete project knowledge base that enables safe parallel work, fast onboarding, and clear handoffs.

---

## docs/ARCHITECTURE.md

> **Purpose:** Single source of truth for system structure. ASCII dependency graph + subsystem responsibility table.

```markdown
# Architecture

## System Graph

\```
[ASCII art showing all modules/services and their relationships]
[Show data flow direction with arrows]
[Mark hub modules that wire everything together]
\```

## Subsystem Responsibilities

| System | Owns | Must NOT |
|--------|------|----------|
| [SystemA] | [what it controls] | [what it must never do] |
| [SystemB] | ... | ... |

## Key Types / Schemas

| Type | Location | Purpose |
|------|----------|---------|
| [TypeName] | [file path] | [what it represents] |

## Phase Map

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | [description] | [done/in-progress/planned] |
| 2 | ... | ... |
```

---

## docs/SYSTEM_OVERVIEW.md

> **Purpose:** High-level project context — goal, runtime lifecycle, tech stack, constraints. For someone who has never seen the project.

```markdown
# System Overview

## Project Goal
[1-2 sentences: what this project does and why it exists]

## Runtime Lifecycle
[Ordered list: what happens from process start to steady state]
1. Entry point loads → ...
2. Config parsed → ...
3. Services initialized → ...
4. Ready to serve / Main loop begins

## Tech Stack
| Component | Technology | Why |
|-----------|-----------|-----|
| [Language] | [e.g. Python 3.12] | [reason] |
| [Framework] | [e.g. FastAPI] | [reason] |
| [Database] | [e.g. PostgreSQL 16] | [reason] |

## Key Constraints
- [Constraint 1 — e.g. "No ORM magic queries; raw SQL or query builder only"]
- [Constraint 2]
```

---

## docs/CURRENT_TASKS.md

> **Purpose:** Single source of truth for work status. What's done, what's in progress, what's next. Agents check this before starting work.

```markdown
# Current Tasks

## Active Phase: [Phase N — Name]

### Completed
- [x] [Task description] — [date or PR]
- [x] ...

### In Progress
- [ ] [Task description] — [who/what agent is working on it]

### Up Next
- [ ] [Task description]
- [ ] ...

### Blocked
- [ ] [Task description] — blocked by: [reason]

## How to Pick Up Work
1. Read docs/ARCHITECTURE.md for context
2. Check "In Progress" — don't duplicate active work
3. Pick from "Up Next" in order
4. Move task to "In Progress" with your name/agent-id
5. Complete the task + update all relevant docs
6. Move task to "Completed" with date
```

---

## docs/CONTRACTS.md

> **Purpose:** Explicit interface contracts between every system pair that communicates. Breaking any of these is a regression. This is the most critical doc for safe parallel work.

```markdown
# Interface Contracts

Explicit contracts between every system pair that communicates.
Breaking any of these is a regression.

---

## [SystemA] ↔ [SystemB]

**Access pattern:** [how A finds/references B]

**A calls on B:**
| Function | When | Returns |
|----------|------|---------|
| `methodName(params)` | [trigger condition] | `ReturnType` |

**Invariants:**
- [Rule that must never be broken — e.g. "A never destroys B"]
- [Ordering constraint — e.g. "init() must be called before process()"]

---

## [SystemC] Public API

**Initialization contract:**
- `init(config)` — called exactly once at startup. Must be called before any other method.

**Runtime contracts:**
- `process(input)` — safe to call with any input; returns error on invalid data, never throws/panics.
- `getState()` → `readonly` — callers must NOT mutate the returned reference.

**Invariants:**
- [State machine rules, ordering constraints, thread safety guarantees]
```

---

## docs/CODING_STANDARDS.md

> **Purpose:** Naming conventions, style rules, pointer/memory safety, error handling patterns. Language-specific.

```markdown
# Coding Standards

## Naming
| Element | Convention | Example |
|---------|-----------|---------|
| Classes/Types | PascalCase | `UserService`, `InvoiceData` |
| Functions | [stack convention] | `process_invoice` / `processInvoice` |
| Variables | [stack convention] | `total_amount` / `totalAmount` |
| Constants | UPPER_SNAKE | `MAX_RETRIES`, `DEFAULT_TIMEOUT` |
| Booleans | `is_`/`has_`/`b` prefix | `is_active`, `has_loaded`, `bReady` |

## File Organization
- No file over 400 lines. Split by logical concern.
- One class/module per file (except small value types).
- [Stack-specific: include order, import order, etc.]

## Error Handling
- [Stack-specific patterns — e.g. Result types, exceptions, error codes]
- Validate at system boundaries (user input, external APIs). Trust internal code.
- Log unexpected states at Warning level. Log failures at Error level.

## Safety Rules
- [Stack-specific — e.g. null checks, ownership, memory management]

## Comments
- Class-level doc comment required on every public type.
- Function-level doc only if behavior is non-obvious.
- Inline comments explain *why*, never *what*.
- No commented-out code. Delete it; git has the history.

## Formatting
- [Tab/space preference, line length, brace style]
- [Formatter config reference if applicable]
```

---

## docs/AGENT_WORKFLOW.md

> **Purpose:** Step-by-step process for any agent (AI or human) to safely make changes.

```markdown
# Agent Workflow

How any agent (AI or human) should orient and safely make changes.

## Reading Order (cold start)
1. `docs/ARCHITECTURE.md` — understand the system graph
2. `docs/SYSTEM_OVERVIEW.md` — understand the project goal and lifecycle
3. `docs/CURRENT_TASKS.md` — understand what is in progress
4. `docs/CONTRACTS.md` — understand interface contracts
5. `docs/systems/<relevant>.md` — deep-dive on the system you'll touch
6. The interface file for the module you'll modify

## Before Touching a File
1. **Read the full interface + implementation** for the module you'll change.
2. **Search for all callers** of any function you'll modify or rename.
3. **Check `CURRENT_TASKS.md`** — is another task already touching this?
4. **Understand the `CONTRACTS.md` entry** — do not break call sequences or return types.

## Making a Change
1. Edit interface first, then implementation.
2. Update dependency manifest if adding new packages/modules.
3. Build / type-check / lint — must pass with 0 errors.
4. Run the test suite (see `TESTING.md`).
5. Update docs in the same change:
   - `docs/systems/<system>.md` if behavior changed
   - `docs/CONTRACTS.md` if any interface changed
   - `docs/ARCHITECTURE.md` if a module was added or removed
   - `docs/CHANGELOG.md` with a one-line entry
   - `docs/CURRENT_TASKS.md` to check off completed work

## Adding a New System / Module
1. Create the new files in the correct directory.
2. Update dependency manifest if needed.
3. Create `docs/systems/<system-name>.md` (150 words max).
4. Add to the graph in `docs/ARCHITECTURE.md`.
5. Add all call contracts to `docs/CONTRACTS.md`.
6. Add a `CHANGELOG.md` entry.
7. Update `CURRENT_TASKS.md`.

## Never
- [FILL: stack-specific never-do list]
- Never skip the test suite.
- Never modify hub files without Boss/orchestrator approval.
- Never leave broken imports or unresolved references.
- Never add dependencies without updating the manifest.
```

---

## docs/TESTING.md

> **Purpose:** Verification protocol. What must pass before any change is considered done.

```markdown
# Testing

## Build Verification
- [FILL: build command] — must complete with 0 errors, 0 warnings.
- [FILL: type-check command if applicable]
- [FILL: lint command if applicable]

## Test Suite
- [FILL: test command — e.g. `pytest`, `npm test`, `cargo test`]
- All existing tests must pass. No skipping without documented reason.
- New code requires new tests unless it's pure wiring/glue.

## Smoke Test Checklist
> Manual verification steps for changes to core systems.

1. [ ] [Step 1 — e.g. "App starts without errors"]
2. [ ] [Step 2 — e.g. "Login flow works end-to-end"]
3. [ ] [Step 3 — e.g. "Core feature X produces correct output"]
4. [ ] [Step N — e.g. "No error-level logs in output"]

## Regression Rule
Full smoke test required for changes to: [list core files/modules].

## Log Patterns
- **Error (must fix):** [patterns that indicate real problems]
- **Warning (investigate):** [patterns that might indicate problems]
- **Benign (ignore):** [patterns that look scary but are expected]
```

---

## docs/LINTING.md

> **Purpose:** Static analysis rules, compiler/linter config, manual review checklist.

```markdown
# Linting & Static Analysis

## Automated Tools
| Tool | Config File | Command |
|------|------------|---------|
| [linter] | [config path] | [command] |
| [formatter] | [config path] | [command] |
| [type checker] | [config path] | [command] |

## Key Rules
- [Rule 1 — e.g. "No unused imports"]
- [Rule 2 — e.g. "No wildcard imports"]
- [Rule 3 — e.g. "Max cyclomatic complexity: 10"]

## Manual Review Checklist
- [ ] No dead code (unused functions, unreachable branches)
- [ ] No hardcoded secrets, keys, or credentials
- [ ] No TODO/FIXME without a CURRENT_TASKS.md entry
- [ ] All public APIs have doc comments
- [ ] Error paths are handled (no silent swallows)
- [ ] No duplicate logic that should be extracted
```

---

## docs/DIRECTORY_STRUCTURE.md

> **Purpose:** Where files go. Prevents structural drift across agents and sessions.

```markdown
# Directory Structure

\```
project-root/
├── [FILL: source directory layout]
│   ├── [modules/components/packages]
│   └── ...
├── tests/                          ← Test files mirror source structure
├── docs/                           ← All documentation (authoritative)
│   ├── ARCHITECTURE.md
│   ├── SYSTEM_OVERVIEW.md
│   ├── CURRENT_TASKS.md
│   ├── CONTRACTS.md
│   ├── CODING_STANDARDS.md
│   ├── AGENT_WORKFLOW.md
│   ├── TESTING.md
│   ├── LINTING.md
│   ├── DIRECTORY_STRUCTURE.md
│   ├── CHANGELOG.md
│   ├── plans/                      ← Design docs (date-prefixed)
│   └── systems/                    ← Atomic per-system docs (~150 words)
├── config/                         ← Environment and app config
├── scripts/                        ← Build, deploy, utility scripts
├── [dependency manifest]           ← package.json / pyproject.toml / Cargo.toml / etc.
└── CLAUDE.md                       ← AI agent entry point (this template)
\```

## Rules
- [FILL: e.g. "Source directories are flat — no nested subdirectories"]
- [FILL: e.g. "One class per file pair (.h/.cpp) or one module per file"]
- Tests mirror source directory structure.
- `docs/` is the authoritative knowledge base. Code comments supplement, not replace.
- `docs/systems/` contains one ~150-word doc per system/module.
- `docs/plans/` contains dated design documents for major features.
```

---

## docs/CHANGELOG.md

> **Purpose:** Architectural decision log. Newest first. One-liners referencing what changed and why.

```markdown
# Changelog

Architectural decisions and significant changes. Newest first.

---

## [YYYY-MM-DD]

- [One-line description of change + why]
- [Another change]
```

---

## docs/systems/ (Atomic System Docs)

> **Purpose:** One file per system/module. ~150 words max. Enables rapid context-loading without reading source.

**Filename:** `docs/systems/<system-name>.md` (kebab-case, matches module name)

```markdown
# [System Name]

## Goal
[1-2 sentences: what this system does and why it exists]

## Implementation
[3-5 sentences: key technical approach, data structures, algorithms]

## Key Code
\```[language]
// Most important function signature or usage pattern
[code snippet]
\```

## Notes
- [Key parameter, threshold, or config value]
- [Important invariant or gotcha]
- [Keyboard shortcut or CLI flag if applicable]
```

---

## docs/plans/ (Design Documents)

> **Purpose:** Dated design docs for major features. Written before implementation. Historical record of intent.

**Filename:** `docs/plans/YYYY-MM-DD-feature-name.md`

```markdown
# [Feature Name] — Design Document

**Date:** YYYY-MM-DD
**Status:** [draft / approved / implemented / superseded]
**Phase:** [which project phase this belongs to]

## Overview
[What we're building and why]

## Tech Stack Decisions
| Component | Choice | Why |
|-----------|--------|-----|
| ... | ... | ... |

## Implementation Tasks
1. [Task with clear deliverable]
2. ...

## Out of Scope
- [Explicitly excluded items to prevent scope creep]

## Success Criteria
- [ ] [Measurable outcome 1]
- [ ] [Measurable outcome 2]
```

---

# Quick-Start Checklist

> When starting a new project, create these files in order:

- [ ] Copy this file → `CLAUDE.md` in project root
- [ ] Fill all `[FILL]` placeholders in `CLAUDE.md`
- [ ] Create `docs/` directory
- [ ] Write `docs/ARCHITECTURE.md` (even if minimal — just the initial graph)
- [ ] Write `docs/SYSTEM_OVERVIEW.md` (goal, stack, constraints)
- [ ] Write `docs/CURRENT_TASKS.md` (initial task list)
- [ ] Write `docs/CONTRACTS.md` (even if empty — "No contracts yet")
- [ ] Write `docs/CODING_STANDARDS.md` (naming + style rules for your stack)
- [ ] Write `docs/AGENT_WORKFLOW.md` (reading order + change process)
- [ ] Write `docs/TESTING.md` (build command + smoke test)
- [ ] Write `docs/LINTING.md` (tool list + manual checklist)
- [ ] Write `docs/DIRECTORY_STRUCTURE.md` (where files go)
- [ ] Write `docs/CHANGELOG.md` (empty template)
- [ ] Create `docs/systems/` directory
- [ ] Create `docs/plans/` directory

---

# Appendix A — Agent Memory Configuration

> For Claude Code, configure persistent memory to carry context across sessions.

**Memory location:** `~/.claude/projects/<project-hash>/memory/`

**Recommended memory files:**

| File | Type | Purpose |
|------|------|---------|
| `MEMORY.md` | index | Links to all other memory files (loaded every session) |
| `agent-workflow.md` | reference | Multi-agent dispatch protocol + dependency graph |
| `user-preferences.md` | user | How the user likes to work, stack expertise, communication style |
| `project-decisions.md` | project | Key architectural decisions with rationale |

---

# Appendix B — Stack-Specific CLAUDE.md Examples

<details>
<summary>Python (FastAPI / Django / Flask)</summary>

```markdown
## Rules (non-negotiable)
- Python 3.12+. Type hints on all function signatures.
- No `Any` except at serialization boundaries.
- No global mutable state. Config via pydantic Settings.
- Tests: pytest only. No unittest.TestCase.
- Async by default (FastAPI). Sync only for CPU-bound work.
- No ORM lazy loading. Explicit `.options(selectinload(...))` or raw SQL.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `src/main.py` — app factory + router wiring
- `src/models/` — SQLAlchemy/Pydantic schemas
- `pyproject.toml` — dependencies

## Key Conventions
- Functions: snake_case. Classes: PascalCase. Constants: UPPER_SNAKE.
- Imports: stdlib → third-party → local.
- One router per domain module.
- Pydantic models for all request/response schemas.
```
</details>

<details>
<summary>TypeScript (Next.js / React)</summary>

```markdown
## Rules (non-negotiable)
- Strict TypeScript. No `any`. No `@ts-ignore`.
- Functional components + hooks. No class components.
- CSS: Tailwind utility classes only. No CSS-in-JS.
- State: Zustand for global, React state for local.
- Data fetching: React Query (TanStack Query). No useEffect for fetching.
- No barrel exports except at package boundaries.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `src/app/layout.tsx` — root layout + providers
- `src/lib/api.ts` — API client singleton
- `package.json` — dependencies

## Key Conventions
- Components: PascalCase files matching export name.
- Hooks: `use` prefix, camelCase.
- Utils: camelCase. Types: PascalCase.
- Co-locate tests: `component.test.tsx` next to `component.tsx`.
```
</details>

<details>
<summary>C++ (Unreal Engine 5)</summary>

```markdown
## Rules (non-negotiable)
- C++ only. No Blueprint logic. No UMG/WBP assets.
- All UI is Slate C++ inside UMyGameViewportClient.
- Source/Public/ is flat. No subdirectories.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `GameManager.h/.cpp` — wires all systems together
- `SharedTypes.h` — shared data structs
- `MyProject.Build.cs` — module dependencies

## Key Conventions
- A = Actor, U = UObject/Component, F = struct, b = bool.
- Functions: PascalCase. Locals: camelCase. Members: PascalCase.
- UPROPERTY only for editor/GC exposure.
- Null-check every Cast<>. No raw UObject* members.
```
</details>

<details>
<summary>Rust (Actix / Axum / CLI)</summary>

```markdown
## Rules (non-negotiable)
- No `unsafe` without `// SAFETY:` comment.
- All public types: Debug + Clone where possible.
- Errors: thiserror for lib, anyhow for binary.
- No `.unwrap()` in library code. `.expect("reason")` only in tests/main.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `src/main.rs` or `src/lib.rs` — entry + module declarations
- `src/types/mod.rs` — shared types
- `Cargo.toml` — dependencies

## Key Conventions
- Types: PascalCase. Functions/variables: snake_case.
- Modules: snake_case. Re-export public API from mod.rs.
- Builder pattern for complex construction.
- Prefer &str over String in function parameters.
```
</details>

<details>
<summary>Go (API / CLI)</summary>

```markdown
## Rules (non-negotiable)
- No `interface{}` / `any` in public APIs.
- Errors are values. No panics except in main() or test setup.
- Context propagation: first parameter is always `ctx context.Context`.
- No init() functions. Explicit initialization.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `cmd/server/main.go` — entry point + wiring
- `internal/types/` — shared types
- `go.mod` — dependencies

## Key Conventions
- Exported: PascalCase. Unexported: camelCase.
- Packages: short, lowercase, no underscores.
- Interfaces: `-er` suffix (Reader, Handler, Processor).
- Table-driven tests with `t.Run()` subtests.
```
</details>

<details>
<summary>AI / ML (PyTorch / HuggingFace / Training)</summary>

```markdown
## Rules (non-negotiable)
- All experiments logged (MLflow / W&B / Trackio). No untracked runs.
- Reproducibility: pin seeds, log hyperparams, version datasets.
- Model artifacts → registry (HF Hub / MLflow), not git.
- Data pipelines: idempotent. Re-running produces identical output.
- No notebooks in production. Scripts only. Notebooks for exploration.
- Don't ask permission. Just execute.
- No git operations. User commits manually.

## Hub Files (BOSS ONLY)
- `src/train.py` — training entry point
- `src/config.py` — all hyperparams + paths
- `pyproject.toml` — dependencies

## Key Conventions
- Config: dataclass or pydantic, never argparse for complex configs.
- Models: subclass nn.Module. Forward signature documented.
- Data: torch Dataset/DataLoader. HF datasets for large-scale.
- Checkpoints: save optimizer state + model state + epoch + metrics.
```
</details>

---

# Appendix C — Why This Structure Works

This documentation architecture solves five problems that kill AI-assisted projects:

1. **Context loss between sessions.** CLAUDE.md + reading order means every session starts with full understanding, not guessing.

2. **Parallel agent conflicts.** Hub files + owned file lists + CONTRACTS.md mean multiple agents can work simultaneously without stepping on each other.

3. **Regression from ignorance.** CONTRACTS.md makes implicit assumptions explicit. An agent can't accidentally break a call sequence it didn't know about.

4. **Documentation drift.** The "update docs in the same change" rule in AGENT_WORKFLOW.md keeps docs in sync with code. Atomic system docs (150 words) are small enough that updating them is never a burden.

5. **Onboarding cost.** A new agent (or human) reads 10 files in a specific order and has complete project context in minutes. No archaeology required.
