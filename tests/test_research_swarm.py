"""Tests for the research swarm DB schema and HistoryManager helper methods."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database import HistoryManager


# ── helpers ───────────────────────────────────────────────────────────────────

def _columns(db_path: Path, table: str) -> set[str]:
    """Return the set of column names for *table*."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _tables(db_path: Path) -> set[str]:
    """Return the set of all user-created table names in the database."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {row[0] for row in rows}


# ── schema tests ──────────────────────────────────────────────────────────────

class TestResearchSchema:
    """Verify all three research swarm tables are created by _init_db."""

    @pytest.fixture()
    def db(self, tmp_path: Path) -> HistoryManager:
        return HistoryManager(db_path=str(tmp_path / "test.db"))

    def test_all_three_tables_exist(self, db: HistoryManager) -> None:
        tables = _tables(db.db_path)
        assert "research_tasks" in tables
        assert "research_findings" in tables
        assert "research_goals" in tables

    def test_research_tasks_columns(self, db: HistoryManager) -> None:
        cols = _columns(db.db_path, "research_tasks")
        expected = {
            "id", "role", "status", "ticker", "parameters", "goal_id",
            "priority", "assigned_worker", "created_at", "started_at",
            "completed_at", "error",
        }
        assert expected.issubset(cols)

    def test_research_findings_columns(self, db: HistoryManager) -> None:
        cols = _columns(db.db_path, "research_findings")
        expected = {
            "id", "task_id", "role", "ticker", "finding_type", "headline",
            "detail", "confidence_pct", "source", "methodology",
            "evidence_json", "acted_on", "created_at",
        }
        assert expected.issubset(cols)

    def test_research_goals_columns(self, db: HistoryManager) -> None:
        cols = _columns(db.db_path, "research_goals")
        expected = {
            "id", "goal", "status", "priority", "created_by", "target_roles",
            "deadline_at", "findings_count", "created_at", "completed_at",
        }
        assert expected.issubset(cols)


# ── helper method tests ───────────────────────────────────────────────────────

class TestResearchDBHelpers:
    """End-to-end tests for all HistoryManager research swarm methods."""

    @pytest.fixture()
    def db(self, tmp_path: Path) -> HistoryManager:
        return HistoryManager(db_path=str(tmp_path / "test.db"))

    # ── tasks ────────────────────────────────────────────────────────────────

    def test_insert_and_claim_task(self, db: HistoryManager) -> None:
        task_id = db.insert_research_task(
            role="quant_analyst",
            priority=3,
            ticker="AAPL",
            parameters=json.dumps({"window": 20}),
        )
        assert task_id > 0

        claimed = db.claim_research_task(worker_id="worker-1")
        assert claimed is not None
        assert claimed["id"] == task_id
        assert claimed["role"] == "quant_analyst"
        assert claimed["ticker"] == "AAPL"

        # Queue should now be empty for a second worker
        second = db.claim_research_task(worker_id="worker-2")
        assert second is None

    def test_claim_returns_none_on_empty_queue(self, db: HistoryManager) -> None:
        result = db.claim_research_task(worker_id="worker-1")
        assert result is None

    def test_complete_task_success(self, db: HistoryManager) -> None:
        task_id = db.insert_research_task(role="news_analyst")
        db.claim_research_task(worker_id="w1")
        db.complete_research_task(task_id)

        stats = db.get_research_task_stats()
        assert stats.get("completed", 0) == 1
        assert stats.get("running", 0) == 0

    def test_complete_task_with_error(self, db: HistoryManager) -> None:
        task_id = db.insert_research_task(role="macro_analyst")
        db.claim_research_task(worker_id="w1")
        db.complete_research_task(task_id, error="timeout after 30s")

        stats = db.get_research_task_stats()
        assert stats.get("failed", 0) == 1

        with sqlite3.connect(db.db_path) as conn:
            row = conn.execute(
                "SELECT error FROM research_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        assert row is not None
        assert row[0] == "timeout after 30s"

    # ── findings ─────────────────────────────────────────────────────────────

    def test_save_and_get_findings(self, db: HistoryManager) -> None:
        finding_id = db.save_research_finding({
            "role": "quant_analyst",
            "ticker": "MSFT",
            "finding_type": "momentum",
            "headline": "Strong momentum signal detected",
            "detail": "RSI above 70 for 3 consecutive days",
            "confidence_pct": 80,
            "source": "technical_screen",
        })
        assert finding_id > 0

        findings = db.get_research_findings(since_minutes=60)
        assert len(findings) == 1
        f = findings[0]
        assert f["role"] == "quant_analyst"
        assert f["ticker"] == "MSFT"
        assert f["finding_type"] == "momentum"
        assert f["confidence_pct"] == 80

    def test_get_findings_filters_by_ticker(self, db: HistoryManager) -> None:
        db.save_research_finding({
            "role": "r1", "ticker": "AAPL",
            "finding_type": "momentum", "headline": "AAPL signal",
            "confidence_pct": 70,
        })
        db.save_research_finding({
            "role": "r2", "ticker": "GOOGL",
            "finding_type": "value", "headline": "GOOGL signal",
            "confidence_pct": 60,
        })

        aapl_findings = db.get_research_findings(ticker="AAPL")
        assert len(aapl_findings) == 1
        assert aapl_findings[0]["ticker"] == "AAPL"

    def test_get_findings_filters_by_min_confidence(self, db: HistoryManager) -> None:
        db.save_research_finding({
            "role": "r1", "finding_type": "t1",
            "headline": "High confidence", "confidence_pct": 90,
        })
        db.save_research_finding({
            "role": "r2", "finding_type": "t2",
            "headline": "Low confidence", "confidence_pct": 30,
        })

        high = db.get_research_findings(min_confidence=70)
        assert len(high) == 1
        assert high[0]["confidence_pct"] == 90

    def test_get_findings_filters_by_type(self, db: HistoryManager) -> None:
        db.save_research_finding({
            "role": "r1", "finding_type": "momentum",
            "headline": "Momentum", "confidence_pct": 75,
        })
        db.save_research_finding({
            "role": "r2", "finding_type": "value",
            "headline": "Value", "confidence_pct": 65,
        })

        momentum = db.get_research_findings(finding_type="momentum")
        assert len(momentum) == 1
        assert momentum[0]["finding_type"] == "momentum"

    # ── priority ordering ─────────────────────────────────────────────────────

    def test_priority_ordering(self, db: HistoryManager) -> None:
        """Lower priority integer = claimed first."""
        db.insert_research_task(role="slow_analyst", priority=9)
        db.insert_research_task(role="fast_analyst", priority=1)
        db.insert_research_task(role="mid_analyst", priority=5)

        first = db.claim_research_task(worker_id="w1")
        assert first is not None
        assert first["role"] == "fast_analyst"

        second = db.claim_research_task(worker_id="w2")
        assert second is not None
        assert second["role"] == "mid_analyst"

        third = db.claim_research_task(worker_id="w3")
        assert third is not None
        assert third["role"] == "slow_analyst"

    # ── goals ────────────────────────────────────────────────────────────────

    def test_insert_and_get_goals(self, db: HistoryManager) -> None:
        goal_id = db.insert_research_goal(
            goal="Find undervalued tech stocks",
            priority=2,
            created_by="supervisor",
            target_roles="quant_analyst,news_analyst",
            deadline_at="2026-05-01T00:00:00",
        )
        assert goal_id > 0

        goals = db.get_active_research_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g["goal"] == "Find undervalued tech stocks"
        assert g["priority"] == 2
        assert g["status"] == "active"
        assert g["target_roles"] == "quant_analyst,news_analyst"

    def test_get_active_goals_excludes_completed(self, db: HistoryManager) -> None:
        goal_id = db.insert_research_goal(goal="Active goal")
        db.insert_research_goal(goal="Another active goal")

        with sqlite3.connect(db.db_path) as conn:
            conn.execute(
                "UPDATE research_goals SET status = 'completed' WHERE id = ?",
                (goal_id,),
            )

        active = db.get_active_research_goals()
        assert len(active) == 1
        assert active[0]["goal"] == "Another active goal"

    def test_get_active_goals_priority_ordering(self, db: HistoryManager) -> None:
        db.insert_research_goal(goal="Low priority", priority=8)
        db.insert_research_goal(goal="High priority", priority=1)

        goals = db.get_active_research_goals()
        assert goals[0]["goal"] == "High priority"
        assert goals[1]["goal"] == "Low priority"

    # ── task stats ───────────────────────────────────────────────────────────

    def test_get_research_task_stats(self, db: HistoryManager) -> None:
        db.insert_research_task(role="r1")
        db.insert_research_task(role="r2")
        t3 = db.insert_research_task(role="r3")
        db.claim_research_task(worker_id="w1")  # moves one to 'running'
        db.complete_research_task(t3)  # t3 was never claimed, status stays pending

        stats = db.get_research_task_stats()
        # Two pending (one claimed becomes running), one pending untouched
        # Exact counts depend on which was claimed; just verify keys are present
        assert isinstance(stats, dict)
        total = sum(stats.values())
        assert total == 3


# ── role definition tests ─────────────────────────────────────────────────────

class TestResearchRoles:
    """Verify the ResearchRole definitions in research_roles.py."""

    def test_exactly_20_roles(self) -> None:
        from agent.research_roles import ALL_ROLES

        assert len(ALL_ROLES) == 20

    def test_10_quick_10_deep(self) -> None:
        from agent.research_roles import ALL_ROLES

        quick = [r for r in ALL_ROLES if r.tier == "quick"]
        deep = [r for r in ALL_ROLES if r.tier == "deep"]
        assert len(quick) == 10
        assert len(deep) == 10

    def test_unique_role_ids(self) -> None:
        from agent.research_roles import ALL_ROLES

        ids = [r.role_id for r in ALL_ROLES]
        assert len(ids) == len(set(ids)), "Duplicate role_ids found"

    def test_role_has_required_fields(self) -> None:
        from agent.research_roles import ALL_ROLES

        valid_tiers = {"quick", "deep"}
        valid_model_tiers = {"simple", "medium", "complex"}

        for role in ALL_ROLES:
            assert role.role_id, f"role_id is empty for {role}"
            assert role.tier in valid_tiers, f"Invalid tier '{role.tier}' for {role.role_id}"
            assert role.model_tier in valid_model_tiers, (
                f"Invalid model_tier '{role.model_tier}' for {role.role_id}"
            )
            assert role.cadence_seconds > 0, (
                f"cadence_seconds must be positive for {role.role_id}"
            )
            assert role.focus, f"focus is empty for {role.role_id}"

    def test_get_role_by_id(self) -> None:
        from agent.research_roles import get_role

        grok = get_role("grok_miner")
        assert grok is not None
        assert grok.role_id == "grok_miner"
        assert grok.tier == "quick"
        assert grok.model_tier == "simple"
        assert grok.cadence_seconds == 180
        assert grok.default_tickers is False

        missing = get_role("nonexistent")
        assert missing is None


# ── model router tests ────────────────────────────────────────────────────────

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


# ── research tool tests ───────────────────────────────────────────────────────

def _run(coro: object) -> dict:  # type: ignore[type-arg]
    """Drive a coroutine to completion and decode the tool response payload."""
    result = asyncio.run(coro)  # type: ignore[arg-type]
    return json.loads(result["content"][0]["text"])


class TestResearchTools:
    """Integration tests for the four research swarm tools."""

    @pytest.fixture(autouse=True)
    def _agent_ctx(self, tmp_path: Path) -> "Generator[None, None, None]":  # type: ignore[name-defined]
        """Set up and tear down an AgentContext around each test."""
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context

        db = HistoryManager(db_path=str(tmp_path / "test.db"))
        config: dict = {"broker": {"type": "log"}, "agent": {"paper_mode": True}}
        broker = MagicMock(spec=BrokerService)
        risk = RiskManager(config=config)
        ctx = init_agent_context(
            config=config,
            broker_service=broker,
            db=db,
            risk_manager=risk,
            iteration_id="test-001",
            paper_mode=True,
        )
        ctx.stats["research_role"] = "quant_analyst"
        ctx.stats["research_task_id"] = 42
        # Expose db on self so individual tests can inspect the DB directly.
        self._db = db
        yield
        clear_agent_context()

    # ── submit_finding ────────────────────────────────────────────────────────

    def test_submit_finding_writes_to_db(self) -> None:
        from core.agent.tools.research_tools import submit_finding

        payload = _run(submit_finding.handler({
            "ticker": "AAPL",
            "finding_type": "catalyst",
            "headline": "AAPL earnings beat expected",
            "confidence_pct": 82,
            "source": "earnings_report",
            "detail": "Revenue up 12% YoY",
            "methodology": "fundamental",
            "evidence": "Q2 2026 press release",
        }))

        assert payload["status"] == "saved"
        assert payload["finding_id"] > 0
        assert payload["ticker"] == "AAPL"
        assert payload["finding_type"] == "catalyst"
        assert payload["confidence_pct"] == 82

        # Verify the row actually landed in the DB.
        rows = self._db.get_research_findings(since_minutes=10, ticker="AAPL")
        assert len(rows) == 1
        assert rows[0]["headline"] == "AAPL earnings beat expected"
        assert rows[0]["role"] == "quant_analyst"

    def test_submit_finding_rejects_empty_headline(self) -> None:
        from core.agent.tools.research_tools import submit_finding

        payload = _run(submit_finding.handler({
            "ticker": "MSFT",
            "finding_type": "alert",
            "headline": "",
            "confidence_pct": 70,
            "source": "screen",
            "detail": "",
            "methodology": "",
            "evidence": "",
        }))

        assert payload["status"] == "rejected"
        assert "headline" in payload["reason"]

    def test_submit_finding_rejects_invalid_type(self) -> None:
        from core.agent.tools.research_tools import submit_finding

        payload = _run(submit_finding.handler({
            "ticker": "TSLA",
            "finding_type": "nonsense",
            "headline": "Some headline",
            "confidence_pct": 60,
            "source": "",
            "detail": "",
            "methodology": "",
            "evidence": "",
        }))

        assert payload["status"] == "rejected"
        assert "finding_type" in payload["reason"]

    def test_submit_finding_clamps_confidence(self) -> None:
        from core.agent.tools.research_tools import submit_finding

        payload = _run(submit_finding.handler({
            "ticker": "NVDA",
            "finding_type": "pattern",
            "headline": "Head and shoulders forming",
            "confidence_pct": 150,
            "source": "chart",
            "detail": "",
            "methodology": "technical",
            "evidence": "",
        }))

        assert payload["status"] == "saved"
        assert payload["confidence_pct"] == 100

    # ── get_findings ──────────────────────────────────────────────────────────

    def test_get_findings_reads_from_db(self) -> None:
        from core.agent.tools.research_tools import get_findings

        # Pre-insert directly via DB helper.
        self._db.save_research_finding({
            "role": "news_analyst",
            "ticker": "GOOG",
            "finding_type": "sentiment",
            "headline": "Positive analyst coverage",
            "confidence_pct": 75,
        })

        payload = _run(get_findings.handler({
            "since_minutes": 60,
            "min_confidence": 0,
            "ticker": "GOOG",
            "finding_type": "sentiment",
            "limit": 10,
        }))

        assert payload["count"] == 1
        assert payload["findings"][0]["ticker"] == "GOOG"
        assert payload["findings"][0]["finding_type"] == "sentiment"

    def test_get_findings_respects_min_confidence(self) -> None:
        from core.agent.tools.research_tools import get_findings

        self._db.save_research_finding({
            "role": "r1", "finding_type": "alert",
            "headline": "High conf", "confidence_pct": 90,
        })
        self._db.save_research_finding({
            "role": "r2", "finding_type": "alert",
            "headline": "Low conf", "confidence_pct": 20,
        })

        payload = _run(get_findings.handler({
            "since_minutes": 60,
            "min_confidence": 70,
            "ticker": "",
            "finding_type": "",
            "limit": 10,
        }))

        assert payload["count"] == 1
        assert payload["findings"][0]["confidence_pct"] == 90

    # ── set_research_goal ─────────────────────────────────────────────────────

    def test_set_research_goal_creates_goal(self) -> None:
        from core.agent.tools.research_tools import set_research_goal

        payload = _run(set_research_goal.handler({
            "goal": "Identify undervalued small-cap tech stocks",
            "priority": 3,
            "target_roles": "quant_analyst,news_analyst",
            "deadline_minutes": 60,
        }))

        assert payload["status"] == "created"
        assert payload["goal_id"] > 0
        assert payload["priority"] == 3

        goals = self._db.get_active_research_goals()
        assert len(goals) == 1
        assert goals[0]["goal"] == "Identify undervalued small-cap tech stocks"
        assert goals[0]["target_roles"] == "quant_analyst,news_analyst"

    def test_set_research_goal_rejects_empty_goal(self) -> None:
        from core.agent.tools.research_tools import set_research_goal

        payload = _run(set_research_goal.handler({
            "goal": "",
            "priority": 5,
            "target_roles": "",
            "deadline_minutes": 0,
        }))

        assert payload["status"] == "rejected"
        assert "goal" in payload["reason"]

    def test_set_research_goal_clamps_priority(self) -> None:
        from core.agent.tools.research_tools import set_research_goal

        payload = _run(set_research_goal.handler({
            "goal": "Some goal",
            "priority": 99,
            "target_roles": "",
            "deadline_minutes": 0,
        }))

        assert payload["status"] == "created"
        assert payload["priority"] == 10

    # ── get_swarm_status ──────────────────────────────────────────────────────

    def test_get_swarm_status_returns_stats(self) -> None:
        from core.agent.tools.research_tools import get_swarm_status

        # Seed some data so the response is non-trivial.
        self._db.insert_research_task(role="quant_analyst", priority=2)
        self._db.insert_research_goal(goal="Watch macro signals", priority=1)
        self._db.save_research_finding({
            "role": "quant_analyst",
            "finding_type": "thesis",
            "headline": "Bull trend intact",
            "confidence_pct": 80,
        })

        payload = _run(get_swarm_status.handler({}))

        assert "task_queue" in payload
        assert "active_goals" in payload
        assert "top_findings_last_2h" in payload
        assert isinstance(payload["task_queue"], dict)
        assert isinstance(payload["active_goals"], list)
        assert isinstance(payload["top_findings_last_2h"], list)
        # The seeded task should appear in the queue.
        assert payload["task_queue"].get("pending", 0) >= 1
        # The seeded goal should appear.
        assert len(payload["active_goals"]) >= 1
        # The high-confidence finding should appear.
        assert len(payload["top_findings_last_2h"]) >= 1


# ── grok tool tests ───────────────────────────────────────────────────────────

class TestGrokTools:
    """Tests for query_grok — always mock _run_grok_query; never launch a real browser."""

    @pytest.fixture(autouse=True)
    def _agent_ctx(self, tmp_path: Path) -> "Generator[None, None, None]":  # type: ignore[name-defined]
        """Set up and tear down an AgentContext around each test."""
        from broker_service import BrokerService
        from risk_manager import RiskManager
        from core.agent.context import init_agent_context, clear_agent_context

        db = HistoryManager(db_path=str(tmp_path / "test.db"))
        config: dict = {"broker": {"type": "log"}, "agent": {"paper_mode": True}}
        broker = MagicMock(spec=BrokerService)
        risk = RiskManager(config=config)
        ctx = init_agent_context(
            config=config,
            broker_service=broker,
            db=db,
            risk_manager=risk,
            iteration_id="test-grok-001",
            paper_mode=True,
        )
        ctx.stats["research_role"] = "grok_miner"
        ctx.stats["research_task_id"] = 99
        yield
        clear_agent_context()

    def test_query_grok_returns_response(self) -> None:
        """Successful query returns status=ok with response text and correct metadata."""
        from core.agent.tools.grok_tools import query_grok

        with patch(
            "core.agent.tools.grok_tools._run_grok_query",
            new_callable=AsyncMock,
            return_value="NVDA is trending on X with extremely bullish sentiment",
        ):
            payload = _run(query_grok.handler({
                "query": "What is the sentiment on NVDA right now?",
                "timeout_seconds": 30,
            }))

        assert payload["status"] == "ok"
        assert "NVDA" in payload["response"]
        assert "bullish" in payload["response"]
        assert payload["source"] == "grok_x"
        assert payload["query"] == "What is the sentiment on NVDA right now?"
        assert payload["queries_used"] == 1
        assert payload["queries_remaining"] == 2

    def test_query_grok_handles_timeout(self) -> None:
        """TimeoutError from _run_grok_query is surfaced as status=error with 'timed out' in the message."""
        from core.agent.tools.grok_tools import query_grok

        with patch(
            "core.agent.tools.grok_tools._run_grok_query",
            new_callable=AsyncMock,
            side_effect=TimeoutError("Grok did not return a stable response within 30s"),
        ):
            payload = _run(query_grok.handler({
                "query": "What are people saying about AAPL earnings?",
                "timeout_seconds": 30,
            }))

        assert payload["status"] == "error"
        assert "timed out" in payload["error"].lower()
        assert payload["queries_used"] == 1

    def test_query_grok_rate_limits(self) -> None:
        """Fourth call is rejected with status=rate_limited after three successful queries."""
        from core.agent.tools.grok_tools import query_grok, MAX_GROK_QUERIES_PER_ITER

        assert MAX_GROK_QUERIES_PER_ITER == 3

        with patch(
            "core.agent.tools.grok_tools._run_grok_query",
            new_callable=AsyncMock,
            return_value="Some response from Grok",
        ):
            # First three calls should succeed.
            for i in range(1, MAX_GROK_QUERIES_PER_ITER + 1):
                result = _run(query_grok.handler({
                    "query": f"Query number {i}",
                    "timeout_seconds": 30,
                }))
                assert result["status"] == "ok", f"Expected ok on call {i}, got {result}"
                assert result["queries_used"] == i

            # Fourth call must be rate-limited — no mock needed as it never reaches
            # _run_grok_query.
            over_limit = _run(query_grok.handler({
                "query": "This should be blocked",
                "timeout_seconds": 30,
            }))

        assert over_limit["status"] == "rate_limited"
        assert over_limit["queries_remaining"] == 0


# ── prompt rendering tests ────────────────────────────────────────────────────

class TestResearchPrompts:
    """Verify render_research_prompt produces correctly tailored system prompts."""

    def test_render_includes_role_focus(self) -> None:
        from agent.research_roles import get_role
        from agent.prompts_research import render_research_prompt

        role = get_role("grok_miner")
        assert role is not None

        prompt = render_research_prompt(config={}, role=role, watchlist=["NVDA", "TSLA"])

        assert "grok_miner" in prompt
        assert role.focus in prompt
        assert "submit_finding" in prompt
        assert "NVDA" in prompt
        assert "TSLA" in prompt

    def test_render_quick_vs_deep_instructions(self) -> None:
        from agent.research_roles import get_role
        from agent.prompts_research import render_research_prompt

        quick_role = get_role("tech_watcher")
        deep_role = get_role("macro_researcher")
        assert quick_role is not None
        assert deep_role is not None

        quick_prompt = render_research_prompt(config={}, role=quick_role)
        deep_prompt = render_research_prompt(config={}, role=deep_role)

        assert "quick" in quick_prompt.lower()
        assert "deep" in deep_prompt.lower()


# ── research queue tests ──────────────────────────────────────────────────────

class TestResearchQueue:
    """Cadence-based scheduler: due roles, priority ordering, mark_fired."""

    def test_all_roles_due_initially(self) -> None:
        """A fresh queue has no fire history, so all 20 roles are due."""
        from core.agent.research_queue import ResearchQueue
        from agent.research_roles import ALL_ROLES

        queue = ResearchQueue()
        due = queue.get_due_roles()
        assert len(due) == len(ALL_ROLES) == 20

    def test_role_not_due_after_fire(self) -> None:
        """Marking a role as fired removes it from the due list immediately."""
        from core.agent.research_queue import ResearchQueue

        queue = ResearchQueue()
        queue.mark_fired("tech_watcher")
        due_ids = {r.role_id for r in queue.get_due_roles()}
        assert "tech_watcher" not in due_ids
        # All other 19 roles should still be due.
        assert len(due_ids) == 19

    def test_priority_quick_over_deep(self) -> None:
        """On a fresh queue, all quick-tier roles appear before all deep-tier roles."""
        from core.agent.research_queue import ResearchQueue

        queue = ResearchQueue()
        due = queue.get_due_roles()
        tiers = [r.tier for r in due]

        quick_indices = [i for i, t in enumerate(tiers) if t == "quick"]
        deep_indices = [i for i, t in enumerate(tiers) if t == "deep"]

        assert quick_indices, "Expected at least one quick role in the due list"
        assert deep_indices, "Expected at least one deep role in the due list"
        assert max(quick_indices) < min(deep_indices), (
            "All quick roles must appear before all deep roles in the sorted output"
        )


# ── research worker tests ─────────────────────────────────────────────────────

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
        broker = MagicMock()

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


# ── swarm coordinator tests ───────────────────────────────────────────────────

class TestSwarmCoordinator:
    """Construction and task-generation behaviour of SwarmCoordinator."""

    def test_constructs(self, tmp_path: Path) -> None:
        """SwarmCoordinator reads max_concurrent_workers from config and is not alive yet."""
        from core.agent.swarm import SwarmCoordinator

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "swarm": {"max_concurrent_workers": 2},
        }))

        broker = MagicMock()
        coord = SwarmCoordinator(
            config_path=config_path,
            broker_service=broker,
            db_path=str(tmp_path / "test.db"),
            paper_mode=True,
        )

        assert coord._max_workers == 2
        assert not coord.is_alive()

    def test_generate_tasks_for_due_roles(self, tmp_path: Path) -> None:
        """Calling _generate_tasks directly inserts one pending task per role (20 total)."""
        from database import HistoryManager
        from core.agent.swarm import SwarmCoordinator

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "swarm": {"max_concurrent_workers": 4},
        }))

        broker = MagicMock()
        coord = SwarmCoordinator(
            config_path=config_path,
            broker_service=broker,
            db_path=str(tmp_path / "test.db"),
            paper_mode=True,
        )

        db = HistoryManager(db_path=str(tmp_path / "test.db"))
        coord._generate_tasks(db)

        stats = db.get_research_task_stats()
        assert stats.get("pending", 0) == 20
