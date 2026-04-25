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
explicit: a stop at "250" on VOD.L means 250p, not £250.
``native_currency`` is a label for the UI / journal; the comparison is
unit-agnostic.

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
import uuid
from dataclasses import asdict, dataclass
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
                    # For trailing stops, treat new_price as the new
                    # trigger explicitly and back-solve the implied
                    # anchor at the configured distance — keeps the
                    # trail honest after a manual nudge.
                    if (o.kind == StopKind.TRAILING_STOP
                            and o.anchor_price is not None
                            and o.distance_pct):
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
