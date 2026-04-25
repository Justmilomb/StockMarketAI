"""ProtectiveMonitor poll cycle: fires triggers, calls broker, stops cleanly."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.protective_orders import ProtectiveStore, StopKind
from core.protective_monitor import ProtectiveMonitor


class _StubBroker:
    """Captures every submit_order call for assertions."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.fail = fail

    def submit_order(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("broker exploded")
        return {"order_id": f"stub-{len(self.calls)}", "status": "FILLED"}


def _stub_price_feed(prices: Dict[str, float]):
    def fetch(tickers: List[str]) -> Dict[str, Dict[str, float]]:
        return {
            t: {"price": prices.get(t, 0.0), "change_pct": 0.0}
            for t in tickers
        }

    return fetch


def test_stop_loss_fires_and_submits_sell(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    broker = _StubBroker()
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=_stub_price_feed({"AAPL": 99.0}),
        poll_seconds=0.05,
    )
    monitor.tick()
    assert len(broker.calls) == 1
    assert broker.calls[0]["ticker"] == "AAPL"
    assert broker.calls[0]["side"] == "SELL"
    assert broker.calls[0]["quantity"] == 5.0
    assert store.list_active() == []


def test_take_profit_fires(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_take_profit("MSFT", trigger_price=400.0, quantity=2.0)
    broker = _StubBroker()
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=_stub_price_feed({"MSFT": 401.0}),
        poll_seconds=0.05,
    )
    monitor.tick()
    assert len(broker.calls) == 1
    assert broker.calls[0]["ticker"] == "MSFT"


def test_no_active_orders_is_a_noop(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    broker = _StubBroker()
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=_stub_price_feed({}),
        poll_seconds=0.05,
    )
    monitor.tick()
    assert broker.calls == []


def test_trailing_stop_ratchets_then_fires(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_trailing_stop(
        "TSLA", distance_pct=10.0, quantity=2.0, anchor_price=200.0,
    )
    broker = _StubBroker()
    prices: Dict[str, float] = {"TSLA": 220.0}

    def feed(tickers: List[str]) -> Dict[str, Dict[str, float]]:
        return {
            t: {"price": prices.get(t, 0.0), "change_pct": 0.0}
            for t in tickers
        }

    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=feed, poll_seconds=0.05,
    )
    monitor.tick()  # ratchets anchor -> 220, trigger -> 198
    assert broker.calls == []
    assert store.list_active()[0].trigger_price == pytest.approx(198.0)
    prices["TSLA"] = 197.0
    monitor.tick()
    assert len(broker.calls) == 1


def test_failed_broker_call_keeps_order(tmp_path: Path) -> None:
    """If the broker rejects, the stop stays active so the agent can react."""
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    broker = _StubBroker(fail=True)
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=_stub_price_feed({"AAPL": 99.0}),
        poll_seconds=0.05,
    )
    monitor.tick()
    assert len(broker.calls) == 1
    assert len(store.list_active()) == 1


def test_thread_lifecycle(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    broker = _StubBroker()
    started = threading.Event()

    def feed(tickers: List[str]) -> Dict[str, Dict[str, float]]:
        started.set()
        return {t: {"price": 0.0, "change_pct": 0.0} for t in tickers}

    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=feed, poll_seconds=0.02,
    )
    monitor.start()
    try:
        assert monitor.is_alive()
        # Set a stop so the price feed actually gets called.
        store.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
        assert started.wait(timeout=2.0), "monitor never invoked the price feed"
    finally:
        monitor.stop()
        monitor.join(timeout=2.0)
    assert not monitor.is_alive()
