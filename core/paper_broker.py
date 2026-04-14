"""PaperBroker — a stateful fake broker for paper trading.

Why this exists
===============

``LogBroker`` in ``broker.py`` is completely stateless: ``get_positions``
always returns ``[]``, ``submit_order`` just writes a JSONL line, cash is
hard-coded to 100k. For "paper mode", the agent sees no memory of what
it just traded, so strategies that depend on portfolio state (stops,
sizing, P&L) cannot be exercised.

``PaperBroker`` is the opposite: a full in-process simulation that

* persists positions / cash / pending orders to ``data/paper_state.json``;
* uses ``data_loader.fetch_live_prices`` for fills and unrealised P&L;
* queues orders submitted when the relevant exchange is closed and
  drains the queue automatically on the next public call once the
  exchange re-opens (so Friday-afternoon orders fill at Monday-morning
  prices, simulating weekend gap risk);
* writes an audit trail to ``logs/paper_orders.jsonl``.

Design notes
============

Price cache. Every public call reconciles pending orders before
answering. To keep that cheap we batch-fetch every pending ticker's
price in one ``fetch_live_prices`` call and cache the result for
``_PRICE_TTL_SECONDS``. yfinance is slow enough that without the cache
the agent would spend most of its tool budget waiting on prices.

Cash reservation. When a buy queues while a market is closed, we
reserve cash = ``max(limit_price, last_known_price) * quantity * 1.15``
against free_cash so the agent sees its real buying power shrink
immediately. At fill time the actual market-open price is used and
any excess reservation is refunded. If the gap overruns the reservation
the fill still goes through (we debit the difference) but the agent
will see negative free_cash on the next ``get_portfolio`` — the same
way a real margin account would show a shortfall.

Thread safety. Several concurrent agents can call this broker from
different QThreads (one supervisor + N chat workers). Every public
entry point takes ``self._lock`` so state mutations are serialised.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from broker import Broker
from market_hours import exchange_for_ticker, status

logger = logging.getLogger(__name__)

# How long a price lookup is reused before we fetch it again. yfinance
# is rate-limited and slow — 30s is plenty for a broker whose "fills"
# are coarse anyway.
_PRICE_TTL_SECONDS = 30.0

# Reserve this multiple of the best known price when queueing a buy
# against a closed market, to absorb weekend gap-up risk.
_GAP_BUFFER = 1.15

# Default starting cash for a brand-new paper account.
_DEFAULT_STARTING_CASH = 100_000.0


# ─────────────────────────────────────────────────────────────────────
# State model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class _Position:
    """One open position. ``avg_price`` tracks weighted cost basis."""

    quantity: float = 0.0
    avg_price: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"quantity": self.quantity, "avg_price": self.avg_price}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_Position":
        return cls(
            quantity=float(d.get("quantity", 0.0) or 0.0),
            avg_price=float(d.get("avg_price", 0.0) or 0.0),
        )


@dataclass
class _Order:
    """One queued order awaiting its exchange to open (or a limit trigger)."""

    order_id: str
    ticker: str
    side: str  # "BUY" / "SELL"
    quantity: float
    order_type: str  # "market" / "limit"
    limit_price: Optional[float]
    stop_price: Optional[float]
    reserved_cash: float
    created_at: str
    queue_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "reserved_cash": self.reserved_cash,
            "created_at": self.created_at,
            "queue_reason": self.queue_reason,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_Order":
        return cls(
            order_id=str(d.get("order_id", "")),
            ticker=str(d.get("ticker", "")),
            side=str(d.get("side", "")).upper(),
            quantity=float(d.get("quantity", 0.0) or 0.0),
            order_type=str(d.get("order_type", "market")),
            limit_price=(
                float(d["limit_price"]) if d.get("limit_price") is not None else None
            ),
            stop_price=(
                float(d["stop_price"]) if d.get("stop_price") is not None else None
            ),
            reserved_cash=float(d.get("reserved_cash", 0.0) or 0.0),
            created_at=str(d.get("created_at", "")),
            queue_reason=str(d.get("queue_reason", "")),
        )


@dataclass
class _State:
    """Everything persisted to disk for a paper account."""

    cash_free: float = _DEFAULT_STARTING_CASH
    positions: Dict[str, _Position] = field(default_factory=dict)
    pending_orders: List[_Order] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cash_free": self.cash_free,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "pending_orders": [o.to_dict() for o in self.pending_orders],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_State":
        return cls(
            cash_free=float(d.get("cash_free", _DEFAULT_STARTING_CASH) or 0.0),
            positions={
                str(k): _Position.from_dict(v)
                for k, v in (d.get("positions", {}) or {}).items()
            },
            pending_orders=[
                _Order.from_dict(o) for o in (d.get("pending_orders", []) or [])
            ],
        )


# ─────────────────────────────────────────────────────────────────────
# Price cache
# ─────────────────────────────────────────────────────────────────────

class _PriceCache:
    """Tiny TTL cache around ``fetch_live_prices`` for paper reconciliation."""

    def __init__(self, ttl_seconds: float = _PRICE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._cache: Dict[str, tuple[float, float]] = {}  # ticker -> (expires, price)

    def get_many(self, tickers: List[str]) -> Dict[str, float]:
        """Return ``{ticker: price}``. Missing prices come back as 0.0."""
        now = time.monotonic()
        missing = [t for t in tickers if self._cache.get(t, (0.0, 0.0))[0] <= now]
        if missing:
            try:
                from data_loader import fetch_live_prices
                live = fetch_live_prices(missing)
            except Exception as e:  # pragma: no cover — network errors
                logger.warning("paper: price fetch failed: %s", e)
                live = {}
            for t in missing:
                price = float((live.get(t) or {}).get("price", 0.0) or 0.0)
                self._cache[t] = (now + self._ttl, price)
        return {t: self._cache[t][1] for t in tickers}


# ─────────────────────────────────────────────────────────────────────
# The broker
# ─────────────────────────────────────────────────────────────────────

class PaperBroker(Broker):
    """Stateful paper-money broker. Shares its interface with Trading 212."""

    def __init__(
        self,
        state_path: Optional[Path] = None,
        audit_path: Optional[Path] = None,
        starting_cash: float = _DEFAULT_STARTING_CASH,
    ) -> None:
        self._state_path = Path(state_path or Path("data") / "paper_state.json")
        self._audit_path = Path(audit_path or Path("logs") / "paper_orders.jsonl")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._prices = _PriceCache()
        self._state: _State = self._load_state(starting_cash)

    # ── persistence ──────────────────────────────────────────────────

    def _load_state(self, starting_cash: float) -> _State:
        if self._state_path.exists():
            try:
                with self._state_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                return _State.from_dict(raw)
            except Exception as e:
                logger.warning(
                    "paper: state file corrupt, starting fresh: %s", e,
                )
        return _State(cash_free=starting_cash)

    def _save_state(self) -> None:
        tmp = self._state_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, indent=2)
        tmp.replace(self._state_path)

    def _audit(self, record: Dict[str, Any]) -> None:
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # ── queue reconciliation ─────────────────────────────────────────

    def _reconcile_pending(self) -> None:
        """Drain every pending order whose exchange is now open and fillable.

        Runs at the top of every public entry point. Cheap when the
        queue is empty (one dict read) and batches its price lookups
        when it isn't.
        """
        if not self._state.pending_orders:
            return
        tickers = sorted({o.ticker for o in self._state.pending_orders})
        prices = self._prices.get_many(tickers)

        still_pending: List[_Order] = []
        dirty = False
        for order in list(self._state.pending_orders):
            exch = exchange_for_ticker(order.ticker)
            if exch is None:
                # Unknown exchange (crypto, dual-listing we haven't mapped)
                # — just fill immediately at last known price.
                px = prices.get(order.ticker, 0.0)
                if px <= 0:
                    still_pending.append(order)
                    continue
                self._fill_order(order, px)
                dirty = True
                continue

            st = status(exch)
            if not st.get("is_open"):
                still_pending.append(order)
                continue

            px = prices.get(order.ticker, 0.0)
            if px <= 0:
                # Market says it's open but we can't price the ticker
                # — don't crash, just keep waiting.
                still_pending.append(order)
                continue

            if order.order_type == "limit":
                limit = float(order.limit_price or 0.0)
                if order.side == "BUY" and px > limit:
                    still_pending.append(order)
                    continue
                if order.side == "SELL" and px < limit:
                    still_pending.append(order)
                    continue

            self._fill_order(order, px)
            dirty = True

        self._state.pending_orders = still_pending
        if dirty:
            self._save_state()

    # ── fills ────────────────────────────────────────────────────────

    def _fill_order(self, order: _Order, fill_price: float) -> None:
        """Mutate cash + positions to reflect a fill. No locking — caller owns it."""
        ticker = order.ticker
        qty = order.quantity
        side = order.side.upper()
        cost = fill_price * qty

        if side == "BUY":
            # Refund / top-up cash reservation to match actual fill.
            refund = order.reserved_cash - cost
            self._state.cash_free += refund  # may be negative on gap-up overrun
            pos = self._state.positions.get(ticker, _Position())
            new_qty = pos.quantity + qty
            if new_qty > 0:
                pos.avg_price = (
                    (pos.avg_price * pos.quantity) + (fill_price * qty)
                ) / new_qty
            pos.quantity = new_qty
            self._state.positions[ticker] = pos
        elif side == "SELL":
            self._state.cash_free += cost
            pos = self._state.positions.get(ticker)
            if pos is not None:
                pos.quantity -= qty
                if pos.quantity <= 1e-9:
                    self._state.positions.pop(ticker, None)
                else:
                    self._state.positions[ticker] = pos
            # Oversell safety: a SELL that tries to unwind more than
            # held is already blocked by broker_tools.place_order, but
            # if somehow we land here just flatten.

        self._audit({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "order_id": order.order_id,
            "ticker": ticker,
            "side": side,
            "quantity": qty,
            "fill_price": fill_price,
            "cost": cost,
            "reserved_cash": order.reserved_cash,
            "queue_reason": order.queue_reason,
            "status": "FILLED",
            "cash_free_after": self._state.cash_free,
        })

    # ── helpers ──────────────────────────────────────────────────────

    def _current_prices(self, tickers: List[str]) -> Dict[str, float]:
        if not tickers:
            return {}
        return self._prices.get_many(tickers)

    def _ticker_is_tradeable(self, ticker: str) -> bool:
        """True if the ticker's exchange is currently in regular session."""
        exch = exchange_for_ticker(ticker)
        if exch is None:
            return True  # unknown → always tradeable (crypto, etc.)
        return bool(status(exch).get("is_open"))

    def _queue_reason(self, ticker: str) -> str:
        exch = exchange_for_ticker(ticker)
        if exch is None:
            return "unknown-exchange"
        st = status(exch)
        if st.get("is_open"):
            return ""
        return f"{exch.code} closed, next open {st.get('next_open')}"

    def _reservation_price(self, order_type: str, limit_price: Optional[float],
                           ticker: str) -> float:
        """Best-guess price for cash reservation when queueing a buy."""
        if order_type == "limit" and limit_price:
            return float(limit_price)
        live = self._prices.get_many([ticker]).get(ticker, 0.0)
        return float(live) if live > 0 else 0.0

    # ── Broker interface ─────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reconcile_pending()
            if not self._state.positions:
                return []
            tickers = list(self._state.positions.keys())
            prices = self._current_prices(tickers)
            out: List[Dict[str, Any]] = []
            for ticker, pos in self._state.positions.items():
                px = prices.get(ticker, 0.0) or pos.avg_price
                market_value = px * pos.quantity
                cost_basis = pos.avg_price * pos.quantity
                out.append({
                    "ticker": ticker,
                    "quantity": pos.quantity,
                    "avg_price": pos.avg_price,
                    "current_price": px,
                    "market_value": market_value,
                    "unrealised_pnl": market_value - cost_basis,
                })
            return out

    def get_account_info(self) -> Dict[str, Any]:
        with self._lock:
            self._reconcile_pending()
            tickers = list(self._state.positions.keys())
            prices = self._current_prices(tickers) if tickers else {}
            invested = 0.0
            unrealised = 0.0
            for ticker, pos in self._state.positions.items():
                px = prices.get(ticker, 0.0) or pos.avg_price
                market_value = px * pos.quantity
                cost_basis = pos.avg_price * pos.quantity
                invested += market_value
                unrealised += market_value - cost_basis
            total = self._state.cash_free + invested
            return {
                "free": self._state.cash_free,
                "invested": invested,
                "result": unrealised,
                "total": total,
            }

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reconcile_pending()
            return [o.to_dict() for o in self._state.pending_orders]

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        ticker = str(ticker).strip()
        side_upper = str(side).strip().upper()
        order_type = str(order_type).strip().lower()

        with self._lock:
            self._reconcile_pending()

            order_id = f"pp-{uuid.uuid4().hex[:10]}"
            created_at = datetime.now(tz=timezone.utc).isoformat()
            is_open = self._ticker_is_tradeable(ticker)

            # ── SELL path ────────────────────────────────────────────
            if side_upper == "SELL":
                if is_open:
                    live_px = self._prices.get_many([ticker]).get(ticker, 0.0)
                    if live_px <= 0:
                        return self._reject(
                            order_id, ticker, side_upper, quantity,
                            "no live price", order_type, limit_price,
                        )
                    if order_type == "limit" and limit_price and live_px < float(limit_price):
                        # queue the limit sell until price hits the limit
                        return self._enqueue_order(
                            order_id, ticker, side_upper, quantity,
                            order_type, limit_price, stop_price,
                            created_at, reserved_cash=0.0,
                            queue_reason="limit sell not yet triggered",
                        )
                    order = _Order(
                        order_id=order_id, ticker=ticker, side=side_upper,
                        quantity=quantity, order_type=order_type,
                        limit_price=limit_price, stop_price=stop_price,
                        reserved_cash=0.0, created_at=created_at,
                        queue_reason="",
                    )
                    self._fill_order(order, live_px)
                    self._save_state()
                    return {
                        "order_id": order_id, "status": "FILLED",
                        "ticker": ticker, "side": side_upper,
                        "quantity": quantity, "fill_price": live_px,
                    }
                # Market closed → queue it (no cash reservation needed for sells)
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    order_type, limit_price, stop_price,
                    created_at, reserved_cash=0.0,
                    queue_reason=self._queue_reason(ticker) or "market closed",
                )

            # ── BUY path ─────────────────────────────────────────────
            if side_upper != "BUY":
                return self._reject(
                    order_id, ticker, side_upper, quantity,
                    f"unknown side {side_upper}", order_type, limit_price,
                )

            reservation_px = self._reservation_price(
                order_type, limit_price, ticker,
            )
            if reservation_px <= 0:
                return self._reject(
                    order_id, ticker, side_upper, quantity,
                    "no reference price for cash reservation",
                    order_type, limit_price,
                )

            # Closed market → queue with gap-buffered reservation
            if not is_open:
                reserved = reservation_px * quantity * _GAP_BUFFER
                if reserved > self._state.cash_free + 1e-6:
                    return self._reject(
                        order_id, ticker, side_upper, quantity,
                        f"buy reservation ${reserved:.2f} > free "
                        f"${self._state.cash_free:.2f}",
                        order_type, limit_price,
                    )
                self._state.cash_free -= reserved
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    order_type, limit_price, stop_price,
                    created_at, reserved_cash=reserved,
                    queue_reason=self._queue_reason(ticker) or "market closed",
                )

            # Open market: limit buy that can't fill right now still queues.
            if order_type == "limit" and limit_price is not None and reservation_px > float(limit_price):
                # Price is above the limit — queue it.
                reserved = float(limit_price) * quantity
                if reserved > self._state.cash_free + 1e-6:
                    return self._reject(
                        order_id, ticker, side_upper, quantity,
                        f"limit reservation ${reserved:.2f} > free "
                        f"${self._state.cash_free:.2f}",
                        order_type, limit_price,
                    )
                self._state.cash_free -= reserved
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    order_type, limit_price, stop_price,
                    created_at, reserved_cash=reserved,
                    queue_reason="limit buy above market",
                )

            # Market open, fillable now — commit immediately.
            actual_cost = reservation_px * quantity
            if actual_cost > self._state.cash_free + 1e-6:
                return self._reject(
                    order_id, ticker, side_upper, quantity,
                    f"cost ${actual_cost:.2f} > free "
                    f"${self._state.cash_free:.2f}",
                    order_type, limit_price,
                )
            self._state.cash_free -= actual_cost  # reservation = cost
            order = _Order(
                order_id=order_id, ticker=ticker, side=side_upper,
                quantity=quantity, order_type=order_type,
                limit_price=limit_price, stop_price=stop_price,
                reserved_cash=actual_cost, created_at=created_at,
                queue_reason="",
            )
            self._fill_order(order, reservation_px)
            self._save_state()
            return {
                "order_id": order_id, "status": "FILLED",
                "ticker": ticker, "side": side_upper,
                "quantity": quantity, "fill_price": reservation_px,
            }

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            self._reconcile_pending()
            idx = next(
                (i for i, o in enumerate(self._state.pending_orders)
                 if o.order_id == order_id),
                None,
            )
            if idx is None:
                return False
            order = self._state.pending_orders.pop(idx)
            if order.side == "BUY" and order.reserved_cash > 0:
                self._state.cash_free += order.reserved_cash
            self._save_state()
            self._audit({
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "order_id": order.order_id,
                "ticker": order.ticker,
                "side": order.side,
                "quantity": order.quantity,
                "status": "CANCELLED",
                "refund": order.reserved_cash if order.side == "BUY" else 0.0,
            })
            return True

    # ── book-keeping helpers ─────────────────────────────────────────

    def _enqueue_order(
        self,
        order_id: str,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str,
        limit_price: Optional[float],
        stop_price: Optional[float],
        created_at: str,
        reserved_cash: float,
        queue_reason: str,
    ) -> Dict[str, Any]:
        order = _Order(
            order_id=order_id, ticker=ticker, side=side, quantity=quantity,
            order_type=order_type, limit_price=limit_price, stop_price=stop_price,
            reserved_cash=reserved_cash, created_at=created_at,
            queue_reason=queue_reason,
        )
        self._state.pending_orders.append(order)
        self._save_state()
        self._audit({
            "timestamp": created_at,
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "reserved_cash": reserved_cash,
            "queue_reason": queue_reason,
            "status": "QUEUED",
        })
        return {
            "order_id": order_id,
            "status": "QUEUED",
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "queue_reason": queue_reason,
            "reserved_cash": reserved_cash,
        }

    def _reject(
        self,
        order_id: str,
        ticker: str,
        side: str,
        quantity: float,
        reason: str,
        order_type: str,
        limit_price: Optional[float],
    ) -> Dict[str, Any]:
        self._audit({
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "status": "REJECTED",
            "reason": reason,
        })
        return {
            "order_id": order_id,
            "status": "REJECTED",
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "reason": reason,
        }

    # ── Extended Broker interface (history) ──────────────────────────

    def get_order_history(
        self,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read recent fills from the JSONL audit log (newest first)."""
        if not self._audit_path.exists():
            return {"items": [], "next_cursor": None}
        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return {"items": [], "next_cursor": None}
        items: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
            if len(items) >= limit:
                break
        return {"items": items, "next_cursor": None}
