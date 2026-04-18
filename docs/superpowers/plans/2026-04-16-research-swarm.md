# Research Swarm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 20-agent research swarm that runs 24/7, mining news/social/Grok intelligence and feeding structured findings to the trading supervisor.

**Architecture:** A `SwarmCoordinator` daemon thread manages a bounded worker pool (default 4 concurrent). Twenty logical roles (10 quick-reaction, 10 deep-research) rotate through the pool on cadence. Each `ResearchWorker` is a QThread running the claude-agent-sdk with research-only tools (no trading). A Playwright-based `query_grok` tool lets agents ask Grok AI to mine X/Twitter intelligence. Findings land in `research_findings` and the supervisor reads them every iteration.

**Tech Stack:** Python 3.12, claude-agent-sdk, PySide6 (QThread), Playwright (headless Chromium), SQLite

---

## File Map

### New files

| File | Responsibility |
|------|---------------|
| `core/agent/research_roles.py` | 20 role dataclass definitions (id, tier, model tier, cadence, focus description) |
| `core/agent/research_queue.py` | Priority task queue + task generation from role cadences |
| `core/agent/research_worker.py` | QThread that runs one research task via claude-agent-sdk |
| `core/agent/prompts_research.py` | System prompt templates per role |
| `core/agent/swarm.py` | SwarmCoordinator — lifecycle, worker pool, scheduling loop |
| `core/agent/tools/research_tools.py` | submit_finding, get_findings, set_research_goal, get_swarm_status |
| `core/agent/tools/grok_tools.py` | query_grok (Playwright-based Grok AI on X) |
| `tests/test_research_swarm.py` | Unit + integration tests for swarm components |

### Modified files

| File | Change |
|------|--------|
| `core/database.py` | Add research_tasks, research_findings, research_goals tables in `_init_db` |
| `core/agent/mcp_server.py` | Import and register RESEARCH_TOOLS + GROK_TOOLS in ALL_TOOLS |
| `core/agent/model_router.py` | Add `research_worker_model(config, role)` — Haiku for tier-1, Sonnet for tier-2 |
| `core/agent/pool.py` | Add `_swarm: Optional[SwarmCoordinator]`, `start_swarm()`, `stop_swarm()` |
| `core/agent/prompts.py` | Add `## Swarm Intelligence Brief` block to supervisor prompt |
| `desktop/app.py` | Call `self._start_swarm()` at boot, wire status signals |
| `config.json` | Add `"swarm"` section |
| `installer/blank.spec` | Add new modules to `hiddenimports` |
| `requirements.txt` | Add `playwright` |

---

## Task 1: Database Schema — Research Tables

**Files:**
- Modify: `core/database.py` (inside `_init_db`, after existing `scraper_items` table, ~line 210)
- Test: `tests/test_research_swarm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_swarm.py`:

```python
"""Tests for the research swarm infrastructure."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


class TestResearchSchema:
    """Verify the three research tables exist after HistoryManager init."""

    def test_research_tables_created(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        with sqlite3.connect(db.db_path) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "research_tasks" in tables
        assert "research_findings" in tables
        assert "research_goals" in tables

    def test_research_tasks_columns(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        with sqlite3.connect(db.db_path) as conn:
            info = conn.execute("PRAGMA table_info(research_tasks)").fetchall()
        col_names = {row[1] for row in info}
        assert col_names >= {
            "id", "role", "status", "ticker", "parameters",
            "goal_id", "priority", "assigned_worker",
            "created_at", "started_at", "completed_at", "error",
        }

    def test_research_findings_columns(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        with sqlite3.connect(db.db_path) as conn:
            info = conn.execute("PRAGMA table_info(research_findings)").fetchall()
        col_names = {row[1] for row in info}
        assert col_names >= {
            "id", "task_id", "role", "ticker", "finding_type",
            "headline", "detail", "confidence_pct", "source",
            "methodology", "evidence_json", "acted_on", "created_at",
        }

    def test_research_goals_columns(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        with sqlite3.connect(db.db_path) as conn:
            info = conn.execute("PRAGMA table_info(research_goals)").fetchall()
        col_names = {row[1] for row in info}
        assert col_names >= {
            "id", "goal", "status", "priority", "created_by",
            "target_roles", "deadline_at", "findings_count",
            "created_at", "completed_at",
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchSchema -v`
Expected: FAIL — tables don't exist yet.

- [ ] **Step 3: Add research tables to database.py**

In `core/database.py`, inside `_init_db`, after the `scraper_items` table block (after line ~225), add:

```python
                -- Research swarm: task queue, structured findings, goals
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    ticker TEXT,
                    parameters TEXT,
                    goal_id INTEGER,
                    priority INTEGER NOT NULL DEFAULT 5,
                    assigned_worker TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_rt_status ON research_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_rt_role ON research_tasks(role);
                CREATE INDEX IF NOT EXISTS idx_rt_priority ON research_tasks(priority);

                CREATE TABLE IF NOT EXISTS research_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER,
                    role TEXT NOT NULL,
                    ticker TEXT,
                    finding_type TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    detail TEXT,
                    confidence_pct INTEGER NOT NULL DEFAULT 50,
                    source TEXT,
                    methodology TEXT,
                    evidence_json TEXT,
                    acted_on INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_rf_ticker ON research_findings(ticker);
                CREATE INDEX IF NOT EXISTS idx_rf_confidence ON research_findings(confidence_pct);
                CREATE INDEX IF NOT EXISTS idx_rf_created ON research_findings(created_at);
                CREATE INDEX IF NOT EXISTS idx_rf_type ON research_findings(finding_type);

                CREATE TABLE IF NOT EXISTS research_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER NOT NULL DEFAULT 5,
                    created_by TEXT,
                    target_roles TEXT,
                    deadline_at TEXT,
                    findings_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    completed_at TEXT
                );
```

- [ ] **Step 4: Add helper methods to HistoryManager**

Still in `core/database.py`, add these methods to the `HistoryManager` class (after the existing `purge_old_scraper_items` method):

```python
    # ── research swarm helpers ──────────────────────────────────────

    def insert_research_task(
        self,
        role: str,
        priority: int = 5,
        ticker: str | None = None,
        parameters: str | None = None,
        goal_id: int | None = None,
    ) -> int:
        """Insert a research task and return its id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO research_tasks "
                "(role, priority, ticker, parameters, goal_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (role, priority, ticker, parameters, goal_id),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def claim_research_task(self, worker_id: str) -> dict | None:
        """Atomically claim the highest-priority pending task.

        Returns the task dict or None if the queue is empty.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, role, ticker, parameters, goal_id, priority "
                "FROM research_tasks "
                "WHERE status = 'pending' "
                "ORDER BY priority ASC, created_at ASC LIMIT 1",
            ).fetchone()
            if row is None:
                return None
            task_id, role, ticker, params, goal_id, priority = row
            conn.execute(
                "UPDATE research_tasks "
                "SET status = 'running', assigned_worker = ?, "
                "    started_at = datetime('now') "
                "WHERE id = ?",
                (worker_id, task_id),
            )
            return {
                "id": task_id,
                "role": role,
                "ticker": ticker,
                "parameters": params,
                "goal_id": goal_id,
                "priority": priority,
            }

    def complete_research_task(
        self, task_id: int, *, error: str | None = None,
    ) -> None:
        """Mark a research task as completed or failed."""
        status = "failed" if error else "completed"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE research_tasks "
                "SET status = ?, completed_at = datetime('now'), error = ? "
                "WHERE id = ?",
                (status, error, task_id),
            )

    def save_research_finding(self, finding: dict) -> int:
        """Insert a research finding and return its id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO research_findings "
                "(task_id, role, ticker, finding_type, headline, detail, "
                " confidence_pct, source, methodology, evidence_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    finding.get("task_id"),
                    finding["role"],
                    finding.get("ticker"),
                    finding["finding_type"],
                    finding["headline"],
                    finding.get("detail"),
                    finding.get("confidence_pct", 50),
                    finding.get("source"),
                    finding.get("methodology"),
                    finding.get("evidence_json"),
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_research_findings(
        self,
        *,
        since_minutes: int = 360,
        min_confidence: int = 0,
        ticker: str | None = None,
        finding_type: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Read recent research findings, newest first."""
        clauses = [
            "created_at >= datetime('now', ?)",
        ]
        params: list[Any] = [f"-{since_minutes} minutes"]

        if min_confidence > 0:
            clauses.append("confidence_pct >= ?")
            params.append(min_confidence)
        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if finding_type:
            clauses.append("finding_type = ?")
            params.append(finding_type)

        where = " AND ".join(clauses)
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM research_findings WHERE {where} "
                f"ORDER BY confidence_pct DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_research_task_stats(self) -> dict:
        """Return counts by status for the research task queue."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM research_tasks GROUP BY status",
            ).fetchall()
        return {status: count for status, count in rows}

    def purge_old_research_data(self, keep_days: int = 30) -> None:
        """Remove old research tasks + findings beyond the retention window."""
        cutoff = f"-{keep_days} days"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM research_findings WHERE created_at < datetime('now', ?)",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM research_tasks "
                "WHERE status IN ('completed', 'failed') "
                "AND completed_at < datetime('now', ?)",
                (cutoff,),
            )

    def insert_research_goal(
        self,
        goal: str,
        priority: int = 5,
        created_by: str = "supervisor",
        target_roles: str | None = None,
        deadline_at: str | None = None,
    ) -> int:
        """Insert a research goal and return its id."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO research_goals "
                "(goal, priority, created_by, target_roles, deadline_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (goal, priority, created_by, target_roles, deadline_at),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_active_research_goals(self) -> list[dict]:
        """Return all active research goals."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM research_goals WHERE status = 'active' "
                "ORDER BY priority ASC, created_at DESC",
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchSchema -v`
Expected: all 4 PASS.

