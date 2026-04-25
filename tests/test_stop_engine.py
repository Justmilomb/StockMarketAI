"""StopEngine unit tests — persistence, trigger logic, GBX/GBP, fills."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Match the existing tests' sys.path bootstrap (conftest already does it,
# but the repo has a few tests that re-state for safety).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from broker_service import BrokerService
from paper_broker import PaperBroker
from stop_engine import (
    StopEngine,
    build_stop,
    evaluate_stop,
    is_gbx_quoted,
    native_to_unit,
    unit_to_native,
)


# ── helpers ─────────────────────────────────────────────────────────────


def _broker(tmp_path: Path) -> PaperBroker:
    return PaperBroker(
        state_path=tmp_path / "state.json",
        audit_path=tmp_path / "orders.jsonl",
        starting_cash=1_000.0,
        currency="GBP",
    )


def _service(broker: PaperBroker) -> BrokerService:
    svc = BrokerService(config={"broker": {"type": "log"}})
    svc.register_broker("stocks", broker)
    return svc


def _seed_position(broker: PaperBroker, ticker: str, qty: float, price: float, ccy: str = "USD") -> None:
    """Inject a held position by hand — bypasses the order-fill path so
    tests don't depend on yfinance for the setup phase."""
    from paper_broker import _Position
    broker._state.positions[ticker] = _Position(
        quantity=qty, avg_price=price, currency=ccy, cost_basis_acct=price * qty,
    )
    broker._save_state()


# ── unit-conversion helpers (GBX / GBP) ─────────────────────────────────


def test_is_gbx_quoted_handles_london_suffix() -> None:
    assert is_gbx_quoted("VOD.L")
    assert is_gbx_quoted("vod.l")
    assert not is_gbx_quoted("AAPL")
    assert not is_gbx_quoted("VOW.DE")


def test_unit_to_native_converts_gbp_on_london() -> None:
    # £5 on a .L ticker becomes 500 pence
    assert unit_to_native("VOD.L", 5.0, "GBP") == 500.0
    # already pence — pass through
    assert unit_to_native("VOD.L", 500.0, "GBX") == 500.0
    assert unit_to_native("VOD.L", 500.0, "native") == 500.0
    # non-London ticker — never converted
    assert unit_to_native("AAPL", 150.0, "GBP") == 150.0


def test_native_to_unit_round_trip() -> None:
    pence = unit_to_native("BARC.L", 2.50, "GBP")
    assert pence == 250.0
    pounds = native_to_unit("BARC.L", pence, "GBP")
    assert pounds == 2.50


# ── trigger evaluation ──────────────────────────────────────────────────


def test_stop_loss_fires_at_or_below_trigger() -> None:
    stop = build_stop(
        ticker="AAPL", kind="stop_loss", quantity=10, trigger_price=150.0,
    )
    assert evaluate_stop(stop, 150.0)
    assert evaluate_stop(stop, 149.99)
    assert not evaluate_stop(stop, 150.01)
    assert not evaluate_stop(stop, 0)  # missing price never fires


def test_take_profit_fires_at_or_above_trigger() -> None:
    stop = build_stop(
        ticker="AAPL", kind="take_profit", quantity=10, trigger_price=200.0,
    )
    assert evaluate_stop(stop, 200.0)
    assert evaluate_stop(stop, 200.01)
    assert not evaluate_stop(stop, 199.99)


def test_trailing_stop_uses_high_water_mark() -> None:
    stop = build_stop(
        ticker="AAPL", kind="trailing_stop", quantity=10,
        trail_distance=5.0, high_water_mark=110.0,
    )
    # Trigger = 110 - 5 = 105
    assert evaluate_stop(stop, 105.0)
    assert evaluate_stop(stop, 100.0)
    assert not evaluate_stop(stop, 106.0)


def test_trailing_stop_pct_uses_high_water_mark() -> None:
    stop = build_stop(
        ticker="AAPL", kind="trailing_stop", quantity=10,
        trail_distance_pct=10.0, high_water_mark=200.0,
    )
    # Trigger = 200 * 0.9 = 180
    assert evaluate_stop(stop, 180.0)
    assert not evaluate_stop(stop, 180.01)


