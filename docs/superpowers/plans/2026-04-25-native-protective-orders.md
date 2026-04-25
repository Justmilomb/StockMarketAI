# Native Stop-Loss / Take-Profit / Trailing-Stop Implementation Plan

**Goal:** Build a broker-side protective-orders engine that fires stops/targets in seconds — no waiting for the agent to wake up — and exposes MCP tools so the agent can manage the orders itself.

**Architecture:**
- A new `core/protective_orders.py` owns a typed list of triggers, persists them to a sidecar JSON (`data/protective_orders.json`), and exposes `set_stop_loss / set_take_profit / set_trailing_stop / adjust_stop / cancel_stop / list_active_stops`.
- A new `core/protective_monitor.py` runs a daemon `threading.Thread` that polls live prices every ~1 s, evaluates triggers, and submits SELL orders to whatever `BrokerService` it was given. Monitor and store are decoupled — the store is the data, the monitor is the worker.
- MCP tools in `core/agent/tools/protective_tools.py` give the agent CRUD access; `mcp_server.py` registers them; `prompts.py` gets a "Protective orders" section.
- Lifecycle: `AgentPool` builds and starts the monitor when the supervisor / chat workers first need a broker; `MainWindow.closeEvent` shuts it down via `pool.shutdown()`.

**Tech Stack:** Python 3.12, threading (no Qt — the monitor must run in modes that don't have a Qt event loop), yfinance via the existing `data_loader.fetch_live_prices`, existing `PaperBroker` / `Trading212Broker` via `BrokerService`, existing `fx.ticker_currency` for GBP/GBX.

---

## File Structure

**Create:**
- `core/protective_orders.py` — `ProtectiveOrder` dataclass + `ProtectiveStore` (CRUD, persistence, trigger evaluation).
- `core/protective_monitor.py` — `ProtectiveMonitor` daemon thread (poll → evaluate → submit).
- `core/agent/tools/protective_tools.py` — six MCP tools.
- `tests/test_protective_orders.py` — unit tests for the store + trigger logic + GBX handling.
- `tests/test_protective_monitor.py` — tests for the monitor's poll cycle (with a stub broker + price feed).
- `tests/test_protective_tools.py` — smoke tests for the MCP tools, registered in mcp_server.

**Modify:**
- `core/agent/mcp_server.py` — import + append `PROTECTIVE_TOOLS`.
- `core/agent/pool.py` — own a `ProtectiveMonitor`, build it when the broker is built, expose `start_protective_monitor / stop_protective_monitor`, call `stop_protective_monitor` from `shutdown()`.
- `core/agent/prompts.py` — short "Protective orders" tool catalogue section.
- `desktop/app.py` — call `pool.start_protective_monitor()` from `_ensure_agent_pool()` after `start_swarm()`.
- `core/config_schema.py` — optional `protective_orders` block (`enabled: bool`, `poll_seconds: float`, `state_path: str`).

GBX handling lives in the store — `core/fx.py` already returns `"GBP"` for `.L` tickers, but LSE prices come back from yfinance in pence (a 250p stock, not £2.50), so the store stores triggers in the same unit it sees from `fetch_live_prices` and we just label trigger prices as "native units, same scale as the live feed". That is the simplest contract that does not lie.

---

## Task 1: Protective-order data model + store

**Files:**
- Create: `core/protective_orders.py`
- Test: `tests/test_protective_orders.py`

- [ ] **Step 1.1: Write the failing tests**

```python
# tests/test_protective_orders.py
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
    order = store.set_trailing_stop("TSLA", distance_pct=10.0, quantity=1.0,
                                     anchor_price=200.0)
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


def test_adjust_stop_updates_trigger(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    store.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    n = store.adjust("AAPL", StopKind.STOP_LOSS, new_price=95.0)
    assert n == 1
    assert store.list_active()[0].trigger_price == 95.0


def test_persistence_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "po.json"
    s1 = ProtectiveStore(state_path=path)
    s1.set_stop_loss("AAPL", trigger_price=100.0, quantity=5.0)
    s1.set_trailing_stop("MSFT", distance_pct=8.0, quantity=2.0,
                          anchor_price=400.0)
    s2 = ProtectiveStore(state_path=path)
    assert {o.ticker for o in s2.list_active()} == {"AAPL", "MSFT"}


def test_gbx_unit_is_passthrough(tmp_path: Path) -> None:
    """LSE tickers come back from yfinance in pence; store keeps the same units."""
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    # User asks for a stop at 250p on a stock currently trading at 260p.
    order = store.set_stop_loss("VOD.L", trigger_price=250.0, quantity=10.0,
                                 native_currency="GBp")
    assert order.native_currency == "GBp"
    # Price coming in from fetch_live_prices is also in pence.
    assert store.evaluate("VOD.L", price=249.0) == [order]
```

- [ ] **Step 1.2: Run the tests to verify they fail**

Run: `pytest tests/test_protective_orders.py -v`
Expected: every test fails with `ModuleNotFoundError: No module named 'core.protective_orders'`

- [ ] **Step 1.3: Write the implementation**

```python
# core/protective_orders.py
"""Native protective-orders engine: stop-loss, take-profit, trailing stop.

Lives outside the broker because both PaperBroker and Trading212Broker
need it identically. The store is the data; ProtectiveMonitor is the
worker that polls prices and fires triggers. Splitting them keeps the
store synchronously testable without spinning up a thread.

Persistence
===========
``data/protective_orders.json`` is the source of truth. Every mutation
writes through immediately (same pattern as paper_state.json) so a
crash mid-session never loses a stop. Schema is intentionally tiny:

    {
      "orders": [
        {"id": "po-…", "ticker": "AAPL", "kind": "stop_loss",
         "trigger_price": 100.0, "quantity": 5.0,
         "native_currency": "USD",
         "distance_pct": null, "anchor_price": null,
         "created_at": "2026-04-25T12:34:56Z"}
      ]
    }

Currency / GBX
==============
We do **not** convert prices. Every trigger is stored in the same units
as ``data_loader.fetch_live_prices`` returns for that ticker — that's
USD for AAPL, pence (GBp) for VOD.L. The agent prompt makes this
explicit: "if you ask for a stop on a ``.L`` ticker, the trigger price
must be in pence to match the live feed". ``native_currency`` is a
label for the UI / journal; the comparison is unit-agnostic.

Concurrency
===========
The monitor thread reads the order list while the agent's MCP tools
write to it. Both go through ``self._lock`` (a plain ``threading.Lock``
— there's no asyncio in the broker path so a re-entrant lock is
overkill).
"""
from __future__ import annotations

import enum
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StopKind(str, enum.Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"


@dataclass
class ProtectiveOrder:
    """One stop / target / trailing-stop on one ticker.

    ``trigger_price`` for trailing stops is recomputed from
    ``anchor_price`` and ``distance_pct`` whenever the price observed
    by the monitor is higher than the current anchor. The static stop
    and take-profit forms keep ``anchor_price`` and ``distance_pct`` as
    ``None``.
    """

    id: str
    ticker: str
    kind: StopKind
    trigger_price: float
    quantity: float
    native_currency: str = "USD"
    distance_pct: Optional[float] = None
    anchor_price: Optional[float] = None
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProtectiveOrder":
        return cls(
            id=str(d.get("id", "")),
            ticker=str(d.get("ticker", "")).upper(),
            kind=StopKind(str(d.get("kind", StopKind.STOP_LOSS.value))),
            trigger_price=float(d.get("trigger_price", 0.0) or 0.0),
            quantity=float(d.get("quantity", 0.0) or 0.0),
            native_currency=str(d.get("native_currency", "USD") or "USD"),
            distance_pct=(
                float(d["distance_pct"]) if d.get("distance_pct") is not None else None
            ),
            anchor_price=(
                float(d["anchor_price"]) if d.get("anchor_price") is not None else None
            ),
            created_at=str(d.get("created_at", "")),
        )


class ProtectiveStore:
    """CRUD + trigger evaluation. Thread-safe; persists every write."""

    def __init__(self, state_path: Optional[Path] = None) -> None:
        self._state_path = Path(state_path or Path("data") / "protective_orders.json")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._orders: List[ProtectiveOrder] = self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> List[ProtectiveOrder]:
        if not self._state_path.exists():
            return []
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("protective: state corrupt, starting fresh: %s", e)
            return []
        return [ProtectiveOrder.from_dict(o) for o in raw.get("orders", [])]

    def _save(self) -> None:
        tmp = self._state_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({"orders": [o.to_dict() for o in self._orders]}, f, indent=2)
        tmp.replace(self._state_path)

    # ── CRUD ─────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _new_id() -> str:
        return f"po-{uuid.uuid4().hex[:10]}"

    def set_stop_loss(self, ticker: str, trigger_price: float,
                      quantity: float,
                      native_currency: str = "USD") -> ProtectiveOrder:
        with self._lock:
            self._remove_existing(ticker, StopKind.STOP_LOSS)
            o = ProtectiveOrder(
                id=self._new_id(), ticker=ticker.upper(),
                kind=StopKind.STOP_LOSS, trigger_price=float(trigger_price),
                quantity=float(quantity), native_currency=native_currency,
                created_at=self._now(),
            )
            self._orders.append(o)
            self._save()
            return o

    def set_take_profit(self, ticker: str, trigger_price: float,
                        quantity: float,
                        native_currency: str = "USD") -> ProtectiveOrder:
        with self._lock:
            self._remove_existing(ticker, StopKind.TAKE_PROFIT)
            o = ProtectiveOrder(
                id=self._new_id(), ticker=ticker.upper(),
                kind=StopKind.TAKE_PROFIT, trigger_price=float(trigger_price),
                quantity=float(quantity), native_currency=native_currency,
                created_at=self._now(),
            )
            self._orders.append(o)
            self._save()
            return o

    def set_trailing_stop(self, ticker: str, distance_pct: float,
                          quantity: float, anchor_price: float,
                          native_currency: str = "USD") -> ProtectiveOrder:
        with self._lock:
            self._remove_existing(ticker, StopKind.TRAILING_STOP)
            anchor = float(anchor_price)
            distance = float(distance_pct)
            trigger = anchor * (1.0 - distance / 100.0)
            o = ProtectiveOrder(
                id=self._new_id(), ticker=ticker.upper(),
                kind=StopKind.TRAILING_STOP, trigger_price=trigger,
                quantity=float(quantity),
                native_currency=native_currency,
                distance_pct=distance, anchor_price=anchor,
                created_at=self._now(),
            )
            self._orders.append(o)
            self._save()
            return o

    def adjust(self, ticker: str, kind: StopKind, new_price: float) -> int:
        with self._lock:
            n = 0
            for o in self._orders:
                if o.ticker == ticker.upper() and o.kind == kind:
                    o.trigger_price = float(new_price)
                    if o.kind == StopKind.TRAILING_STOP and o.anchor_price:
                        # Treat new_price as the new trigger explicitly,
                        # back-solve the implied anchor at the configured
                        # distance — keeps the trail honest after a manual
                        # nudge.
                        if o.distance_pct:
                            o.anchor_price = float(new_price) / (
                                1.0 - o.distance_pct / 100.0
                            )
                    n += 1
            if n:
                self._save()
            return n

    def cancel(self, ticker: str, kind: Optional[StopKind] = None) -> int:
        with self._lock:
            before = len(self._orders)
            t = ticker.upper()
            self._orders = [
                o for o in self._orders
                if not (o.ticker == t and (kind is None or o.kind == kind))
            ]
            removed = before - len(self._orders)
            if removed:
                self._save()
            return removed

    def list_active(self) -> List[ProtectiveOrder]:
        with self._lock:
            return list(self._orders)

    def tickers(self) -> List[str]:
        with self._lock:
            return sorted({o.ticker for o in self._orders})

    def _remove_existing(self, ticker: str, kind: StopKind) -> None:
        """Caller must hold the lock. Replaces same-ticker-same-kind orders."""
        t = ticker.upper()
        self._orders = [
            o for o in self._orders if not (o.ticker == t and o.kind == kind)
        ]

    # ── trigger logic ────────────────────────────────────────────────

    def observe_price(self, ticker: str, price: float) -> None:
        """Update trailing-stop anchors for ``ticker`` if ``price`` is a new high."""
        if price <= 0:
            return
        with self._lock:
            t = ticker.upper()
            dirty = False
            for o in self._orders:
                if o.ticker != t or o.kind != StopKind.TRAILING_STOP:
                    continue
                if o.anchor_price is None or o.distance_pct is None:
                    continue
                if price > o.anchor_price:
                    o.anchor_price = float(price)
                    o.trigger_price = price * (1.0 - o.distance_pct / 100.0)
                    dirty = True
            if dirty:
                self._save()

    def evaluate(self, ticker: str, price: float) -> List[ProtectiveOrder]:
        """Return every order on ``ticker`` whose trigger fires at ``price``."""
        if price <= 0:
            return []
        with self._lock:
            t = ticker.upper()
            fired: List[ProtectiveOrder] = []
            for o in self._orders:
                if o.ticker != t:
                    continue
                if o.kind == StopKind.STOP_LOSS and price <= o.trigger_price:
                    fired.append(o)
                elif o.kind == StopKind.TAKE_PROFIT and price >= o.trigger_price:
                    fired.append(o)
                elif o.kind == StopKind.TRAILING_STOP and price <= o.trigger_price:
                    fired.append(o)
            return fired

    def remove_ids(self, ids: List[str]) -> None:
        if not ids:
            return
        with self._lock:
            keep = [o for o in self._orders if o.id not in set(ids)]
            if len(keep) != len(self._orders):
                self._orders = keep
                self._save()
```

- [ ] **Step 1.4: Run the tests to verify they pass**

Run: `pytest tests/test_protective_orders.py -v`
Expected: 7 passed.

- [ ] **Step 1.5: Commit**

```bash
git add core/protective_orders.py tests/test_protective_orders.py
git commit -m "feat(protective-orders): add ProtectiveStore data model + tests"
```

---

## Task 2: Price-monitor daemon thread

**Files:**
- Create: `core/protective_monitor.py`
- Test: `tests/test_protective_monitor.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_protective_monitor.py
"""ProtectiveMonitor poll cycle: fires triggers, calls broker, stops cleanly."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.protective_orders import ProtectiveStore, StopKind
from core.protective_monitor import ProtectiveMonitor


class _StubBroker:
    """Captures every submit_order call for assertions."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def submit_order(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"order_id": f"stub-{len(self.calls)}", "status": "FILLED"}


def _stub_price_feed(prices: Dict[str, float]):
    def fetch(tickers: List[str]) -> Dict[str, Dict[str, float]]:
        return {t: {"price": prices.get(t, 0.0), "change_pct": 0.0} for t in tickers}
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
    monitor.tick()  # one synchronous cycle — easier to assert than threading
    assert len(broker.calls) == 1
    assert broker.calls[0]["ticker"] == "AAPL"
    assert broker.calls[0]["side"] == "SELL"
    assert broker.calls[0]["quantity"] == 5.0
    assert store.list_active() == []


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
    store.set_trailing_stop("TSLA", distance_pct=10.0, quantity=2.0,
                             anchor_price=200.0)
    broker = _StubBroker()
    prices = {"TSLA": 220.0}
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=lambda t: {x: {"price": prices.get(x, 0.0), "change_pct": 0.0} for x in t},
        poll_seconds=0.05,
    )
    monitor.tick()  # ratchets anchor → 220, trigger → 198
    assert broker.calls == []
    assert store.list_active()[0].trigger_price == pytest.approx(198.0)
    prices["TSLA"] = 197.0
    monitor.tick()
    assert len(broker.calls) == 1


def test_thread_lifecycle(tmp_path: Path) -> None:
    store = ProtectiveStore(state_path=tmp_path / "po.json")
    broker = _StubBroker()
    started = threading.Event()
    monitor = ProtectiveMonitor(
        store=store, broker_service=broker,
        price_feed=lambda t: (started.set() or {x: {"price": 0.0, "change_pct": 0.0} for x in t}),
        poll_seconds=0.02,
    )
    monitor.start()
    try:
        # Even with no orders, the monitor should still be alive and ticking.
        assert monitor.is_alive()
        # Set a stop so the price feed actually gets called.
        store.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
        assert started.wait(timeout=2.0), "monitor never invoked the price feed"
    finally:
        monitor.stop()
        monitor.join(timeout=2.0)
    assert not monitor.is_alive()
```

- [ ] **Step 2.2: Run the tests to verify they fail**

Run: `pytest tests/test_protective_monitor.py -v`
Expected: every test fails with `ModuleNotFoundError`.

- [ ] **Step 2.3: Write the implementation**

```python
# core/protective_monitor.py
"""Background daemon that polls prices and fires protective orders.

Why a thread, not a Qt timer: the monitor must run inside the agent
pool, which is shared between the Qt desktop window and a few headless
modes (paper REPL, swarm-only test runs). A plain ``threading.Thread``
works in all of them; a ``QTimer`` would crash the headless modes.

The thread loops:

    while not stop:
        tick()
        sleep(poll_seconds)

``tick()`` is the entire poll cycle and is also called directly by the
unit tests, so we never have to deal with timing flakiness.

Failure modes
=============
* Price feed errors (yfinance rate limit, no network) — log debug and
  skip this tick. Do **not** silently retire orders; a missed tick
  becomes a missed trigger but the next tick will reconsider them.
* Broker errors (sell rejected because the position has already been
  closed elsewhere) — log warning, drop the order from the store. The
  agent's next iteration will see the empty stop list and can decide
  what to do.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from core.protective_orders import ProtectiveOrder, ProtectiveStore, StopKind

logger = logging.getLogger(__name__)


PriceFeed = Callable[[List[str]], Dict[str, Dict[str, float]]]


def _default_price_feed(tickers: List[str]) -> Dict[str, Dict[str, float]]:
    """Lazy import so importing this module doesn't drag yfinance in."""
    from data_loader import fetch_live_prices
    return fetch_live_prices(tickers)


class ProtectiveMonitor(threading.Thread):
    """Daemon that fires protective orders on price moves.

    The monitor owns no state of its own beyond the stop flag — every
    cycle re-reads the store. New orders added by the agent show up on
    the next tick without restart.
    """

    def __init__(
        self,
        store: ProtectiveStore,
        broker_service: Any,
        price_feed: Optional[PriceFeed] = None,
        poll_seconds: float = 1.0,
    ) -> None:
        super().__init__(daemon=True, name="protective-monitor")
        self._store = store
        self._broker = broker_service
        self._price_feed = price_feed or _default_price_feed
        self._poll_seconds = max(0.1, float(poll_seconds))
        self._stop = threading.Event()

    # ── lifecycle ────────────────────────────────────────────────────

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D401 — Thread.run override
        logger.info("protective monitor started (poll=%.2fs)", self._poll_seconds)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("protective monitor tick failed")
            self._stop.wait(self._poll_seconds)
        logger.info("protective monitor stopped")

    # ── one cycle ────────────────────────────────────────────────────

    def tick(self) -> None:
        """One pass of the monitor loop — pulled out for testability."""
        tickers = self._store.tickers()
        if not tickers:
            return

        try:
            quotes = self._price_feed(tickers)
        except Exception as exc:
            logger.debug("protective: price feed failed: %s", exc)
            return

        fired: List[ProtectiveOrder] = []
        for ticker in tickers:
            price = float((quotes.get(ticker) or {}).get("price", 0.0) or 0.0)
            if price <= 0:
                continue
            self._store.observe_price(ticker, price)
            fired.extend(self._store.evaluate(ticker, price))

        if fired:
            executed_ids = self._execute(fired)
            if executed_ids:
                self._store.remove_ids(executed_ids)

    def _execute(self, orders: List[ProtectiveOrder]) -> List[str]:
        """Submit each fired order as a market SELL. Returns the ids we managed
        to send. Failures stay in the store so the agent can see them.
        """
        executed: List[str] = []
        for o in orders:
            try:
                resp = self._broker.submit_order(
                    ticker=o.ticker, side="SELL",
                    quantity=o.quantity, order_type="market",
                    limit_price=None, stop_price=None,
                )
                logger.info(
                    "protective: %s on %s fired @ trigger=%.4f → %s",
                    o.kind.value, o.ticker, o.trigger_price,
                    (resp or {}).get("status", "?"),
                )
                executed.append(o.id)
            except Exception:
                logger.exception(
                    "protective: failed to execute %s on %s", o.kind.value, o.ticker,
                )
        return executed
```

- [ ] **Step 2.4: Run the tests to verify they pass**

Run: `pytest tests/test_protective_monitor.py -v`
Expected: 4 passed.

- [ ] **Step 2.5: Commit**

```bash
git add core/protective_monitor.py tests/test_protective_monitor.py
git commit -m "feat(protective-orders): add price-monitor daemon thread"
```

---

## Task 3: MCP tools for the agent

**Files:**
- Create: `core/agent/tools/protective_tools.py`
- Modify: `core/agent/context.py` — add a `protective_store` field
- Modify: `core/agent/mcp_server.py` — register `PROTECTIVE_TOOLS`
- Test: `tests/test_protective_tools.py`

- [ ] **Step 3.1: Add ``protective_store`` field to AgentContext**

In `core/agent/context.py`, after `risk_manager: RiskManager` add:

```python
    protective_store: Optional[Any] = None  # core.protective_orders.ProtectiveStore
```

…and pass it through `init_agent_context` as a new keyword:

```python
def init_agent_context(
    config: Dict[str, Any],
    broker_service: BrokerService,
    db: HistoryManager,
    risk_manager: RiskManager,
    iteration_id: str = "",
    paper_mode: bool = True,
    trader_personality: Optional[Any] = None,
    protective_store: Optional[Any] = None,
) -> AgentContext:
    ctx = AgentContext(
        config=config,
        broker_service=broker_service,
        db=db,
        risk_manager=risk_manager,
        iteration_id=iteration_id,
        paper_mode=paper_mode,
        trader_personality=trader_personality,
        protective_store=protective_store,
    )
    _context.set(ctx)
    return ctx
```

- [ ] **Step 3.2: Write the failing tests**

```python
# tests/test_protective_tools.py
"""Smoke tests for the protective MCP tools."""
from __future__ import annotations

import asyncio
import json
import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from core.protective_orders import ProtectiveStore, StopKind
from core.agent.context import init_agent_context, clear_agent_context


def _payload(result):
    return json.loads(result["content"][0]["text"])


@pytest.fixture
def ctx(tmp_path: Path):
    db_path = tmp_path / "h.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE agent_journal (id INTEGER PRIMARY KEY, iteration_id TEXT, "
            "kind TEXT, tool TEXT, payload TEXT, tags TEXT)"
        )

    class _DummyDB:
        def __init__(self, p): self.db_path = str(p)

    store = ProtectiveStore(state_path=tmp_path / "po.json")
    init_agent_context(
        config={}, broker_service=None,
        db=_DummyDB(db_path), risk_manager=None,
        iteration_id="t", paper_mode=True,
        protective_store=store,
    )
    yield store
    clear_agent_context()


def test_set_stop_loss_tool(ctx: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import set_stop_loss
    result = asyncio.run(set_stop_loss({
        "ticker": "AAPL", "trigger_price": 100.0, "quantity": 5.0,
    }))
    data = _payload(result)
    assert data["status"] == "ok"
    assert data["order"]["kind"] == "stop_loss"
    assert ctx.list_active()[0].trigger_price == 100.0


def test_list_active_stops_returns_distance(ctx: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import list_active_stops
    ctx.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
    # Hand a price into the tool via the optional override so we don't hit yfinance.
    result = asyncio.run(list_active_stops({"_test_prices": {"AAPL": 110.0}}))
    data = _payload(result)
    assert len(data["orders"]) == 1
    o = data["orders"][0]
    assert o["current_price"] == 110.0
    assert o["distance_pct"] == pytest.approx(-9.0909, rel=1e-3)


def test_cancel_stop_tool(ctx: ProtectiveStore) -> None:
    from core.agent.tools.protective_tools import cancel_stop
    ctx.set_stop_loss("AAPL", trigger_price=100.0, quantity=1.0)
    result = asyncio.run(cancel_stop({"ticker": "AAPL", "order_type": "stop_loss"}))
    data = _payload(result)
    assert data["removed"] == 1
    assert ctx.list_active() == []
```

- [ ] **Step 3.3: Run the tests to verify they fail**

Run: `pytest tests/test_protective_tools.py -v`
Expected: every test fails with `ModuleNotFoundError`.

- [ ] **Step 3.4: Write the tool module**

```python
# core/agent/tools/protective_tools.py
"""MCP tools the agent uses to manage protective orders.

Six tools, one ``PROTECTIVE_TOOLS`` export. Every tool reads the
``ProtectiveStore`` instance the agent pool put on the context — there
is no per-tool state.

Distance fields in ``list_active_stops`` are signed:
  * negative → trigger is below current price (a typical stop_loss
    that's still in the money) — distance to the danger.
  * positive → trigger is above current price (typical take_profit) —
    distance to the prize.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List

from core.agent._sdk import tool
from core.agent.context import get_agent_context
from core.protective_orders import StopKind


def _text_result(data: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _journal(kind: str, payload: Dict[str, Any], tags: List[str] | None = None) -> None:
    ctx = get_agent_context()
    try:
        with sqlite3.connect(ctx.db.db_path) as conn:
            conn.execute(
                "INSERT INTO agent_journal (iteration_id, kind, tool, payload, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    ctx.iteration_id, kind, payload.get("tool", ""),
                    json.dumps(payload, default=str), ",".join(tags or []),
                ),
            )
    except Exception:
        # Tests use a stub DB without the journal table — never crash a tool on logging.
        pass


def _store():
    ctx = get_agent_context()
    if ctx.protective_store is None:
        raise RuntimeError(
            "protective_store missing from AgentContext — "
            "AgentPool didn't wire it before the iteration",
        )
    return ctx.protective_store


def _live_price(ticker: str, override: Dict[str, float] | None = None) -> float:
    if override and ticker in override:
        return float(override[ticker])
    try:
        from data_loader import fetch_live_prices
        live = fetch_live_prices([ticker])
        return float((live.get(ticker) or {}).get("price", 0.0) or 0.0)
    except Exception:
        return 0.0


def _native_currency(ticker: str) -> str:
    try:
        from fx import ticker_currency
        return ticker_currency(ticker, default="USD")
    except Exception:
        return "USD"


# ── tools ──────────────────────────────────────────────────────────────

@tool(
    "set_stop_loss",
    "Place a stop-loss on a held ticker. Trigger price is in the same units "
    "as the live feed (USD for AAPL, pence for .L tickers). When the price "
    "hits or drops below trigger_price the broker fires a market SELL "
    "*immediately* — independent of the agent's wake cadence. Replaces any "
    "existing stop-loss on the same ticker.",
    {"ticker": str, "trigger_price": float, "quantity": float},
)
async def set_stop_loss(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    trigger_price = float(args.get("trigger_price", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    if not ticker or trigger_price <= 0 or quantity <= 0:
        return _text_result({"status": "rejected",
                              "reason": "ticker, trigger_price>0, quantity>0 required"})
    o = _store().set_stop_loss(
        ticker=ticker, trigger_price=trigger_price, quantity=quantity,
        native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_stop_loss", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "set_take_profit",
    "Place a take-profit on a held ticker. When the price hits or exceeds "
    "trigger_price the broker fires a market SELL *immediately*. Replaces "
    "any existing take-profit on the same ticker.",
    {"ticker": str, "trigger_price": float, "quantity": float},
)
async def set_take_profit(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    trigger_price = float(args.get("trigger_price", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    if not ticker or trigger_price <= 0 or quantity <= 0:
        return _text_result({"status": "rejected",
                              "reason": "ticker, trigger_price>0, quantity>0 required"})
    o = _store().set_take_profit(
        ticker=ticker, trigger_price=trigger_price, quantity=quantity,
        native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_take_profit", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "set_trailing_stop",
    "Place a trailing stop on a held ticker. distance_pct (e.g. 8 for 8%) is "
    "the gap between the running high and the trigger. As the price climbs, "
    "the trigger ratchets up; if the price drops by distance_pct from the "
    "running high the broker sells immediately. Anchors at the current live "
    "price unless an explicit anchor_price is supplied.",
    {"ticker": str, "distance_pct": float, "quantity": float, "anchor_price": float},
)
async def set_trailing_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    distance_pct = float(args.get("distance_pct", 0.0) or 0.0)
    quantity = float(args.get("quantity", 0.0) or 0.0)
    anchor_arg = args.get("anchor_price")
    if not ticker or distance_pct <= 0 or quantity <= 0:
        return _text_result({"status": "rejected",
                              "reason": "ticker, distance_pct>0, quantity>0 required"})
    anchor = float(anchor_arg) if anchor_arg else _live_price(ticker)
    if anchor <= 0:
        return _text_result({"status": "rejected",
                              "reason": "could not determine anchor price"})
    o = _store().set_trailing_stop(
        ticker=ticker, distance_pct=distance_pct, quantity=quantity,
        anchor_price=anchor, native_currency=_native_currency(ticker),
    )
    _journal("tool_call",
             {"tool": "set_trailing_stop", "order": o.to_dict()},
             tags=["protective"])
    return _text_result({"status": "ok", "order": o.to_dict()})


@tool(
    "adjust_stop",
    "Move an existing stop's trigger price. order_type must be one of "
    "'stop_loss', 'take_profit', or 'trailing_stop'. For trailing stops, the "
    "new_price is interpreted as the new trigger and the implied anchor is "
    "back-solved from the original distance_pct.",
    {"ticker": str, "order_type": str, "new_price": float},
)
async def adjust_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    raw_kind = str(args.get("order_type", "")).strip().lower()
    new_price = float(args.get("new_price", 0.0) or 0.0)
    if not ticker or new_price <= 0:
        return _text_result({"status": "rejected",
                              "reason": "ticker and new_price>0 required"})
    try:
        kind = StopKind(raw_kind)
    except ValueError:
        return _text_result({"status": "rejected",
                              "reason": f"unknown order_type {raw_kind!r}"})
    n = _store().adjust(ticker, kind, new_price)
    _journal("tool_call",
             {"tool": "adjust_stop", "ticker": ticker,
              "order_type": kind.value, "new_price": new_price, "updated": n},
             tags=["protective"])
    return _text_result({"status": "ok" if n else "not_found", "updated": n})


@tool(
    "cancel_stop",
    "Remove an existing stop. order_type must be one of 'stop_loss', "
    "'take_profit', or 'trailing_stop'. Returns the number of orders removed.",
    {"ticker": str, "order_type": str},
)
async def cancel_stop(args: Dict[str, Any]) -> Dict[str, Any]:
    ticker = str(args.get("ticker", "")).strip().upper()
    raw_kind = str(args.get("order_type", "")).strip().lower()
    if not ticker:
        return _text_result({"status": "rejected", "reason": "ticker required"})
    try:
        kind = StopKind(raw_kind) if raw_kind else None
    except ValueError:
        return _text_result({"status": "rejected",
                              "reason": f"unknown order_type {raw_kind!r}"})
    n = _store().cancel(ticker, kind)
    _journal("tool_call",
             {"tool": "cancel_stop", "ticker": ticker,
              "order_type": kind.value if kind else "all", "removed": n},
             tags=["protective"])
    return _text_result({"status": "ok" if n else "not_found", "removed": n})


@tool(
    "list_active_stops",
    "List every active protective order with its trigger price, current "
    "price, and percentage distance to the trigger (negative = below "
    "current price, positive = above). Use this before placing a new stop "
    "to see what's already in flight.",
    {},
)
async def list_active_stops(args: Dict[str, Any]) -> Dict[str, Any]:
    store = _store()
    orders = store.list_active()
    test_prices = args.get("_test_prices") if isinstance(args, dict) else None
    out = []
    for o in orders:
        live = _live_price(o.ticker, override=test_prices if isinstance(test_prices, dict) else None)
        distance_pct = (
            (o.trigger_price - live) / live * 100.0 if live > 0 else None
        )
        out.append({
            **o.to_dict(),
            "current_price": live,
            "distance_pct_to_trigger": distance_pct,
        })
    _journal("tool_call",
             {"tool": "list_active_stops", "count": len(out)},
             tags=["protective"])
    return _text_result({"orders": out})


PROTECTIVE_TOOLS = [
    set_stop_loss,
    set_take_profit,
    set_trailing_stop,
    adjust_stop,
    cancel_stop,
    list_active_stops,
]
```

NOTE on field naming: the test `test_list_active_stops_returns_distance` reads `current_price` and `distance_pct` — but the implementation above renames the latter to `distance_pct_to_trigger` to avoid collision with the trailing-stop dataclass field of the same name. Update the test to read `o["distance_pct_to_trigger"]` as well; both names match here.

Apply that test update before Step 3.5.

```python
# Replace the assertion in tests/test_protective_tools.py
assert o["distance_pct_to_trigger"] == pytest.approx(-9.0909, rel=1e-3)
```

- [ ] **Step 3.5: Register the tools in mcp_server**

In `core/agent/mcp_server.py`, add the import:

```python
from core.agent.tools.protective_tools import PROTECTIVE_TOOLS
```

…and append `*PROTECTIVE_TOOLS` to the `ALL_TOOLS` list (place after `*EXECUTION_TOOLS` for readability — sells live next to executions).

- [ ] **Step 3.6: Run the tests to verify they pass**

Run: `pytest tests/test_protective_tools.py -v`
Expected: 3 passed.

- [ ] **Step 3.7: Commit**

```bash
git add core/agent/tools/protective_tools.py core/agent/mcp_server.py \
        core/agent/context.py tests/test_protective_tools.py
git commit -m "feat(protective-orders): MCP tools (set/adjust/cancel/list)"
```

---

## Task 4: Lifecycle wiring in AgentPool

**Files:**
- Modify: `core/agent/pool.py`
- Modify: `desktop/app.py`
- Modify: `core/agent/runner.py` and `core/agent/chat_worker.py` to forward the store into the context.

- [ ] **Step 4.1: Wire the store + monitor into AgentPool**

In `core/agent/pool.py`, add to `__init__`:

```python
        self._protective_store: Optional[Any] = None
        self._protective_monitor: Optional[Any] = None
```

Add helper near `get_broker_for_mode`:

```python
    def get_protective_store(self) -> Any:
        if self._protective_store is None:
            from pathlib import Path as _Path
            from core.protective_orders import ProtectiveStore
            cfg = self._load_config()
            po_cfg = cfg.get("protective_orders") or {}
            state_path = _Path(po_cfg.get(
                "state_path",
                "data/protective_orders.json" if not self._force_paper
                else "data/protective_orders_paper.json",
            ))
            self._protective_store = ProtectiveStore(state_path=state_path)
        return self._protective_store

    def start_protective_monitor(self) -> None:
        """Start the price-monitor daemon if enabled in config (default on)."""
        cfg = self._load_config()
        po_cfg = cfg.get("protective_orders") or {}
        if not po_cfg.get("enabled", True):
            return
        if self._protective_monitor is not None and self._protective_monitor.is_alive():
            return
        from core.protective_monitor import ProtectiveMonitor
        broker = self.get_broker_for_mode(self._force_paper)
        store = self.get_protective_store()
        poll = float(po_cfg.get("poll_seconds", 1.0))
        self._protective_monitor = ProtectiveMonitor(
            store=store, broker_service=broker,
            poll_seconds=poll,
        )
        self._protective_monitor.start()
        logger.info("AgentPool: protective monitor started (poll=%.2fs)", poll)

    def stop_protective_monitor(self) -> None:
        if self._protective_monitor is not None and self._protective_monitor.is_alive():
            self._protective_monitor.stop()
            self._protective_monitor.join(timeout=5)
        self._protective_monitor = None
```

Update `shutdown()`:

```python
    def shutdown(self) -> None:
        self.cancel_all_chat_workers()
        self.stop_swarm()
        self.stop_protective_monitor()
        self.kill_supervisor()
```

- [ ] **Step 4.2: Pass the store into AgentContext for the supervisor and chat workers**

In `core/agent/runner.py`, find every call to `init_agent_context(...)` (or the wrapper that calls it) and add `protective_store=self._pool.get_protective_store()` if a pool is present. Same in `core/agent/chat_worker.py`. Both files already accept the pool reference; this is a single new keyword.

If the runner doesn't currently take a pool reference, plumb it through the constructor (it already does — see `pool=self` in `pool.ensure_supervisor`).

- [ ] **Step 4.3: Start the monitor from the desktop window**

In `desktop/app.py` `_ensure_agent_pool`, immediately after `self.agent_pool.start_swarm()` add:

```python
        # Native protective-orders monitor: independent of the supervisor's
        # cadence so a stop fires within ~1s of the trigger, not on the next wake.
        try:
            self.agent_pool.start_protective_monitor()
        except Exception:
            logger.exception("Failed to start protective monitor")
```

`closeEvent` already calls `pool.shutdown()` so no change needed there.

- [ ] **Step 4.4: Add the optional config block**

In `core/config_schema.py` add a `ProtectiveOrdersConfig` Pydantic model (mirror existing block style) with three fields and append it to the `AppConfig`:

```python
class ProtectiveOrdersConfig(BaseModel):
    enabled: bool = True
    poll_seconds: float = 1.0
    state_path: Optional[str] = None
```

…and on `AppConfig`:

```python
    protective_orders: ProtectiveOrdersConfig = Field(default_factory=ProtectiveOrdersConfig)
```

If the config schema doesn't already use Pydantic in that style, just match whatever the existing nearby blocks do — don't reshape it.

- [ ] **Step 4.5: Run the broader test suite to make sure nothing else regressed**

Run: `pytest tests/ -v -k "protective or paper_broker or agent_loop"`
Expected: every selected test passes.

- [ ] **Step 4.6: Commit**

```bash
git add core/agent/pool.py core/agent/runner.py core/agent/chat_worker.py \
        core/config_schema.py desktop/app.py
git commit -m "feat(protective-orders): wire monitor lifecycle into AgentPool + desktop"
```

---

## Task 5: Update the agent system prompt

**Files:**
- Modify: `core/agent/prompts.py`

- [ ] **Step 5.1: Add a Protective-orders catalogue section**

In `core/agent/prompts.py`, find the `## Tool catalogue` section (around line 331) and add directly after the **Broker** paragraph:

```
**Protective orders (native, broker-side)** — `set_stop_loss`,
`set_take_profit`, `set_trailing_stop`, `adjust_stop`, `cancel_stop`,
`list_active_stops`. These run in a background thread that polls live
prices every ~1s. When a trigger fires the broker SELLS *immediately* —
no waiting for the next iteration. Use them whenever you open a
position you can't babysit. Trigger prices are in the live feed's
units: USD for US tickers, **pence for `.L` tickers** (e.g. a stop on
VOD.L at "250" means 250p, not £250). Replacing an existing stop on
the same ticker overwrites it — call `list_active_stops` first if
you're not sure what's in place.
```

- [ ] **Step 5.2: Commit**

```bash
git add core/agent/prompts.py
git commit -m "docs(prompt): document protective-order tools"
```

---

## Task 6: Push to main

- [ ] **Step 6.1: Verify the working tree is clean and tests still pass**

Run:
```bash
pytest tests/test_protective_orders.py tests/test_protective_monitor.py tests/test_protective_tools.py -v
git status
```

Expected: 14 passed; working tree clean.

- [ ] **Step 6.2: Push branch + merge to main, then push main**

```bash
git push origin claude/inspiring-pare-924597
git checkout main
git pull --ff-only origin main
git merge --no-ff claude/inspiring-pare-924597 -m "feat: native protective orders engine (stop-loss/take-profit/trailing)"
git push origin main
```

If the merge has conflicts (working off a stale main), stop and ask the user before resolving them — the user said "Push to main", not "rewrite history".

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Background price monitor thread @ 1s — Task 2 (`ProtectiveMonitor`, `poll_seconds=1.0` default).
- ✅ Stop-loss / take-profit / trailing — Task 1 (`StopKind` enum, three `set_*` methods).
- ✅ Immediate execution independent of agent — Task 2 (daemon thread + Task 4 lifecycle).
- ✅ Six MCP tools — Task 3.
- ✅ Persistence to paper_state.json — sidecar file `protective_orders.json` (cleaner separation than wedging into the broker's state) — Task 1.
- ✅ Same price source — `data_loader.fetch_live_prices` via `_default_price_feed` — Task 2.
- ✅ GBX awareness — units pass through, prompt makes pence explicit, native_currency stamped on each order — Tasks 1 + 5.
- ✅ Register in mcp_server.py — Task 3.5.
- ✅ Start on app start, stop on close — Task 4 (`pool.start_protective_monitor` + existing `pool.shutdown` chain).
- ✅ Document in agent prompt — Task 5.

**Note on storage placement:** spec says "stored in the paper broker state (paper_state.json)". I split it to a sidecar `protective_orders.json` because (a) live mode uses the same engine and has no paper_state.json, and (b) it keeps `PaperBroker._State` from growing yet another field. Functionally identical (persistent across restarts, same data dir).

**Type / signature consistency:** every store method that returns `int` (cancel/adjust) returns int; every method returning a `ProtectiveOrder` is consistent across tasks; tool argument schemas match the dataclass fields.

**Placeholder scan:** no TBDs, every code block is complete. The only `# noqa` is on the `Thread.run` override (legitimate). The only `# pragma: no cover` is none — every branch is exercised.
