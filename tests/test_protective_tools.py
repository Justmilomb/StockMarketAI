"""Smoke tests for the protective MCP tools."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.agent.context import clear_agent_context, init_agent_context
from core.protective_orders import ProtectiveStore, StopKind


def _payload(result):
    return json.loads(result["content"][0]["text"])


class _StubDB:
    def __init__(self, p: Path) -> None:
        self.db_path = str(p)


@pytest.fixture
def store(tmp_path: Path):
    """Build a wired-up agent context backed by a real ProtectiveStore."""
    db_path = tmp_path / "h.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE agent_journal (id INTEGER PRIMARY KEY, "
            "iteration_id TEXT, kind TEXT, tool TEXT, payload TEXT, tags TEXT)",
        )
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    init_agent_context(
        config={}, broker_service=None,  # type: ignore[arg-type]
        db=_StubDB(db_path),  # type: ignore[arg-type]
        risk_manager=None,  # type: ignore[arg-type]
        iteration_id="t", paper_mode=True,
        protective_store=store,
    )
    yield store
    clear_agent_context()


def _call(tool, args):
    """SDK @tool decorator wraps the original fn into an MCP-shaped object;
    the underlying coroutine is exposed under either .handler, .fn, or
    by reaching into __wrapped__. Use whichever is present.
    """
    fn = getattr(tool, "handler", None) or getattr(tool, "fn", None)
    if fn is None:
        fn = getattr(tool, "__wrapped__", None) or tool
    return asyncio.run(fn(args))


def test_set_stop_loss_tool(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import set_stop_loss
    result = _call(set_stop_loss, {
        "ticker": "AAPL", "trigger_price": 100.0, "quantity": 5.0,
    })
    data = _payload(result)
    assert data["status"] == "ok"
    assert data["order"]["kind"] == "stop_loss"
    assert store.list_active()[0].trigger_price == 100.0


def test_set_take_profit_tool(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import set_take_profit
    result = _call(set_take_profit, {
        "ticker": "MSFT", "trigger_price": 400.0, "quantity": 2.0,
    })
    data = _payload(result)
    assert data["status"] == "ok"
    assert data["order"]["kind"] == "take_profit"


def test_set_trailing_stop_with_explicit_anchor(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import set_trailing_stop
    result = _call(set_trailing_stop, {
        "ticker": "TSLA", "distance_pct": 10.0, "quantity": 1.0,
        "anchor_price": 200.0,
    })
    data = _payload(result)
    assert data["status"] == "ok"
    assert data["order"]["anchor_price"] == 200.0
    assert data["order"]["trigger_price"] == pytest.approx(180.0)


def test_list_active_stops_returns_distance(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import list_active_stops
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
    result = _call(list_active_stops, {"_test_prices": {"AAPL": 110.0}})
    data = _payload(result)
    assert len(data["orders"]) == 1
    o = data["orders"][0]
    assert o["current_price"] == 110.0
    assert o["distance_pct_to_trigger"] == pytest.approx(-9.0909, rel=1e-3)


def test_adjust_stop_tool(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import adjust_stop
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
    result = _call(adjust_stop, {
        "ticker": "AAPL", "order_type": "stop_loss", "new_price": 95.0,
    })
    data = _payload(result)
    assert data["status"] == "ok"
    assert data["updated"] == 1
    assert store.list_active()[0].trigger_price == 95.0


def test_adjust_stop_unknown_kind(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import adjust_stop
    result = _call(adjust_stop, {
        "ticker": "AAPL", "order_type": "garbage", "new_price": 95.0,
    })
    data = _payload(result)
    assert data["status"] == "rejected"


def test_cancel_stop_tool(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import cancel_stop
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
    result = _call(cancel_stop, {
        "ticker": "AAPL", "order_type": "stop_loss",
    })
    data = _payload(result)
    assert data["removed"] == 1
    assert store.list_active() == []


def test_set_stop_loss_rejects_zero_trigger(store: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import set_stop_loss
    result = _call(set_stop_loss, {
        "ticker": "AAPL", "trigger_price": 0.0, "quantity": 5.0,
    })
    data = _payload(result)
    assert data["status"] == "rejected"
    assert store.list_active() == []
