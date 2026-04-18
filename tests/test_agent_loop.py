"""Integration tests for the agent tool bus.

These tests exercise the *plumbing* of the agent loop without
spawning a real AI engine subprocess. We:

* round-trip ``init_agent_context`` / ``get_agent_context`` /
  ``clear_agent_context``,
* validate every entry in ``ALL_TOOLS`` is a real ``SdkMcpTool``
  with a callable ``.handler`` and a non-empty ``.name``,
* build the in-process MCP server and confirm the registered tool
  names line up with what ``allowed_tool_names()`` reports,
* invoke a representative cross-section of tools end-to-end with a
  ``MagicMock`` broker so the journal rows actually land in sqlite,
* assert ``end_iteration`` mutates the context flags the runner reads.

No real network, no subprocess, no broker keys — everything stays
inside the test process. Together with ``test_browser_tools.py`` this
gives us full coverage of the tool surface that ``AgentRunner`` will
expose to a live AI session.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from broker_service import BrokerService
from database import HistoryManager
from risk_manager import RiskManager

from core.agent.context import (
    AgentContext,
    clear_agent_context,
    get_agent_context,
    init_agent_context,
)
from core.agent.mcp_server import (
    ALL_TOOLS,
    SERVER_NAME,
    allowed_tool_names,
    build_mcp_server,
)
from core.agent.tools.flow_tools import end_iteration
from core.agent.tools.broker_tools import get_portfolio, place_order
from core.agent.tools.market_hours_tools import get_market_status


# ─── helpers ─────────────────────────────────────────────────────────────

def _run(coro: Any) -> Dict[str, Any]:
    """Invoke an async tool handler and unwrap the JSON text payload."""
    result = asyncio.run(coro)
    return json.loads(result["content"][0]["text"])


def _journal_rows(db_path: str, iteration_id: str) -> List[tuple[str, str, str]]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT kind, tool, tags FROM agent_journal "
            "WHERE iteration_id = ? ORDER BY id",
            (iteration_id,),
        ))


# ─── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def real_ctx(tmp_path: Path) -> AgentContext:
    """An AgentContext backed by real BrokerService/HistoryManager/RiskManager
    pointed at a throwaway sqlite DB. Broker is in log-mode so no network."""
    db_path = str(tmp_path / "agent_loop.db")
    config: Dict[str, Any] = {
        "broker": {"type": "log"},
        "agent": {
            "paper_mode": True,
            "max_position_pct": 20.0,
            "max_trades_per_hour": 10,
        },
        "database": {"path": db_path},
    }
    db = HistoryManager(db_path)
    broker = BrokerService(config=config)
    risk = RiskManager(config=config)
    ctx = init_agent_context(
        config=config,
        broker_service=broker,
        db=db,
        risk_manager=risk,
        iteration_id=f"loop-{uuid.uuid4().hex[:8]}",
        paper_mode=True,
    )
    yield ctx
    clear_agent_context()


@pytest.fixture
def mocked_ctx(tmp_path: Path) -> AgentContext:
    """An AgentContext whose broker is a MagicMock so we can dictate
    positions/account info per test without touching any real broker
    code path."""
    db_path = str(tmp_path / "agent_mock.db")
    config: Dict[str, Any] = {
        "broker": {"type": "log"},
        "agent": {"paper_mode": True, "max_position_pct": 20.0},
        "database": {"path": db_path},
    }
    db = HistoryManager(db_path)
    broker = MagicMock(spec=BrokerService)
    broker.is_live = False
    broker.get_positions.return_value = [
        {"ticker": "TSLA_US_EQ", "quantity": 5.0,
         "avg_price": 200.0, "current_price": 210.0,
         "unrealised_pnl": 50.0},
        {"ticker": "BPl_EQ", "quantity": 100.0,
         "avg_price": 4.5, "current_price": 4.7,
         "unrealised_pnl": 20.0},
    ]
    broker.get_account_info.return_value = {
        "free": 5_000.0, "invested": 1_500.0,
        "result": 70.0, "total": 6_500.0,
    }
    broker.get_pending_orders.return_value = []
    broker.get_order_history.return_value = {"items": []}
    broker.submit_order.return_value = {"status": "submitted", "order_id": "X"}
    broker.cancel_order.return_value = True
    risk = RiskManager(config=config)
    ctx = init_agent_context(
        config=config,
        broker_service=broker,
        db=db,
        risk_manager=risk,
        iteration_id=f"mock-{uuid.uuid4().hex[:8]}",
        paper_mode=True,
    )
    yield ctx
    clear_agent_context()


# ─── context lifecycle ──────────────────────────────────────────────────

class TestContextLifecycle:
    def test_init_then_get_returns_same_instance(self, real_ctx: AgentContext) -> None:
        assert get_agent_context() is real_ctx
        assert real_ctx.iteration_id.startswith("loop-")
        assert real_ctx.paper_mode is True
        assert real_ctx.end_requested is False

    def test_clear_makes_get_raise(self, real_ctx: AgentContext) -> None:
        clear_agent_context()
        with pytest.raises(RuntimeError, match="not initialised"):
            get_agent_context()
        # Re-init so the fixture's teardown clear is a no-op.
        init_agent_context(
            config=real_ctx.config,
            broker_service=real_ctx.broker_service,
            db=real_ctx.db,
            risk_manager=real_ctx.risk_manager,
            iteration_id=real_ctx.iteration_id,
            paper_mode=real_ctx.paper_mode,
        )


# ─── tool registry shape ────────────────────────────────────────────────

class TestToolRegistry:
    def test_every_tool_has_name_and_handler(self) -> None:
        assert len(ALL_TOOLS) >= 25, "tool catalogue suspiciously thin"
        seen: set[str] = set()
        for t in ALL_TOOLS:
            name = getattr(t, "name", "")
            handler = getattr(t, "handler", None)
            assert name, f"tool missing .name: {t!r}"
            assert callable(handler), f"tool {name} has non-callable .handler"
            assert name not in seen, f"duplicate tool name {name}"
            seen.add(name)

    def test_market_hours_and_backtest_registered(self) -> None:
        names = {t.name for t in ALL_TOOLS}
        assert "get_market_status" in names
        assert "simulate_stop_target" in names
        assert "fetch_page" in names
        assert "end_iteration" in names

    def test_allowed_names_match_registered_tools(self) -> None:
        registered = {f"mcp__{SERVER_NAME}__{t.name}" for t in ALL_TOOLS}
        allowed = set(allowed_tool_names())
        assert registered == allowed

    def test_build_mcp_server_returns_object(self) -> None:
        srv = build_mcp_server()
        assert srv is not None  # SDK returns a dict-shaped server descriptor


# ─── invocation cycle ──────────────────────────────────────────────────

class TestInvocationCycle:
    def test_get_portfolio_round_trip(self, mocked_ctx: AgentContext) -> None:
        payload = _run(get_portfolio.handler({}))

        assert payload["equity"] == 6_500.0
        assert payload["cash_free"] == 5_000.0
        assert payload["paper_mode_flag"] is True
        assert len(payload["positions"]) == 2
        tickers = {p["ticker"] for p in payload["positions"]}
        assert tickers == {"TSLA_US_EQ", "BPl_EQ"}

        # Journal row written for the call.
        rows = _journal_rows(mocked_ctx.db.db_path, mocked_ctx.iteration_id)
        assert any(kind == "tool_call" and tool == "get_portfolio" for kind, tool, _ in rows)

    def test_place_order_refuses_overquantity_sell(self, mocked_ctx: AgentContext) -> None:
        # We only hold 5 TSLA — selling 10 must be refused with the
        # ownership message and recorded as ``order_refused``.
        payload = _run(place_order.handler({
            "ticker": "TSLA_US_EQ",
            "side": "sell",
            "quantity": 10,
            "order_type": "market",
            "reason": "stop hunt",
        }))
        assert payload["status"] == "rejected"
        assert "only 5" in payload["reason"]

        # MagicMock broker should NOT have been hit with submit_order.
        mocked_ctx.broker_service.submit_order.assert_not_called()

        rows = _journal_rows(mocked_ctx.db.db_path, mocked_ctx.iteration_id)
        kinds = [k for k, _, _ in rows]
        assert "order_refused" in kinds

    def test_place_order_happy_path_logs_trade(self, mocked_ctx: AgentContext) -> None:
        # Sell 2 TSLA — within ownership, should hit submit_order and
        # write an ``order_placed`` journal row.
        payload = _run(place_order.handler({
            "ticker": "TSLA_US_EQ",
            "side": "sell",
            "quantity": 2,
            "order_type": "market",
            "reason": "trim",
        }))
        assert payload["status"] == "submitted"
        mocked_ctx.broker_service.submit_order.assert_called_once()

        rows = _journal_rows(mocked_ctx.db.db_path, mocked_ctx.iteration_id)
        assert any(k == "order_placed" for k, _, _ in rows)

    def test_get_market_status_buckets_positions(self, mocked_ctx: AgentContext) -> None:
        payload = _run(get_market_status.handler({}))

        assert isinstance(payload["exchanges"], list)
        assert payload["total_positions"] == 2
        # TSLA → US, BPl → LSE
        by_code = {e["code"]: e for e in payload["exchanges"]}
        assert by_code["US"]["positions_count"] == 1
        assert by_code["LSE"]["positions_count"] == 1
        # Other venues should report zero so the panel can render dashes.
        assert by_code["XETRA"]["positions_count"] == 0
        # is_open is a bool
        assert isinstance(by_code["US"]["is_open"], bool)


# ─── end_iteration semantics ────────────────────────────────────────────

class TestEndIteration:
    def test_sets_runner_signals(self, real_ctx: AgentContext) -> None:
        payload = _run(end_iteration.handler({
            "summary": "Slept early — markets closed.",
            "next_check_in_minutes": 45,
        }))

        assert payload["status"] == "ended"
        assert payload["next_check_in_minutes"] == 45
        assert real_ctx.end_requested is True
        assert real_ctx.next_wait_minutes == 45
        assert real_ctx.end_summary == "Slept early — markets closed."

        rows = _journal_rows(real_ctx.db.db_path, real_ctx.iteration_id)
        assert any(k == "iteration_end" and tool == "end_iteration" for k, tool, _ in rows)

    def test_negative_minutes_clamped_to_zero(self, real_ctx: AgentContext) -> None:
        _run(end_iteration.handler({
            "summary": "asap",
            "next_check_in_minutes": -10,
        }))
        assert real_ctx.next_wait_minutes == 0