def test_trailing_stop_without_hwm_does_not_fire() -> None:
    """A freshly-created trailing stop has no HWM yet — must not fire."""
    stop = build_stop(
        ticker="AAPL", kind="trailing_stop", quantity=10, trail_distance_pct=5.0,
    )
    assert stop["high_water_mark"] is None
    assert not evaluate_stop(stop, 50.0)


def test_build_stop_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        build_stop(ticker="AAPL", kind="bogus", quantity=1, trigger_price=10)
    with pytest.raises(ValueError):
        build_stop(ticker="AAPL", kind="stop_loss", quantity=0, trigger_price=10)
    with pytest.raises(ValueError):
        build_stop(ticker="AAPL", kind="stop_loss", quantity=1, trigger_price=0)
    with pytest.raises(ValueError):
        build_stop(ticker="AAPL", kind="trailing_stop", quantity=1)
    with pytest.raises(ValueError):
        build_stop(
            ticker="AAPL", kind="trailing_stop", quantity=1,
            trail_distance_pct=150,  # > 100 is nonsensical
        )


# ── persistence ─────────────────────────────────────────────────────────


def test_paper_broker_persists_active_stops_across_reload(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    audit = tmp_path / "audit.jsonl"
    b1 = PaperBroker(state_path=state_path, audit_path=audit,
                     starting_cash=1_000, currency="GBP")
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=5, trigger_price=140)
    b1.add_stop(s)

    # Re-open from disk — stop must come back.
    b2 = PaperBroker(state_path=state_path, audit_path=audit,
                     starting_cash=1_000, currency="GBP")
    listed = b2.list_stops()
    assert len(listed) == 1
    assert listed[0]["stop_id"] == s["stop_id"]
    assert listed[0]["trigger_price"] == 140.0


def test_remove_stop_returns_value_and_clears_storage(tmp_path: Path) -> None:
    b = _broker(tmp_path)
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=5, trigger_price=140)
    b.add_stop(s)
    assert b.remove_stop(s["stop_id"]) is not None
    assert b.list_stops() == []
    assert b.remove_stop(s["stop_id"]) is None


def test_update_stop_changes_only_supplied_fields(tmp_path: Path) -> None:
    b = _broker(tmp_path)
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=5, trigger_price=140)
    b.add_stop(s)
    updated = b.update_stop(s["stop_id"], {"trigger_price": 145.0})
    assert updated["trigger_price"] == 145.0
    assert updated["quantity"] == 5  # untouched


# ── engine tick (end-to-end with injected price feed) ───────────────────


class _FakeFeed:
    def __init__(self, prices: Dict[str, float] | None = None) -> None:
        self.prices = prices or {}
        self.calls: List[List[str]] = []

    def __call__(self, tickers: List[str]) -> Dict[str, float]:
        self.calls.append(list(tickers))
        return {t: float(self.prices.get(t, 0.0)) for t in tickers}


def test_tick_fires_stop_loss_and_executes_sell(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=10, price=150.0)
    svc = _service(broker)

    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=10, trigger_price=140)
    broker.add_stop(s)

    feed = _FakeFeed({"AAPL": 139.0})
    engine = StopEngine(svc, price_fetcher=feed)
    fired = engine.tick()

    assert len(fired) == 1
    assert fired[0]["stop_id"] == s["stop_id"]
    # Stop removed after firing — second tick is a no-op.
    assert broker.list_stops() == []
    # Position unwound.
    assert broker.get_positions() == []


def test_tick_no_op_when_price_above_stop(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=10, price=150.0)
    svc = _service(broker)
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=10, trigger_price=140)
    broker.add_stop(s)

    feed = _FakeFeed({"AAPL": 160.0})
    engine = StopEngine(svc, price_fetcher=feed)
    assert engine.tick() == []
    assert len(broker.list_stops()) == 1


