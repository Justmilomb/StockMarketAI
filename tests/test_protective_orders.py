"""Unit tests for ProtectiveStore + ProtectiveOrder triggering logic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.protective_orders import (
    ProtectiveOrder,
    ProtectiveStore,
    StopKind,
)


def test_stop_loss_triggers_below(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    order = store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    assert order.kind == StopKind.STOP_LOSS
    assert store.evaluate("AAPL", price=99.0) == [order]
    assert store.evaluate("AAPL", price=101.0) == []


def test_take_profit_triggers_above(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    order = store.set_take_profit("MSFT", trigger_price=400.0, quantity=2.0)
    assert store.evaluate("MSFT", price=400.5) == [order]
    assert store.evaluate("MSFT", price=399.0) == []


def test_trailing_stop_ratchets_up(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_trailing_stop(
        "TSLA", distance_pct=10.0, quantity=1.0, anchor_price=200.0,
    )
    # Price climbs — anchor follows, trigger lifts to 0.9 * 220 = 198.
    store.observe_price("TSLA", price=220.0)
    refreshed = store.list_active()[0]
    assert refreshed.anchor_price == pytest.approx(220.0)
    assert refreshed.trigger_price == pytest.approx(198.0)
    # Price dips back to 215 — anchor stays at 220, trigger stays at 198.
    store.observe_price("TSLA", price=215.0)
    refreshed = store.list_active()[0]
    assert refreshed.anchor_price == pytest.approx(220.0)
    assert refreshed.trigger_price == pytest.approx(198.0)
    # Drops below 198 — fires.
    fired = store.evaluate("TSLA", price=197.0)
    assert len(fired) == 1
    assert fired[0].kind == StopKind.TRAILING_STOP


def test_cancel_removes_only_matching_kind(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    store.set_take_profit("AAPL", trigger_price=120.0, quantity=5.0)
    assert store.cancel("AAPL", StopKind.STOP_LOSS) == 1
    remaining = store.list_active()
    assert len(remaining) == 1
    assert remaining[0].kind == StopKind.TAKE_PROFIT


def test_cancel_without_kind_removes_all_for_ticker(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    store.set_take_profit("AAPL", trigger_price=120.0, quantity=5.0)
    store.set_stop_loss("MSFT", trigger_price=300.0, quantity=2.0)
    assert store.cancel("AAPL") == 2
    remaining = store.list_active()
    assert [o.ticker for o in remaining] == ["MSFT"]


def test_adjust_stop_updates_trigger(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    n = store.adjust("AAPL", StopKind.STOP_LOSS, new_price=95.0)
    assert n == 1
    assert store.list_active()[0].trigger_price == 95.0


def test_adjust_trailing_back_solves_anchor(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_trailing_stop(
        "TSLA", distance_pct=10.0, quantity=1.0, anchor_price=200.0,
    )
    # Bumping the trigger up to 189 with distance 10% implies anchor = 210.
    store.adjust("TSLA", StopKind.TRAILING_STOP, new_price=189.0)
    refreshed = store.list_active()[0]
    assert refreshed.trigger_price == pytest.approx(189.0)
    assert refreshed.anchor_price == pytest.approx(210.0)


def test_replacing_existing_kind_overwrites(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    a = store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    b = store.set_stop_loss("AAPL", trigger_price=95.0, quantity=5.0)
    active = store.list_active()
    assert len(active) == 1
    assert active[0].id == b.id
    assert a.id != b.id


def test_persistence_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "po.json"
    s1 = ProtectiveStore(state_path=path)
    s1.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    s1.set_trailing_stop(
        "MSFT", distance_pct=8.0, quantity=2.0, anchor_price=400.0,
    )
    s2 = ProtectiveStore(state_path=path)
    assert {o.ticker for o in s2.list_active()} == {"AAPL", "MSFT"}


def test_gbx_unit_is_passthrough(tmp_path: Path) -> None:
    """LSE tickers come back from yfinance in pence; store keeps the same units."""
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    # User asks for a stop at 250p on a stock currently trading at 260p.
    order = store.set_stop_loss(
        "VOD.L", trigger_price=250.0, quantity=10.0, native_currency="GBp",
    )
    assert order.native_currency == "GBp"
    # Price coming in from fetch_live_prices is also in pence.
    assert store.evaluate("VOD.L", price=249.0) == [order]


def test_zero_or_negative_price_never_fires(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    assert store.evaluate("AAPL", price=0.0) == []
    assert store.evaluate("AAPL", price=-1.0) == []


def test_remove_ids(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    a = store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    store.set_take_profit("MSFT", trigger_price=400.0, quantity=1.0)
    store.remove_ids([a.id])
    remaining = store.list_active()
    assert len(remaining) == 1
    assert remaining[0].ticker == "MSFT"