- [ ] **Step 6: Add DB helper tests**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchDBHelpers:
    """Verify the insert/claim/complete/find round-trip."""

    def test_insert_and_claim_task(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        task_id = db.insert_research_task(
            role="tech_watcher", priority=3, ticker="NVDA",
        )
        assert task_id > 0

        claimed = db.claim_research_task("w-001")
        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["role"] == "tech_watcher"
        assert claimed["ticker"] == "NVDA"

        # Queue is now empty.
        assert db.claim_research_task("w-002") is None

    def test_complete_task(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        task_id = db.insert_research_task(role="grok_miner")
        db.claim_research_task("w-001")
        db.complete_research_task(task_id)

        with sqlite3.connect(db.db_path) as conn:
            row = conn.execute(
                "SELECT status FROM research_tasks WHERE id = ?", (task_id,),
            ).fetchone()
        assert row[0] == "completed"

    def test_save_and_get_findings(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        fid = db.save_research_finding({
            "role": "reddit_scanner",
            "ticker": "GME",
            "finding_type": "sentiment",
            "headline": "WSB extremely bullish on GME",
            "confidence_pct": 78,
            "source": "reddit",
        })
        assert fid > 0

        results = db.get_research_findings(since_minutes=60, min_confidence=50)
        assert len(results) == 1
        assert results[0]["ticker"] == "GME"
        assert results[0]["confidence_pct"] == 78

    def test_priority_ordering(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        db.insert_research_task(role="slow", priority=8)
        db.insert_research_task(role="fast", priority=2)
        db.insert_research_task(role="mid", priority=5)

        claimed = db.claim_research_task("w-001")
        assert claimed is not None
        assert claimed["role"] == "fast"  # priority 2 first

    def test_insert_and_get_goals(self, tmp_path: Path) -> None:
        from database import HistoryManager

        db = HistoryManager(str(tmp_path / "test.db"))
        gid = db.insert_research_goal(
            goal="Analyse biotech sector before market open",
            priority=3,
            target_roles='["healthcare_watcher", "sector_analyst_health"]',
        )
        assert gid > 0
        goals = db.get_active_research_goals()
        assert len(goals) == 1
        assert goals[0]["goal"] == "Analyse biotech sector before market open"
```

- [ ] **Step 7: Run full test suite**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add core/database.py tests/test_research_swarm.py
git commit -m "feat(swarm): add research_tasks, research_findings, research_goals tables + helpers"
```

---

## Task 2: Research Roles — 20 Role Definitions

**Files:**
- Create: `core/agent/research_roles.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchRoles:
    def test_exactly_20_roles(self) -> None:
        from core.agent.research_roles import ALL_ROLES
        assert len(ALL_ROLES) == 20

    def test_10_quick_10_deep(self) -> None:
        from core.agent.research_roles import ALL_ROLES
        quick = [r for r in ALL_ROLES if r.tier == "quick"]
        deep = [r for r in ALL_ROLES if r.tier == "deep"]
        assert len(quick) == 10
        assert len(deep) == 10

    def test_unique_role_ids(self) -> None:
        from core.agent.research_roles import ALL_ROLES
        ids = [r.role_id for r in ALL_ROLES]
        assert len(ids) == len(set(ids))

    def test_role_has_required_fields(self) -> None:
        from core.agent.research_roles import ALL_ROLES
        for r in ALL_ROLES:
            assert r.role_id, f"missing role_id: {r}"
            assert r.tier in ("quick", "deep"), f"bad tier: {r.tier}"
            assert r.model_tier in ("simple", "medium", "complex")
            assert r.cadence_seconds > 0
            assert r.focus, f"missing focus: {r.role_id}"

    def test_get_role_by_id(self) -> None:
        from core.agent.research_roles import get_role
        role = get_role("grok_miner")
        assert role is not None
        assert role.tier == "quick"

        missing = get_role("nonexistent_role")
        assert missing is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchRoles -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create research_roles.py**

Create `core/agent/research_roles.py`:

```python
"""Research swarm role definitions.

Each role describes a specialised research agent: what it focuses on,
how often it fires, and which model tier it uses. The SwarmCoordinator
rotates all 20 roles through a bounded worker pool.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ResearchRole:
    """One research agent specialisation."""

    role_id: str
    tier: str                # "quick" or "deep"
    model_tier: str          # "simple" (Haiku), "medium" (Sonnet), "complex" (Opus)
    cadence_seconds: int     # how often this role should fire
    focus: str               # one-line description for the system prompt
    default_tickers: bool    # True = uses watchlist tickers; False = broad market


# ── Tier 1: Quick-Reaction Squad (10 roles) ──────────────────────────

_QUICK_ROLES: List[ResearchRole] = [
    ResearchRole(
        role_id="tech_watcher",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Tech sector breaking news and price spikes. Monitor FAANG, semis, AI plays.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="healthcare_watcher",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Healthcare and biotech: FDA decisions, trial results, drug approvals.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="energy_watcher",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Energy sector, oil prices, renewables, geopolitical supply disruptions.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="finance_watcher",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Banks, interest rate signals, Fed commentary, financial sector moves.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="consumer_watcher",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Consumer and retail: earnings surprises, sentiment shifts, spending data.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="reddit_scanner",
        tier="quick", model_tier="simple", cadence_seconds=150,
        focus="Reddit WSB, r/stocks, r/investing: hot threads, unusual volume of mentions.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="stocktwits_scanner",
        tier="quick", model_tier="simple", cadence_seconds=150,
        focus="StockTwits trending tickers, sentiment ratio, message velocity spikes.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="grok_miner",
        tier="quick", model_tier="simple", cadence_seconds=180,
        focus="X/Twitter intelligence via Grok AI: social buzz, rumours, retail sentiment.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="news_scanner",
        tier="quick", model_tier="simple", cadence_seconds=120,
        focus="Breaking news from Google News, BBC, MarketWatch: earnings, M&A, guidance.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="earnings_watcher",
        tier="quick", model_tier="simple", cadence_seconds=180,
        focus="Earnings calendar: pre-market and after-hours movers, beats vs misses.",
        default_tickers=False,
    ),
]

# ── Tier 2: Deep Research Squad (10 roles) ────────────────────────────

_DEEP_ROLES: List[ResearchRole] = [
    ResearchRole(
        role_id="sector_analyst_tech",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Deep tech sector analysis: competitive dynamics, product cycles, capex trends.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="sector_analyst_health",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Biotech pipeline analysis, regulatory landscape, patent cliffs.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="sector_analyst_industrial",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Industrials, commodities, supply chain disruptions, infrastructure spending.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="macro_researcher",
        tier="deep", model_tier="medium", cadence_seconds=900,
        focus="Macro research: interest rates, inflation, GDP, central bank policy shifts.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="geopolitical_researcher",
        tier="deep", model_tier="medium", cadence_seconds=900,
        focus="Geopolitical risk: trade wars, sanctions, political instability, tariffs.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="sentiment_aggregator_social",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Cross-platform sentiment synthesis: aggregate Reddit + StockTwits + X signals.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="sentiment_aggregator_news",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="News sentiment trends: detect shifts across BBC, MarketWatch, Google News.",
        default_tickers=True,
    ),
    ResearchRole(
        role_id="contrarian_hunter",
        tier="deep", model_tier="medium", cadence_seconds=900,
        focus="Find where crowd consensus is wrong: overcrowded shorts, contrarian setups.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="catalyst_scanner",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Upcoming catalysts: earnings dates, FDA dates, stock splits, buyback programmes.",
        default_tickers=False,
    ),
    ResearchRole(
        role_id="technical_researcher",
        tier="deep", model_tier="medium", cadence_seconds=600,
        focus="Chart patterns, support/resistance, volume analysis, breakout candidates.",
        default_tickers=True,
    ),
]


ALL_ROLES: List[ResearchRole] = _QUICK_ROLES + _DEEP_ROLES

_ROLES_BY_ID: Dict[str, ResearchRole] = {r.role_id: r for r in ALL_ROLES}


def get_role(role_id: str) -> Optional[ResearchRole]:
    """Look up a role by its id, or return None."""
    return _ROLES_BY_ID.get(role_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchRoles -v`
Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/research_roles.py tests/test_research_swarm.py
git commit -m "feat(swarm): define 20 research roles (10 quick, 10 deep)"
```

---

## Task 3: Model Router — Research Worker Routing

**Files:**
- Modify: `core/agent/model_router.py` (append after `chat_worker_model`)
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchModelRouter:
    def test_quick_role_gets_haiku(self) -> None:
        from core.agent.model_router import research_worker_model
        from core.agent.research_roles import get_role

        config = {"ai": {
            "model_simple": "Y2xhdWRlLWhhaWt1LTQtNS0yMDI1MTAwMQ==",
            "model_medium": "Y2xhdWRlLXNvbm5ldC00LTIwMjUwNTE0",
        }}
        role = get_role("tech_watcher")
        model_id = research_worker_model(config, role)
        assert "haiku" in model_id

    def test_deep_role_gets_sonnet(self) -> None:
        from core.agent.model_router import research_worker_model
        from core.agent.research_roles import get_role

        config = {"ai": {
            "model_simple": "Y2xhdWRlLWhhaWt1LTQtNS0yMDI1MTAwMQ==",
            "model_medium": "Y2xhdWRlLXNvbm5ldC00LTIwMjUwNTE0",
        }}
        role = get_role("macro_researcher")
        model_id = research_worker_model(config, role)
        assert "sonnet" in model_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchModelRouter -v`
Expected: FAIL — `research_worker_model` not defined.

- [ ] **Step 3: Add research_worker_model to model_router.py**

In `core/agent/model_router.py`, append after the `chat_worker_model` function (line 151):

```python
def _haiku_model(config: Dict[str, Any]) -> str:
    return _model(_ai_cfg(config), "model_simple")


def research_worker_model(config: Dict[str, Any], role: Any) -> str:
    """Pick the right model for a research worker based on role tier.

    Quick-reaction roles (tier 1) use Haiku for throughput.
    Deep-research roles (tier 2) use Sonnet for analytical depth.
    """
    tier = getattr(role, "model_tier", "simple")
    if tier == "complex":
        return _opus_model(config)
    if tier == "medium":
        return _sonnet_model(config)
    return _haiku_model(config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchModelRouter -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/model_router.py tests/test_research_swarm.py
git commit -m "feat(swarm): add research_worker_model to model router"
```

---

## Task 4: Research Tools — submit_finding, get_findings, set_research_goal, get_swarm_status

**Files:**
- Create: `core/agent/tools/research_tools.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
import asyncio
import json
from unittest.mock import MagicMock


def _run(coro):
    """Invoke an async tool handler and unwrap the JSON text payload."""
    result = asyncio.run(coro)
    return json.loads(result["content"][0]["text"])


class TestResearchTools:
    def test_submit_finding_writes_to_db(self, tmp_path: Path) -> None:
        from database import HistoryManager
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context
        from core.agent.tools.research_tools import submit_finding

        db = HistoryManager(str(tmp_path / "test.db"))
        config = {"broker": {"type": "log"}, "agent": {"paper_mode": True}}
        broker = MagicMock(spec=BrokerService)
        risk = RiskManager(config=config)
        init_agent_context(
            config=config, broker_service=broker, db=db,
            risk_manager=risk, iteration_id="test-001", paper_mode=True,
        )
        try:
            payload = _run(submit_finding.handler({
                "ticker": "NVDA",
                "finding_type": "alert",
                "headline": "NVDA breaking out on volume",
                "confidence_pct": 85,
                "source": "news_scanner",
                "detail": "Large buy blocks appearing",
            }))
            assert payload["status"] == "saved"
            assert payload["finding_id"] > 0

            findings = db.get_research_findings(since_minutes=60)
            assert len(findings) == 1
            assert findings[0]["ticker"] == "NVDA"
        finally:
            clear_agent_context()

    def test_get_findings_reads_from_db(self, tmp_path: Path) -> None:
        from database import HistoryManager
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context
        from core.agent.tools.research_tools import get_findings

        db = HistoryManager(str(tmp_path / "test.db"))
        config = {"broker": {"type": "log"}, "agent": {"paper_mode": True}}
        broker = MagicMock(spec=BrokerService)
        risk = RiskManager(config=config)

        db.save_research_finding({
            "role": "tech_watcher",
            "ticker": "TSLA",
            "finding_type": "sentiment",
            "headline": "TSLA buzz spike on StockTwits",
            "confidence_pct": 72,
            "source": "stocktwits",
        })

        init_agent_context(
            config=config, broker_service=broker, db=db,
            risk_manager=risk, iteration_id="test-002", paper_mode=True,
        )
        try:
            payload = _run(get_findings.handler({
                "since_minutes": 60,
                "min_confidence": 50,
            }))
            assert payload["count"] == 1
            assert payload["findings"][0]["ticker"] == "TSLA"
        finally:
            clear_agent_context()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchTools -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create research_tools.py**

Create `core/agent/tools/research_tools.py`:

```python
"""Research swarm tools — structured finding submission and retrieval.

These tools let research agents write findings to the database and let
the supervisor (or any agent) read aggregated intelligence.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.agent._sdk import tool
from core.agent.context import get_agent_context


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


@tool(
    "submit_finding",
    "Submit a structured research finding. Every finding needs a "
    "finding_type (alert, sentiment, catalyst, thesis, pattern), a "
    "headline, and a confidence_pct (0-100). The supervisor reads "
    "these to inform trade decisions.",
    {
        "ticker": str,
        "finding_type": str,
        "headline": str,
        "confidence_pct": int,
        "source": str,
        "detail": str,
        "methodology": str,
        "evidence": str,
    },
)
async def submit_finding(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    headline = str(args.get("headline", "")).strip()
    finding_type = str(args.get("finding_type", "alert")).strip()
    if not headline:
        return _text_result({"status": "rejected", "reason": "headline required"})

    valid_types = {"alert", "sentiment", "catalyst", "thesis", "pattern"}
    if finding_type not in valid_types:
        return _text_result({
            "status": "rejected",
            "reason": f"finding_type must be one of {valid_types}",
        })

    confidence = max(0, min(100, int(args.get("confidence_pct", 50) or 50)))

    # The role is stored on the context by the research worker.
    role = ctx.stats.get("research_role", "unknown")

    finding_id = ctx.db.save_research_finding({
        "task_id": ctx.stats.get("research_task_id"),
        "role": role,
        "ticker": (str(args.get("ticker", "")).strip().upper() or None),
        "finding_type": finding_type,
        "headline": headline,
        "detail": str(args.get("detail", "") or ""),
        "confidence_pct": confidence,
        "source": str(args.get("source", "") or ""),
        "methodology": str(args.get("methodology", "") or ""),
        "evidence_json": str(args.get("evidence", "") or ""),
    })

    return _text_result({
        "status": "saved",
        "finding_id": finding_id,
        "finding_type": finding_type,
        "confidence_pct": confidence,
    })


@tool(
    "get_findings",
    "Read recent research findings from the swarm. Filter by "
    "since_minutes, min_confidence, ticker, or finding_type. "
    "Returns findings sorted by confidence (highest first).",
    {
        "since_minutes": int,
        "min_confidence": int,
        "ticker": str,
        "finding_type": str,
        "limit": int,
    },
)
async def get_findings(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    since = int(args.get("since_minutes", 360) or 360)
    conf = int(args.get("min_confidence", 0) or 0)
    ticker = str(args.get("ticker", "") or "").strip().upper() or None
    ftype = str(args.get("finding_type", "") or "").strip() or None
    limit = int(args.get("limit", 30) or 30)

    rows = ctx.db.get_research_findings(
        since_minutes=since,
        min_confidence=conf,
        ticker=ticker,
        finding_type=ftype,
        limit=limit,
    )

    return _text_result({
        "count": len(rows),
        "since_minutes": since,
        "min_confidence": conf,
        "findings": rows,
    })


@tool(
    "set_research_goal",
    "Direct the research swarm to focus on a specific goal. "
    "The swarm coordinator will prioritise tasks that serve this goal. "
    "Provide the goal text and optionally a list of target roles.",
    {
        "goal": str,
        "priority": int,
        "target_roles": str,
        "deadline_minutes": int,
    },
)
async def set_research_goal(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()
    goal_text = str(args.get("goal", "")).strip()
    if not goal_text:
        return _text_result({"status": "rejected", "reason": "goal text required"})

    priority = max(1, min(10, int(args.get("priority", 5) or 5)))
    target_roles = str(args.get("target_roles", "") or "")
    deadline_min = int(args.get("deadline_minutes", 0) or 0)
    deadline_at = None
    if deadline_min > 0:
        deadline_at = f"+{deadline_min} minutes"

    goal_id = ctx.db.insert_research_goal(
        goal=goal_text,
        priority=priority,
        created_by="supervisor",
        target_roles=target_roles or None,
        deadline_at=deadline_at,
    )

    return _text_result({
        "status": "created",
        "goal_id": goal_id,
        "goal": goal_text,
        "priority": priority,
    })


@tool(
    "get_swarm_status",
    "Return the current state of the research swarm: task queue stats, "
    "active goals, and recent high-confidence findings.",
    {},
)
async def get_swarm_status(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    task_stats = ctx.db.get_research_task_stats()
    goals = ctx.db.get_active_research_goals()
    top_findings = ctx.db.get_research_findings(
        since_minutes=120, min_confidence=60, limit=10,
    )

    return _text_result({
        "task_queue": task_stats,
        "active_goals": goals,
        "top_findings_last_2h": top_findings,
    })


RESEARCH_TOOLS = [submit_finding, get_findings, set_research_goal, get_swarm_status]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchTools -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/tools/research_tools.py tests/test_research_swarm.py
git commit -m "feat(swarm): add research tools — submit_finding, get_findings, set_research_goal, get_swarm_status"
```

---

## Task 5: Grok Tools — Playwright-based X/Twitter Intelligence

**Files:**
- Create: `core/agent/tools/grok_tools.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test (mocked Playwright)**

Append to `tests/test_research_swarm.py`:

```python
from unittest.mock import AsyncMock, patch, MagicMock as SyncMock


class TestGrokTools:
    def test_query_grok_returns_response(self, tmp_path: Path) -> None:
        """Test query_grok with a mocked Playwright browser."""
        from database import HistoryManager
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context
        from core.agent.tools.grok_tools import query_grok

        db = HistoryManager(str(tmp_path / "test.db"))
        config = {
            "broker": {"type": "log"},
            "agent": {"paper_mode": True},
            "swarm": {"grok_session_path": str(tmp_path / "grok_session")},
        }
        broker = SyncMock(spec=BrokerService)
        risk = RiskManager(config=config)
        init_agent_context(
            config=config, broker_service=broker, db=db,
            risk_manager=risk, iteration_id="test-grok", paper_mode=True,
        )

        # Mock the entire _run_grok_query helper to avoid real browser.
        with patch(
            "core.agent.tools.grok_tools._run_grok_query",
            new_callable=AsyncMock,
            return_value="NVDA is trending on X with extremely bullish sentiment",
        ):
            payload = _run(query_grok.handler({
                "query": "What is X saying about NVDA?",
                "timeout": 30,
            }))

        assert payload["status"] == "ok"
        assert "NVDA" in payload["response"]
        assert payload["source"] == "grok_x"
        clear_agent_context()

    def test_query_grok_handles_error(self, tmp_path: Path) -> None:
        from database import HistoryManager
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context
        from core.agent.tools.grok_tools import query_grok

        db = HistoryManager(str(tmp_path / "test.db"))
        config = {
            "broker": {"type": "log"},
            "agent": {"paper_mode": True},
            "swarm": {"grok_session_path": str(tmp_path / "grok_session")},
        }
        broker = SyncMock(spec=BrokerService)
        risk = RiskManager(config=config)
        init_agent_context(
            config=config, broker_service=broker, db=db,
            risk_manager=risk, iteration_id="test-grok-err", paper_mode=True,
        )

        with patch(
            "core.agent.tools.grok_tools._run_grok_query",
            new_callable=AsyncMock,
            side_effect=TimeoutError("browser timed out"),
        ):
            payload = _run(query_grok.handler({
                "query": "trending stocks on X",
                "timeout": 10,
            }))

        assert payload["status"] == "error"
        assert "timed out" in payload["error"]
        clear_agent_context()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestGrokTools -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create grok_tools.py**

Create `core/agent/tools/grok_tools.py`:

```python
"""Grok AI tools — Playwright-based X/Twitter intelligence.

Research agents use these tools to ask Grok AI (grok.x.ai) about what's
happening on X/Twitter. Grok has native access to X data, making it the
best proxy for social media intelligence without needing an X API key.

The browser automation flow:
1. Launch headless Chromium
2. Navigate to grok.x.ai
3. Type the research query
4. Wait for Grok's streaming response to complete
5. Extract the response text
6. Return it as a structured result

Session cookies are persisted so auth survives across calls within the
same worker. If auth expires, the tool returns a graceful error and the
agent continues with its other tools.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from core.agent._sdk import tool
from core.agent.context import get_agent_context

logger = logging.getLogger(__name__)

#: Hard cap on Grok queries per iteration to prevent runaway browser use.
MAX_GROK_QUERIES_PER_ITER: int = 3

#: Default timeout for a Grok query (seconds).
DEFAULT_TIMEOUT: int = 60


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


async def _run_grok_query(
    query_text: str,
    session_path: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Launch headless Chromium, send a query to Grok, return the response.

    This is the core browser automation. Separated from the tool handler
    so tests can mock it without touching Playwright.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "playwright is not installed — run: pip install playwright && "
            "playwright install chromium"
        )

    session_dir = Path(session_path)
    session_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()

        try:
            await page.goto("https://grok.x.ai", wait_until="domcontentloaded",
                            timeout=timeout * 1000)

            # Wait for the input area to appear.
            input_sel = 'textarea, [contenteditable="true"], input[type="text"]'
            await page.wait_for_selector(input_sel, timeout=15000)

            # Type the query.
            input_el = await page.query_selector(input_sel)
            if input_el is None:
                raise RuntimeError("Could not find Grok input field")

            await input_el.click()
            await input_el.fill(query_text)

            # Submit — try Enter key.
            await page.keyboard.press("Enter")

            # Wait for the response to appear and stabilise.
            # Grok streams its response; we wait until the content stops
            # changing for 2 seconds.
            import asyncio

            last_text = ""
            stable_count = 0
            for _ in range(timeout * 2):  # check every 0.5s
                await asyncio.sleep(0.5)

                # Try multiple selectors for the response container.
                response_el = await page.query_selector(
                    '[class*="response"], [class*="message"], '
                    '[class*="answer"], [data-testid*="response"]'
                )
                if response_el is None:
                    # Broader fallback: look for the last large text block.
                    elements = await page.query_selector_all("div, p, section")
                    best = None
                    best_len = 0
                    for el in elements[-20:]:
                        txt = (await el.inner_text() or "").strip()
                        if len(txt) > best_len and len(txt) > 50:
                            best = el
                            best_len = len(txt)
                    response_el = best

                if response_el is None:
                    continue

                current_text = (await response_el.inner_text() or "").strip()
                if current_text and current_text == last_text:
                    stable_count += 1
                    if stable_count >= 4:  # 2 seconds of stability
                        break
                else:
                    stable_count = 0
                    last_text = current_text

            if not last_text:
                raise RuntimeError("Grok returned no response text")

            return last_text

        finally:
            await browser.close()


@tool(
    "query_grok",
    "Ask Grok AI on X (grok.x.ai) a research question. Grok has native "
    "access to X/Twitter data and can summarise social sentiment, find "
    "trending tickers, surface rumours, and analyse what retail traders "
    "are discussing. Hard cap: 3 queries per iteration. Timeout default: "
    "60 seconds.",
    {"query": str, "timeout": int},
)
async def query_grok(args: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_agent_context()

    # Rate limit.
    count = int(ctx.stats.get("grok_queries", 0))
    if count >= MAX_GROK_QUERIES_PER_ITER:
        return _text_result({
            "status": "rate_limited",
            "error": f"Grok query limit reached ({count}/{MAX_GROK_QUERIES_PER_ITER})",
            "queries_used": count,
        })

    query_text = str(args.get("query", "")).strip()
    if not query_text:
        return _text_result({"status": "error", "error": "query is required"})

    timeout = int(args.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
    timeout = max(10, min(120, timeout))

    session_path = (
        ctx.config.get("swarm", {}).get("grok_session_path")
        or "data/grok_session"
    )

    ctx.stats["grok_queries"] = count + 1

    try:
        response = await _run_grok_query(
            query_text=query_text,
            session_path=session_path,
            timeout=timeout,
        )
    except TimeoutError as exc:
        return _text_result({
            "status": "error",
            "error": f"Grok query timed out: {exc}",
            "query": query_text,
            "queries_used": count + 1,
        })
    except Exception as exc:
        logger.exception("Grok query failed")
        return _text_result({
            "status": "error",
            "error": f"Grok query failed: {exc}",
            "query": query_text,
            "queries_used": count + 1,
        })

    return _text_result({
        "status": "ok",
        "response": response,
        "source": "grok_x",
        "query": query_text,
        "queries_used": count + 1,
        "queries_remaining": MAX_GROK_QUERIES_PER_ITER - (count + 1),
    })


GROK_TOOLS = [query_grok]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestGrokTools -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/tools/grok_tools.py tests/test_research_swarm.py
git commit -m "feat(swarm): add Playwright-based Grok AI tool for X/Twitter intelligence"
```

---

## Task 6: Research Prompts — Per-Role System Prompts

**Files:**
- Create: `core/agent/prompts_research.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchPrompts:
    def test_render_includes_role_focus(self) -> None:
        from core.agent.prompts_research import render_research_prompt
        from core.agent.research_roles import get_role

        role = get_role("grok_miner")
        config = {"agent": {"paper_mode": True}, "paper_broker": {"currency": "GBP"}}
        prompt = render_research_prompt(config, role, watchlist=["NVDA", "TSLA"])

        assert "grok_miner" in prompt
        assert "X/Twitter intelligence" in prompt
        assert "submit_finding" in prompt
        assert "NVDA" in prompt
        assert "TSLA" in prompt

    def test_render_quick_vs_deep_instructions(self) -> None:
        from core.agent.prompts_research import render_research_prompt
        from core.agent.research_roles import get_role

        quick_role = get_role("tech_watcher")
        deep_role = get_role("macro_researcher")
        config = {"agent": {"paper_mode": True}, "paper_broker": {"currency": "GBP"}}

        quick_prompt = render_research_prompt(config, quick_role)
        deep_prompt = render_research_prompt(config, deep_role)

        assert "quick" in quick_prompt.lower()
        assert "deep" in deep_prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchPrompts -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create prompts_research.py**

Create `core/agent/prompts_research.py`:

```python
"""System prompts for research swarm agents.

Each research worker gets a prompt tailored to its role: what to focus
on, which tools to prefer, and how to submit findings. Research agents
never have trading tools — they observe and report.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


RESEARCH_PROMPT_TEMPLATE: str = """\
You are a **research agent** inside **blank** by Certified Random — a
trading terminal's research swarm. You are role **{role_id}** in the
{tier_label} tier.

## Your focus

{focus}

## How you work

You are a {tier_desc} researcher. {pace_instruction}

Your job is to find actionable intelligence and submit it as structured
findings using `submit_finding`. Every finding needs:
- **finding_type**: one of alert, sentiment, catalyst, thesis, pattern
- **headline**: one clear sentence summarising the finding
- **confidence_pct**: 0-100, how confident you are
- **ticker**: the symbol if applicable (or leave blank for broad market)
- **source**: where you found this (reddit, stocktwits, grok_x, news, etc.)
- **detail**: supporting context (optional but encouraged)
- **methodology**: how you reached this conclusion (optional)

## Tools you have

**News + social** — `get_news`, `get_social_buzz`, `get_market_buzz`,
`get_scraper_health`. These read from the 24/7 scraper cache.

**Research browser** — `fetch_page(url)` for reading articles, filings,
press releases. Cap: 10 per iteration.

**Grok AI on X** — `query_grok(query)` asks Grok AI to mine X/Twitter.
Use this for social sentiment, trending topics, retail trader buzz, and
rumours that don't surface in traditional news. Cap: 3 per iteration.

**Market data** — `get_live_price`, `get_daily_bars`, `get_intraday_bars`,
`search_instrument` for price context and chart analysis.

**Findings** — `submit_finding` to report what you found,
`get_findings` to read what other researchers found (avoid duplicating).

**Memory** — `read_memory`, `write_memory` for your scratchpad.

**Flow** — `end_iteration` to close your turn.

You do NOT have trading tools. You observe and report — the supervisor
decides what to trade.

## Current context

{watchlist_block}

## Standing rules

1. **Submit findings, don't hoard them.** Every useful observation should
   be a `submit_finding` call, not just text in your response.
2. **Check `get_findings` before submitting.** Don't duplicate what
   another researcher already found this hour.
3. **Confidence matters.** A 90% confidence finding drives a trade. A
   30% finding is noise. Be honest about your certainty.
4. **Go on tangents.** If you spot something interesting that's outside
   your primary focus, follow it. Serendipity is valuable.
5. **End cleanly.** Call `end_iteration` with a summary when you're done.
"""


_TIER_LABELS = {
    "quick": "quick-reaction",
    "deep": "deep-research",
}

_TIER_DESCS = {
    "quick": "fast-cycling, quick-reaction",
    "deep": "thorough, deep-analysis",
}

_PACE_INSTRUCTIONS = {
    "quick": (
        "You cycle fast — 2-5 minutes per task. Scan, spot, report. "
        "Don't overthink. If something looks interesting, submit a finding "
        "and move on. The deep-research tier will follow up on your leads."
    ),
    "deep": (
        "You take your time — 15-60 minutes per task. Go deep. Read "
        "multiple sources. Cross-reference. Build a thesis with supporting "
        "evidence. Your findings should be thorough enough for the "
        "supervisor to make a trade decision on."
    ),
}


def render_research_prompt(
    config: Dict[str, Any],
    role: Any,
    watchlist: Optional[List[str]] = None,
) -> str:
    """Build the system prompt for a research worker."""
    tier = getattr(role, "tier", "quick")

    if watchlist:
        watchlist_block = f"Active watchlist: {', '.join(watchlist)}"
    else:
        watchlist_block = "No active watchlist — scan the broad market."

    return RESEARCH_PROMPT_TEMPLATE.format(
        role_id=role.role_id,
        tier_label=_TIER_LABELS.get(tier, tier),
        tier_desc=_TIER_DESCS.get(tier, tier),
        pace_instruction=_PACE_INSTRUCTIONS.get(tier, ""),
        focus=role.focus,
        watchlist_block=watchlist_block,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchPrompts -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/prompts_research.py tests/test_research_swarm.py
git commit -m "feat(swarm): add per-role research system prompts"
```

---

## Task 7: Register New Tools in MCP Server

**Files:**
- Modify: `core/agent/mcp_server.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestMCPRegistration:
    def test_research_tools_registered(self) -> None:
        from core.agent.mcp_server import ALL_TOOLS
        names = {getattr(t, "name", "") for t in ALL_TOOLS}
        assert "submit_finding" in names
        assert "get_findings" in names
        assert "set_research_goal" in names
        assert "get_swarm_status" in names

    def test_grok_tools_registered(self) -> None:
        from core.agent.mcp_server import ALL_TOOLS
        names = {getattr(t, "name", "") for t in ALL_TOOLS}
        assert "query_grok" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestMCPRegistration -v`
Expected: FAIL — tools not in ALL_TOOLS yet.

- [ ] **Step 3: Add imports and register in mcp_server.py**

In `core/agent/mcp_server.py`, add these imports after the existing tool imports (after line 28):

```python
from core.agent.tools.research_tools import RESEARCH_TOOLS
from core.agent.tools.grok_tools import GROK_TOOLS
```

Then add `*RESEARCH_TOOLS, *GROK_TOOLS,` to the `ALL_TOOLS` list, before `*FLOW_TOOLS`:

```python
ALL_TOOLS: List[Any] = [
    *BROKER_TOOLS,
    *MARKET_TOOLS,
    *MARKET_HOURS_TOOLS,
    *RISK_TOOLS,
    *MEMORY_TOOLS,
    *WATCHLIST_TOOLS,
    *NEWS_TOOLS,
    *SOCIAL_TOOLS,
    *BROWSER_TOOLS,
    *BACKTEST_TOOLS,
    *RESEARCH_TOOLS,
    *GROK_TOOLS,
    *FLOW_TOOLS,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestMCPRegistration -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/mcp_server.py tests/test_research_swarm.py
git commit -m "feat(swarm): register research + grok tools in MCP server"
```

---

## Task 8: Research Worker — QThread Per Task

**Files:**
- Create: `core/agent/research_worker.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchWorker:
    def test_worker_constructs(self, tmp_path: Path) -> None:
        from core.agent.research_worker import ResearchWorker
        from core.agent.research_roles import get_role

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "agent": {"paper_mode": True},
            "ai": {"model_simple": "Y2xhdWRlLWhhaWt1LTQtNS0yMDI1MTAwMQ=="},
            "swarm": {},
        }))

        role = get_role("tech_watcher")
        task = {"id": 1, "role": "tech_watcher", "ticker": "NVDA",
                "parameters": None, "goal_id": None, "priority": 3}
        broker = SyncMock()

        worker = ResearchWorker(
            worker_id="rw-001",
            task=task,
            role=role,
            config_path=config_path,
            broker_service=broker,
            db_path=str(tmp_path / "test.db"),
            paper_mode=True,
        )
        assert worker.worker_id == "rw-001"
        assert worker._role.role_id == "tech_watcher"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchWorker -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create research_worker.py**

Create `core/agent/research_worker.py`:

```python
"""ResearchWorker — QThread that runs one research task.

Like ChatWorker but for autonomous research. Each worker:
1. Claims a task from the queue
2. Sets up AgentContext with research role metadata
3. Runs a claude-agent-sdk query with the role's system prompt
4. Streams until end_iteration
5. Marks the task complete and exits

Research workers share the same broker, DB, and tool bus as the
supervisor and chat workers. They write to research_findings via
the submit_finding tool.
"""
from __future__ import annotations

from . import subprocess_patch  # noqa: F401

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class ResearchWorker(QThread):
    """Runs a single research task via the claude-agent-sdk."""

    # ── signals ──────────────────────────────────────────────────────
    log_line = Signal(str)
    finding_submitted = Signal(dict)  # {role, ticker, headline, confidence}
    worker_done = Signal(str, str)    # worker_id, summary
    worker_error = Signal(str, str)   # worker_id, error

    def __init__(
        self,
        worker_id: str,
        task: Dict[str, Any],
        role: Any,
        config_path: Path | str,
        broker_service: Any,
        db_path: str,
        paper_mode: bool,
        watchlist: Optional[List[str]] = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._worker_id = worker_id
        self._task = task
        self._role = role
        self._config_path = Path(config_path)
        self._broker_service = broker_service
        self._db_path = db_path
        self._paper_mode = paper_mode
        self._watchlist = watchlist or []
        self._stop_requested: bool = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def request_stop(self) -> None:
        self._stop_requested = True

    # ── QThread entry ────────────────────────────────────────────────

    def run(self) -> None:
        role_id = self._role.role_id
        task_id = self._task.get("id", "?")
        self.log_line.emit(
            f"[swarm:{role_id}] worker {self._worker_id} started (task {task_id})"
        )
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_research())
        except Exception as e:
            logger.exception("Research worker %s crashed", self._worker_id)
            self.worker_error.emit(self._worker_id, f"research worker crashed: {e}")
        finally:
            if loop is not None:
                try:
                    loop.close()
                except Exception:
                    pass
            self.log_line.emit(
                f"[swarm:{role_id}] worker {self._worker_id} stopped"
            )

    async def _run_research(self) -> None:
        from core.agent._sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
        from database import HistoryManager
        from risk_manager import RiskManager
        from core.agent.context import clear_agent_context, init_agent_context
        from core.agent.mcp_server import (
            SERVER_NAME,
            allowed_tool_names,
            build_mcp_server,
        )
        from core.agent.model_router import research_worker_model
        from core.agent.paths import cli_path_for_sdk, prepare_env_for_bundled_engine
        from core.agent.prompts_research import render_research_prompt

        config = self._load_config()
        effective_config = dict(config)
        effective_config.setdefault("agent", {})["paper_mode"] = self._paper_mode

        db = HistoryManager(self._db_path)
        risk = RiskManager(config=effective_config)

        role_id = self._role.role_id
        task_id = self._task.get("id")
        iteration_id = f"swarm-{role_id}-{uuid.uuid4().hex[:6]}"

        ctx = init_agent_context(
            config=effective_config,
            broker_service=self._broker_service,
            db=db,
            risk_manager=risk,
            iteration_id=iteration_id,
            paper_mode=self._paper_mode,
        )
        # Tag the context so submit_finding knows which role produced it.
        ctx.stats["research_role"] = role_id
        ctx.stats["research_task_id"] = task_id

        model_id = research_worker_model(effective_config, self._role)

        self.log_line.emit(
            f"[swarm:{role_id}] iteration {iteration_id} "
            f"(model={model_id}, task={task_id})"
        )

        mcp_server = build_mcp_server()
        prepare_env_for_bundled_engine()

        system_prompt = render_research_prompt(
            effective_config, self._role, watchlist=self._watchlist,
        )

        # Build the wake prompt with task context.
        ticker = self._task.get("ticker")
        params = self._task.get("parameters")
        wake_parts = [
            f"You are research role '{role_id}'. Wake up and start researching.",
        ]
        if ticker:
            wake_parts.append(f"Focus ticker: {ticker}")
        if params:
            wake_parts.append(f"Parameters: {params}")
        wake_parts.append(
            "Find what's interesting, submit findings, then end your turn."
        )
        wake_prompt = " ".join(wake_parts)

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            mcp_servers={SERVER_NAME: mcp_server},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",
            model=model_id,
            cwd=str(self._config_path.parent),
            cli_path=cli_path_for_sdk(),
        )

        start = time.monotonic()
        try:
            async for message in query(prompt=wake_prompt, options=options):
                if self._stop_requested:
                    self.log_line.emit(f"[swarm:{role_id}] stop requested")
                    break

                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            self.log_line.emit(f"[swarm:{role_id}] {block.text}")
                        elif isinstance(block, ToolUseBlock):
                            short = (block.name or "").rsplit("__", 1)[-1]
                            if short == "submit_finding":
                                inp = block.input or {}
                                self.finding_submitted.emit({
                                    "role": role_id,
                                    "ticker": inp.get("ticker", ""),
                                    "headline": inp.get("headline", ""),
                                    "confidence": inp.get("confidence_pct", 0),
                                })
                elif isinstance(message, ResultMessage):
                    self.log_line.emit(
                        f"[swarm:{role_id}] done "
                        f"turns={message.num_turns} "
                        f"duration={message.duration_ms}ms"
                    )
        except Exception as e:
            logger.exception("Research query failed for %s", role_id)
            self.worker_error.emit(self._worker_id, f"research query failed: {e}")
            db.complete_research_task(task_id, error=str(e))
        else:
            summary = ""
            try:
                from core.agent.context import get_agent_context
                summary = get_agent_context().end_summary or ""
            except Exception:
                pass
            db.complete_research_task(task_id)
            self.worker_done.emit(self._worker_id, summary)
            self.log_line.emit(
                f"[swarm:{role_id}] task {task_id} completed "
                f"({time.monotonic() - start:.1f}s)"
            )
        finally:
            clear_agent_context()

    def _load_config(self) -> Dict[str, Any]:
        with self._config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchWorker -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/research_worker.py tests/test_research_swarm.py
git commit -m "feat(swarm): add ResearchWorker QThread"
```

---

## Task 9: Research Queue — Priority Scheduling

**Files:**
- Create: `core/agent/research_queue.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestResearchQueue:
    def test_generate_due_tasks(self) -> None:
        from core.agent.research_queue import ResearchQueue
        from core.agent.research_roles import ALL_ROLES

        queue = ResearchQueue()

        # First call should generate tasks for all roles (nothing fired yet).
        due = queue.get_due_roles()
        assert len(due) == 20  # all roles due on first call

    def test_role_not_due_before_cadence(self) -> None:
        import time
        from core.agent.research_queue import ResearchQueue

        queue = ResearchQueue()
        queue.mark_fired("tech_watcher")

        # Immediately after firing, tech_watcher should not be due.
        due_ids = {r.role_id for r in queue.get_due_roles()}
        assert "tech_watcher" not in due_ids

    def test_priority_quick_over_deep(self) -> None:
        from core.agent.research_queue import ResearchQueue

        queue = ResearchQueue()
        prioritised = queue.get_due_roles()

        # Quick roles should come before deep roles.
        quick_indices = [
            i for i, r in enumerate(prioritised) if r.tier == "quick"
        ]
        deep_indices = [
            i for i, r in enumerate(prioritised) if r.tier == "deep"
        ]
        if quick_indices and deep_indices:
            assert max(quick_indices) < min(deep_indices)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchQueue -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create research_queue.py**

Create `core/agent/research_queue.py`:

```python
"""Research queue — priority scheduling for the swarm.

Tracks when each role last fired and decides which roles are due. Quick-
reaction roles get priority over deep-research roles. The
SwarmCoordinator reads from this queue on every tick.
"""
from __future__ import annotations

import time
from typing import Dict, List

from core.agent.research_roles import ALL_ROLES, ResearchRole


class ResearchQueue:
    """Cadence-based scheduler for 20 research roles."""

    def __init__(self) -> None:
        self._last_fired: Dict[str, float] = {}

    def mark_fired(self, role_id: str) -> None:
        """Record that a role just started running."""
        self._last_fired[role_id] = time.monotonic()

    def get_due_roles(self) -> List[ResearchRole]:
        """Return roles whose cadence has elapsed, quick-first."""
        now = time.monotonic()
        due: List[ResearchRole] = []
        for role in ALL_ROLES:
            last = self._last_fired.get(role.role_id)
            if last is None or (now - last) >= role.cadence_seconds:
                due.append(role)

        # Sort: quick roles first (priority), then by cadence (shorter = more urgent).
        due.sort(key=lambda r: (0 if r.tier == "quick" else 1, r.cadence_seconds))
        return due

    def reset(self) -> None:
        """Clear all fire times (used on restart)."""
        self._last_fired.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestResearchQueue -v`
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/research_queue.py tests/test_research_swarm.py
git commit -m "feat(swarm): add cadence-based priority research queue"
```

---

## Task 10: Swarm Coordinator — Main Orchestrator

**Files:**
- Create: `core/agent/swarm.py`
- Test: `tests/test_research_swarm.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research_swarm.py`:

```python
class TestSwarmCoordinator:
    def test_constructs(self, tmp_path: Path) -> None:
        from core.agent.swarm import SwarmCoordinator

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "agent": {"paper_mode": True},
            "ai": {"model_simple": "dGVzdA=="},
            "swarm": {"enabled": True, "max_concurrent_workers": 2},
        }))
        db_path = str(tmp_path / "test.db")
        broker = SyncMock()

        coord = SwarmCoordinator(
            config_path=config_path,
            broker_service=broker,
            db_path=db_path,
            paper_mode=True,
        )
        assert coord._max_workers == 2
        assert not coord.is_alive()

    def test_generate_tasks_for_due_roles(self, tmp_path: Path) -> None:
        from core.agent.swarm import SwarmCoordinator
        from database import HistoryManager

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "agent": {"paper_mode": True},
            "ai": {"model_simple": "dGVzdA=="},
            "swarm": {"enabled": True, "max_concurrent_workers": 2},
        }))
        db_path = str(tmp_path / "test.db")
        db = HistoryManager(db_path)
        broker = SyncMock()

        coord = SwarmCoordinator(
            config_path=config_path,
            broker_service=broker,
            db_path=db_path,
            paper_mode=True,
        )
        coord._generate_tasks(db)

        stats = db.get_research_task_stats()
        assert stats.get("pending", 0) == 20  # all 20 roles queued
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestSwarmCoordinator -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Create swarm.py**

Create `core/agent/swarm.py`:

```python
"""SwarmCoordinator — manages the 20-agent research worker pool.

Runs as a daemon thread alongside ScraperRunner. On every tick:
1. Check which roles are due to fire (based on cadence)
2. Generate tasks for due roles
3. Assign tasks to idle workers (priority order)
4. Collect completed worker results
5. Purge old findings
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from core.agent.research_queue import ResearchQueue
from core.agent.research_roles import ALL_ROLES, get_role

logger = logging.getLogger(__name__)

#: Tick interval for the coordinator loop.
TICK_SECONDS: float = 5.0

#: Default max concurrent research workers.
DEFAULT_MAX_WORKERS: int = 4

#: Retention window for old findings/tasks.
RETENTION_DAYS: int = 30


class SwarmCoordinator(threading.Thread):
    """Daemon thread that schedules and runs research workers."""

    def __init__(
        self,
        config_path: Path | str,
        broker_service: Any,
        db_path: str,
        paper_mode: bool,
        watchlist_provider: Optional[Callable[[], List[str]]] = None,
    ) -> None:
        super().__init__(daemon=True, name="swarm-coordinator")
        self._config_path = Path(config_path)
        self._broker_service = broker_service
        self._db_path = db_path
        self._paper_mode = paper_mode
        self._watchlist_provider = watchlist_provider or (lambda: [])

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._queue = ResearchQueue()

        # Active workers keyed by worker_id.
        self._workers: Dict[str, Any] = {}

        # Load config for worker cap.
        self._max_workers = self._read_max_workers()

        # Stats for introspection.
        self._total_tasks_run: int = 0
        self._total_findings: int = 0

    def _read_max_workers(self) -> int:
        try:
            with self._config_path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
            return int(
                cfg.get("swarm", {}).get(
                    "max_concurrent_workers", DEFAULT_MAX_WORKERS
                )
            )
        except Exception:
            return DEFAULT_MAX_WORKERS

    # ── lifecycle ────────────────────────────────────────────────────

    def run(self) -> None:
        logger.info(
            "[swarm] coordinator started (max_workers=%d, roles=%d)",
            self._max_workers, len(ALL_ROLES),
        )

        from core.database import HistoryManager
        db = HistoryManager(self._db_path)

        while not self._stop_event.is_set():
            try:
                self._tick(db)
            except Exception:
                logger.exception("[swarm] tick failed")

            self._stop_event.wait(timeout=TICK_SECONDS)

        # Graceful shutdown: wait for running workers.
        self._shutdown_workers()
        logger.info("[swarm] coordinator stopped")

    def stop(self) -> None:
        """Request the coordinator to exit."""
        self._stop_event.set()

    # ── one tick ─────────────────────────────────────────────────────

    def _tick(self, db: Any) -> None:
        # 1. Collect finished workers.
        self._collect_finished()

        # 2. Generate tasks for due roles.
        self._generate_tasks(db)

        # 3. Assign tasks to idle workers.
        self._assign_tasks(db)

        # 4. Periodic housekeeping (every ~5 minutes).
        if self._total_tasks_run % 60 == 0 and self._total_tasks_run > 0:
            try:
                db.purge_old_research_data(keep_days=RETENTION_DAYS)
            except Exception:
                logger.debug("[swarm] purge failed", exc_info=True)

    def _generate_tasks(self, db: Any) -> None:
        """Insert tasks for roles whose cadence has elapsed."""
        due_roles = self._queue.get_due_roles()
        for role in due_roles:
            # Don't duplicate: skip if there's already a pending task for this role.
            stats = db.get_research_task_stats()
            # Quick check: if queue is already large, skip generation.
            pending = stats.get("pending", 0)
            if pending > len(ALL_ROLES) * 2:
                break

            priority = 3 if role.tier == "quick" else 7
            ticker = None
            if role.default_tickers:
                tickers = self._watchlist_provider()
                if tickers:
                    ticker = ",".join(tickers[:10])

            db.insert_research_task(
                role=role.role_id,
                priority=priority,
                ticker=ticker,
            )
            self._queue.mark_fired(role.role_id)

    def _assign_tasks(self, db: Any) -> None:
        """Assign pending tasks to idle worker slots."""
        with self._lock:
            active = len(self._workers)
        slots = self._max_workers - active
        if slots <= 0:
            return

        for _ in range(slots):
            task = db.claim_research_task(worker_id=f"swarm-{self._total_tasks_run}")
            if task is None:
                break

            role = get_role(task["role"])
            if role is None:
                logger.warning("[swarm] unknown role %s, skipping", task["role"])
                db.complete_research_task(task["id"], error="unknown role")
                continue

            self._spawn_worker(task, role)

    def _spawn_worker(self, task: Dict[str, Any], role: Any) -> None:
        """Start a ResearchWorker QThread for one task."""
        from core.agent.research_worker import ResearchWorker

        import uuid
        worker_id = f"rw-{uuid.uuid4().hex[:6]}"
        watchlist = self._watchlist_provider()

        worker = ResearchWorker(
            worker_id=worker_id,
            task=task,
            role=role,
            config_path=self._config_path,
            broker_service=self._broker_service,
            db_path=self._db_path,
            paper_mode=self._paper_mode,
            watchlist=watchlist,
        )

        with self._lock:
            self._workers[worker_id] = worker

        self._total_tasks_run += 1
        worker.start()
        logger.info(
            "[swarm] spawned %s for role %s (task %s)",
            worker_id, role.role_id, task.get("id"),
        )

    def _collect_finished(self) -> None:
        """Remove workers that have finished their QThread."""
        with self._lock:
            finished = [
                wid for wid, w in self._workers.items()
                if not w.isRunning()
            ]
            for wid in finished:
                worker = self._workers.pop(wid)
                try:
                    worker.wait(50)
                except Exception:
                    pass
                try:
                    worker.deleteLater()
                except Exception:
                    pass

    def _shutdown_workers(self) -> None:
        """Stop all running workers (best-effort, max 30s)."""
        with self._lock:
            workers = list(self._workers.values())
        for w in workers:
            try:
                w.request_stop()
            except Exception:
                pass
        deadline = time.monotonic() + 30
        for w in workers:
            remaining = max(0, int((deadline - time.monotonic()) * 1000))
            try:
                w.wait(remaining)
            except Exception:
                pass

    # ── introspection ────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of the swarm state."""
        with self._lock:
            active_roles = [
                w._role.role_id for w in self._workers.values()
            ]
        return {
            "running": not self._stop_event.is_set(),
            "active_workers": len(active_roles),
            "active_roles": active_roles,
            "max_workers": self._max_workers,
            "total_tasks_run": self._total_tasks_run,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py::TestSwarmCoordinator -v`
Expected: all 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/agent/swarm.py tests/test_research_swarm.py
git commit -m "feat(swarm): add SwarmCoordinator daemon thread"
```

---

## Task 11: AgentPool Integration

**Files:**
- Modify: `core/agent/pool.py`

- [ ] **Step 1: Add swarm coordinator to AgentPool**

In `core/agent/pool.py`, add to `__init__` (after `self._paper_broker: Optional[Any] = None` on line 84):

```python
        self._swarm: Optional[Any] = None
```

Then add these methods after the `shutdown` method (line 328):

```python
    # ── swarm lifecycle ─────────────────────────────────────────────

    def start_swarm(self) -> None:
        """Start the research swarm coordinator if enabled in config."""
        try:
            config = self._load_config()
            swarm_cfg = config.get("swarm", {})
            if not swarm_cfg.get("enabled", False):
                logger.info("AgentPool: swarm disabled in config")
                return
        except Exception:
            return

        if self._swarm is not None and self._swarm.is_alive():
            return

        from core.agent.swarm import SwarmCoordinator

        paper_mode = self._force_paper
        broker = self.get_broker_for_mode(paper_mode)

        self._swarm = SwarmCoordinator(
            config_path=self._config_path,
            broker_service=broker,
            db_path=self._db_path,
            paper_mode=paper_mode,
            watchlist_provider=self._watchlist_provider,
        )
        self._swarm.start()

    def stop_swarm(self) -> None:
        if self._swarm is not None and self._swarm.is_alive():
            self._swarm.stop()
            self._swarm.join(timeout=10)
            self._swarm = None

    @property
    def swarm(self) -> Optional[Any]:
        return self._swarm

    def swarm_running(self) -> bool:
        return self._swarm is not None and self._swarm.is_alive()

    def set_watchlist_provider(self, provider: Any) -> None:
        """Set the watchlist provider for the swarm coordinator."""
        self._watchlist_provider = provider
```

Also add `self._watchlist_provider: Any = lambda: []` to `__init__` (after the `_paper_broker` line).

Update the `shutdown` method to also stop the swarm:

```python
    def shutdown(self) -> None:
        """Best-effort clean shutdown of everything in the pool."""
        self.cancel_all_chat_workers()
        self.stop_swarm()
        self.kill_supervisor()
```

- [ ] **Step 2: Commit**

```bash
git add core/agent/pool.py
git commit -m "feat(swarm): wire SwarmCoordinator into AgentPool"
```

---

## Task 12: Supervisor Prompt — Swarm Intelligence Brief

**Files:**
- Modify: `core/agent/prompts.py`

- [ ] **Step 1: Add swarm brief to supervisor prompt**

In `core/agent/prompts.py`, add a new block to `SYSTEM_PROMPT_AUTONOMOUS_PM_TEMPLATE` after the `## Tool catalogue` section (before `## Standing rules`, around line 196). Insert:

```
## Research swarm

You have a 20-agent research swarm running in parallel. Ten quick-
reaction agents scan breaking news, social media, and Grok/X intelligence
every few minutes. Ten deep-research agents analyse sectors, macro, and
patterns over longer cycles.

Their findings are in `research_findings` — call `get_findings` to read
them. High-confidence findings (>70%) are strong signals. Use
`get_swarm_status` to see what the swarm is working on.

You can direct the swarm with `set_research_goal` — e.g. "Investigate
biotech sector sentiment before market open" — and the coordinator will
prioritise matching roles.

The swarm observes and reports. You decide and trade.
```

- [ ] **Step 2: Commit**

```bash
git add core/agent/prompts.py
git commit -m "feat(swarm): add research swarm section to supervisor prompt"
```

---

## Task 13: Config + Requirements

**Files:**
- Modify: `config.json`
- Modify: `requirements.txt`

- [ ] **Step 1: Add swarm config section**

In `config.json`, add after the `"news"` section:

```json
  "swarm": {
    "enabled": true,
    "max_concurrent_workers": 4,
    "grok_enabled": true,
    "grok_session_path": "data/grok_session",
    "finding_retention_days": 30
  },
```

- [ ] **Step 2: Add playwright to requirements.txt**

Append to `requirements.txt`:

```
playwright>=1.44
```

- [ ] **Step 3: Commit**

```bash
git add config.json requirements.txt
git commit -m "feat(swarm): add swarm config section + playwright dependency"
```

---

## Task 14: Desktop Integration — Start Swarm on Boot

**Files:**
- Modify: `desktop/app.py`

- [ ] **Step 1: Wire swarm startup**

In `desktop/app.py`, find the `_ensure_agent_pool` method. After the existing pool setup, add the watchlist provider and swarm start:

```python
        self.agent_pool.set_watchlist_provider(self._get_active_tickers)
        self.agent_pool.start_swarm()
```

Where `_get_active_tickers` is the same lambda already used by the scraper runner — it reads the active watchlist from config.

- [ ] **Step 2: Commit**

```bash
git add desktop/app.py
git commit -m "feat(swarm): start research swarm on desktop boot"
```

---

## Task 15: Installer — Hidden Imports

**Files:**
- Modify: `installer/blank.spec`

- [ ] **Step 1: Add new modules to hiddenimports**

In `installer/blank.spec`, in the `hiddenimports` list (after the existing `core.agent.tools.flow_tools` line), add:

```python
        'core.agent.swarm', 'core.agent.research_worker',
        'core.agent.research_queue', 'core.agent.research_roles',
        'core.agent.prompts_research',
        'core.agent.tools.research_tools', 'core.agent.tools.grok_tools',
        'playwright', 'playwright.async_api',
```

- [ ] **Step 2: Commit**

```bash
git add installer/blank.spec
git commit -m "feat(swarm): add swarm modules to PyInstaller hiddenimports"
```

---

## Task 16: Run Full Test Suite

- [ ] **Step 1: Run all swarm tests**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_research_swarm.py -v`
Expected: all tests PASS.

- [ ] **Step 2: Run existing agent tests to check for regressions**

Run: `cd E:\Coding\StockMarketAI && python -m pytest tests/test_agent_loop.py -v`
Expected: all existing tests still PASS (the new MCP tools increase ALL_TOOLS count, so `test_every_tool_has_name_and_handler`'s `>= 25` assertion still holds).

- [ ] **Step 3: Verify no import errors**

Run: `cd E:\Coding\StockMarketAI && python -c "from core.agent.swarm import SwarmCoordinator; from core.agent.research_worker import ResearchWorker; from core.agent.tools.grok_tools import GROK_TOOLS; from core.agent.tools.research_tools import RESEARCH_TOOLS; print('All imports OK')"`
Expected: `All imports OK`