def test_trailing_stop_walks_high_water_mark_then_fires(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=10, price=100.0)
    svc = _service(broker)
    s = build_stop(
        ticker="AAPL", kind="trailing_stop", quantity=10, trail_distance=5.0,
    )
    broker.add_stop(s)

    feed = _FakeFeed({"AAPL": 110.0})
    engine = StopEngine(svc, price_fetcher=feed)

    # Tick 1: 110 — HWM rises to 110, no fire (trigger 105, price 110)
    assert engine.tick() == []
    persisted = broker.list_stops()[0]
    assert persisted["high_water_mark"] == 110.0

    # Tick 2: 108 — HWM unchanged, no fire (trigger 105, price 108)
    feed.prices["AAPL"] = 108.0
    assert engine.tick() == []
    assert broker.list_stops()[0]["high_water_mark"] == 110.0

    # Tick 3: 104 — fires (price <= 105)
    feed.prices["AAPL"] = 104.0
    fired = engine.tick()
    assert len(fired) == 1
    assert broker.list_stops() == []


def test_take_profit_fires_when_price_above_target(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=10, price=150.0)
    svc = _service(broker)
    s = build_stop(ticker="AAPL", kind="take_profit", quantity=10, trigger_price=200)
    broker.add_stop(s)

    feed = _FakeFeed({"AAPL": 201.0})
    engine = StopEngine(svc, price_fetcher=feed)
    assert len(engine.tick()) == 1


def test_stop_capped_to_held_quantity(tmp_path: Path) -> None:
    """A stale stop on a partially-exited position can't oversell."""
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=3, price=150.0)
    svc = _service(broker)
    # Stop sized for 10 shares but only 3 held
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=10, trigger_price=140)
    broker.add_stop(s)
    feed = _FakeFeed({"AAPL": 139.0})
    engine = StopEngine(svc, price_fetcher=feed)
    fired = engine.tick()
    assert len(fired) == 1
    # Position fully unwound — only 3 shares were sold, not 10.
    assert broker.get_positions() == []


def test_stop_with_no_position_self_removes(tmp_path: Path) -> None:
    """Stop on a ticker with zero held quantity gets cleaned up, not fired."""
    broker = _broker(tmp_path)
    svc = _service(broker)
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=10, trigger_price=140)
    broker.add_stop(s)
    feed = _FakeFeed({"AAPL": 139.0})
    engine = StopEngine(svc, price_fetcher=feed)
    fired = engine.tick()
    # Trigger fired but position is empty — engine cleans up the orphan.
    assert fired == []
    assert broker.list_stops() == []


def test_consume_fired_drains_buffer(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    _seed_position(broker, "AAPL", qty=5, price=150.0)
    svc = _service(broker)
    s = build_stop(ticker="AAPL", kind="stop_loss", quantity=5, trigger_price=140)
    broker.add_stop(s)
    engine = StopEngine(svc, price_fetcher=_FakeFeed({"AAPL": 139.0}))
    engine.tick()
    drained = engine.consume_fired()
    assert len(drained) == 1
    assert engine.consume_fired() == []  # second drain returns empty


# ── GBX / GBP end-to-end ───────────────────────────────────────────────


def test_gbp_unit_translates_to_pence_for_london_ticker(tmp_path: Path) -> None:
    broker = _broker(tmp_path)
    # Yfinance returns VOD.L in pence — seed the position that way too.
    _seed_position(broker, "VOD.L", qty=100, price=80.0, ccy="GBP")
    svc = _service(broker)

    # User thinks "stop at £0.75" — convert via unit helper.
    trigger_pence = unit_to_native("VOD.L", 0.75, "GBP")
    assert trigger_pence == 75.0
    s = build_stop(
        ticker="VOD.L", kind="stop_loss", quantity=100, trigger_price=trigger_pence,
    )
    broker.add_stop(s)

    # Live feed (in pence) prints 74p — should fire.
    feed = _FakeFeed({"VOD.L": 74.0})
    engine = StopEngine(svc, price_fetcher=feed)
    fired = engine.tick()
    assert len(fired) == 1
