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
from fx import fx_rate, ticker_currency
from market_hours import exchange_for_ticker, status

logger = logging.getLogger(__name__)

# How long a price lookup is reused before we fetch it again. yfinance
# is rate-limited and slow — 30s is plenty for a broker whose "fills"
# are coarse anyway.
_PRICE_TTL_SECONDS = 30.0

# Reserve this multiple of the best known price when queueing a buy
# against a closed market, to absorb weekend gap-up risk.
_GAP_BUFFER = 1.15

# Default starting cash for a brand-new paper account. Kept small so a
# missing or corrupted config can never silently hand the agent a
# $100k toy account — paper mode in blank is a £100 sandbox by design.
_DEFAULT_STARTING_CASH = 100.0

# Background monitor cadence. A stop-loss that waits 5–15 minutes for
# the agent to iterate is useless in a flash crash — we poll every
# second so stops/limits fire independently of the agent loop.
_MONITOR_TICK_SECONDS = 1.0


# ─────────────────────────────────────────────────────────────────────
# State model
# ─────────────────────────────────────────────────────────────────────

@dataclass
class _Position:
    """One open position.

    ``avg_price`` is stored in the ticker's *native* currency so the
    displayed number matches what the user sees on Yahoo / the broker
    UI (TSLA avg at $305, not £243.17). ``cost_basis_acct`` is the
    weighted *account-currency* cost — what we actually debited from
    ``cash_free`` on the fills, across whatever FX rates were in force
    at each entry. Both numbers are needed for clean P&L attribution:
    native tells you the trading decision, account tells you the
    ledger truth including FX drift.
    """

    quantity: float = 0.0
    avg_price: float = 0.0
    currency: str = "USD"
    cost_basis_acct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quantity": self.quantity,
            "avg_price": self.avg_price,
            "currency": self.currency,
            "cost_basis_acct": self.cost_basis_acct,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_Position":
        qty = float(d.get("quantity", 0.0) or 0.0)
        avg = float(d.get("avg_price", 0.0) or 0.0)
        # Legacy state files predate cost_basis_acct — if we're missing
        # it, fall back to ``avg * qty`` (assumes no FX move since entry,
        # which is the best guess we have without the original rate).
        cost_basis = float(d.get("cost_basis_acct", avg * qty) or 0.0)
        return cls(
            quantity=qty,
            avg_price=avg,
            currency=str(d.get("currency", "USD") or "USD"),
            cost_basis_acct=cost_basis,
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
            "id": self.order_id,
            "ticker": self.ticker,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "reserved_cash": self.reserved_cash,
            "created_at": self.created_at,
            "queue_reason": self.queue_reason,
            "status": "PENDING",
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
    """Everything persisted to disk for a paper account.

    The realised-P&L counters are cumulative across the account's
    lifetime (reset on ``PaperBroker.reset()``). They let the agent
    see how much of its closed-trade P&L came from price moves vs
    currency moves — a £100 GBP account that trades US stocks can
    easily see its "trading wins" eaten by a weakening dollar, and
    the attribution exposes that without the agent having to guess.
    """

    cash_free: float = _DEFAULT_STARTING_CASH
    currency: str = "USD"
    positions: Dict[str, _Position] = field(default_factory=dict)
    pending_orders: List[_Order] = field(default_factory=list)
    realised_pnl_acct: float = 0.0
    realised_trading_acct: float = 0.0
    realised_fx_acct: float = 0.0
    total_deposits_acct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cash_free": self.cash_free,
            "currency": self.currency,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "pending_orders": [o.to_dict() for o in self.pending_orders],
            "realised_pnl_acct": self.realised_pnl_acct,
            "realised_trading_acct": self.realised_trading_acct,
            "realised_fx_acct": self.realised_fx_acct,
            "total_deposits_acct": self.total_deposits_acct,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "_State":
        return cls(
            cash_free=float(d.get("cash_free", _DEFAULT_STARTING_CASH) or 0.0),
            currency=str(d.get("currency", "USD") or "USD"),
            positions={
                str(k): _Position.from_dict(v)
                for k, v in (d.get("positions", {}) or {}).items()
            },
            pending_orders=[
                _Order.from_dict(o) for o in (d.get("pending_orders", []) or [])
            ],
            realised_pnl_acct=float(d.get("realised_pnl_acct", 0.0) or 0.0),
            realised_trading_acct=float(d.get("realised_trading_acct", 0.0) or 0.0),
            realised_fx_acct=float(d.get("realised_fx_acct", 0.0) or 0.0),
            total_deposits_acct=float(d.get("total_deposits_acct", 0.0) or 0.0),
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

    def get_fresh(self, ticker: str) -> float:
        """Force a fresh fetch, bypassing TTL. Updates cache on success.

        Used at fill time so a paper order always books against the
        live market price, not a 30-second-stale cached quote. The 30s
        cache is fine for position/account displays but would book CVX
        at $150 when the actual tape has rallied to $183.
        """
        try:
            from data_loader import fetch_live_prices
            live = fetch_live_prices([ticker])
        except Exception as e:  # pragma: no cover — network errors
            logger.warning("paper: fresh price fetch failed for %s: %s", ticker, e)
            return 0.0
        price = float((live.get(ticker) or {}).get("price", 0.0) or 0.0)
        if price > 0:
            self._cache[ticker] = (time.monotonic() + self._ttl, price)
        return price


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
        currency: str = "USD",
    ) -> None:
        self._state_path = Path(state_path or Path("data") / "paper_state.json")
        self._audit_path = Path(audit_path or Path("logs") / "paper_orders.jsonl")
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._prices = _PriceCache()
        # Remember the config values so reset() can rebuild from them
        # without re-reading config.json.
        self._starting_cash = float(starting_cash)
        self._currency = str(currency or "USD")
        self._state: _State = self._load_state(self._starting_cash, self._currency)

        # Background 1 s monitor — runs forever as a daemon so stops
        # and limits execute independently of the agent iteration.
        # When the active data provider supports WebSocket streaming
        # (FMP Enterprise), the monitor *also* opens a stream against
        # every pending-order ticker so triggers fire on tick rather
        # than waiting for the next 1 s poll. Both paths run together
        # — streaming is best-effort; if it dies, the poll keeps the
        # broker correct.
        self._monitor_stop = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stream_subscription: Any = None
        self._stream_tickers: tuple[str, ...] = ()
        self._start_monitor()

    # ── persistence ──────────────────────────────────────────────────

    def _load_state(self, starting_cash: float, currency: str) -> _State:
        """Load state from disk, rebuilding from config if the disk is stale.

        Stale-state detection: if the persisted file's ``starting_cash``
        or ``currency`` no longer matches the config the caller just
        handed us — and the account has not yet been traded — the
        config wins. This fixes the "edit config.json to £100 but the
        agent still sees the $100k the file was born with" bug: the
        previous loader silently preserved the disk's cash on reload.
        We only rebuild when the portfolio is empty; a user who has
        actually traded on a stale account keeps their positions and
        just has the currency stamped on if it's missing.
        """
        if not self._state_path.exists():
            return _State(cash_free=starting_cash, currency=currency)
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.warning(
                "paper: state file corrupt, starting fresh: %s", e,
            )
            return _State(cash_free=starting_cash, currency=currency)

        disk_cash = float(raw.get("cash_free", 0.0) or 0.0)
        disk_currency = str(raw.get("currency", "") or "")
        # "Has activity" = any trace the user actually used this account.
        # Positions, pending orders, deposits, or realised P&L all count —
        # wiping any of those on restart would destroy real state.
        has_trading = bool(raw.get("positions")) or bool(raw.get("pending_orders"))
        has_deposits = float(raw.get("total_deposits_acct", 0.0) or 0.0) > 0.0
        has_realised = (
            float(raw.get("realised_pnl_acct", 0.0) or 0.0) != 0.0
            or float(raw.get("realised_trading_acct", 0.0) or 0.0) != 0.0
            or float(raw.get("realised_fx_acct", 0.0) or 0.0) != 0.0
        )
        has_activity = has_trading or has_deposits or has_realised

        cash_stale = (
            starting_cash > 0
            and abs(disk_cash - starting_cash) > max(0.01 * starting_cash, 1e-6)
        )
        currency_stale = (
            bool(currency) and bool(disk_currency) and disk_currency != currency
        )
        missing_currency = bool(currency) and not disk_currency

        if not has_activity and (cash_stale or currency_stale or missing_currency):
            logger.warning(
                "paper: state file stale (disk cash=%s ccy=%s, "
                "config cash=%s ccy=%s) — rebuilding from config",
                disk_cash, disk_currency or "<none>", starting_cash, currency,
            )
            return _State(cash_free=starting_cash, currency=currency)

        try:
            state = _State.from_dict(raw)
        except Exception as e:
            logger.warning(
                "paper: state parse failed, starting fresh: %s", e,
            )
            return _State(cash_free=starting_cash, currency=currency)

        # Back-fill currency on a pre-currency state file so legacy
        # users don't silently get "USD" once the field starts existing.
        # ``from_dict`` defaults missing currency to "USD", so we check
        # the raw dict directly to distinguish "was stamped USD" from
        # "had no currency at all".
        if "currency" not in raw and currency:
            state.currency = currency
        return state

    def reset(self) -> None:
        """Wipe the paper account and rebuild from the config values.

        Removes the persisted state file and reconstructs in-memory
        state with the ``starting_cash`` and ``currency`` handed to
        ``__init__``. Safe to call concurrently with read traffic —
        takes the broker lock.
        """
        with self._lock:
            try:
                self._state_path.unlink()
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(
                    "paper: reset failed to delete state file: %s", e,
                )
            self._state = _State(
                cash_free=self._starting_cash,
                currency=self._currency,
            )
            self._save_state()
            self._audit({
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "status": "RESET",
                "cash_free": self._state.cash_free,
                "currency": self._state.currency,
            })
            logger.info(
                "paper: account reset to %s %.2f",
                self._state.currency, self._state.cash_free,
            )

    def deposit(self, amount: float) -> Dict[str, Any]:
        """Credit the paper account with ``amount`` of account-currency cash.

        Simulates a bank transfer into the sandbox — touches only
        ``cash_free`` and the cumulative ``total_deposits_acct`` counter.
        Realised / unrealised P&L counters are left alone so the commission
        model (which tallies realised trade P&L, not cash balance) correctly
        treats deposits as non-profit.

        Writes an audit row tagged ``DEPOSIT`` to ``paper_orders.jsonl``.
        The row has no ticker/side, so ``get_order_history`` (which
        filters those out) never surfaces deposits as trades.
        """
        if amount <= 0:
            raise ValueError(f"deposit amount must be positive, got {amount}")
        with self._lock:
            self._state.cash_free += float(amount)
            self._state.total_deposits_acct += float(amount)
            self._save_state()
            self._audit({
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "status": "DEPOSIT",
                "amount": float(amount),
                "currency": self._state.currency,
                "cash_free_after": self._state.cash_free,
                "total_deposits_after": self._state.total_deposits_acct,
            })
            logger.info(
                "paper: deposited %s %.2f (cash_free=%.2f, total_deposits=%.2f)",
                self._state.currency, float(amount),
                self._state.cash_free, self._state.total_deposits_acct,
            )
            return {
                "status": "OK",
                "amount": float(amount),
                "currency": self._state.currency,
                "cash_free": self._state.cash_free,
                "total_deposits": self._state.total_deposits_acct,
            }

    def modify_order(
        self,
        order_id: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Adjust an open pending order's limit_price and/or stop_price.

        Does not support resizing — changing quantity would require
        re-reserving cash on BUYs, a path that's easy to get wrong.
        Cancel-and-resubmit is the safe way to resize.

        Returns ``{"status": "OK", ...}`` on success. If the order is
        no longer pending (already filled, already cancelled, or never
        existed), returns ``{"status": "REJECTED", "reason": ...}``.
        """
        with self._lock:
            self._reconcile_pending()
            order = next(
                (o for o in self._state.pending_orders if o.order_id == order_id),
                None,
            )
            if order is None:
                return {
                    "status": "REJECTED",
                    "reason": f"no pending order with id {order_id}",
                }
            if limit_price is None and stop_price is None:
                return {
                    "status": "REJECTED",
                    "reason": "supply at least one of limit_price or stop_price",
                }
            old_limit = order.limit_price
            old_stop = order.stop_price
            if limit_price is not None:
                order.limit_price = float(limit_price)
            if stop_price is not None:
                order.stop_price = float(stop_price)
            self._save_state()
            self._audit({
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "order_id": order.order_id,
                "ticker": order.ticker,
                "side": order.side,
                "status": "MODIFIED",
                "old_limit_price": old_limit,
                "old_stop_price": old_stop,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
            })
            logger.info(
                "paper: modified %s %s %s → limit=%s stop=%s",
                order.order_id, order.side, order.ticker,
                order.limit_price, order.stop_price,
            )
            return {
                "status": "OK",
                "order_id": order.order_id,
                "ticker": order.ticker,
                "side": order.side,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
            }

    # ── background monitor ───────────────────────────────────────────

    def _start_monitor(self) -> None:
        """Spawn the 1 s background reconciliation thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        t = threading.Thread(
            target=self._monitor_loop,
            name="paper-broker-monitor",
            daemon=True,
        )
        t.start()
        self._monitor_thread = t

    def _monitor_loop(self) -> None:
        """Tick every second, firing any triggered stops/limits.

        Skips cheaply when there are no pending orders so the hot path
        is a single list check. Errors are logged, not raised — a
        failed tick must not kill the thread. Whenever the pending
        ticker set changes we re-subscribe the WebSocket stream (when
        the provider supports streaming) so new orders are covered.
        """
        while not self._monitor_stop.is_set():
            try:
                with self._lock:
                    pending_tickers = tuple(sorted({o.ticker for o in self._state.pending_orders}))
                if pending_tickers != self._stream_tickers:
                    self._sync_stream(list(pending_tickers))
                if pending_tickers:
                    with self._lock:
                        self._reconcile_pending()
            except Exception:
                logger.exception("paper: monitor tick failed")
            self._monitor_stop.wait(_MONITOR_TICK_SECONDS)

    def _sync_stream(self, tickers: List[str]) -> None:
        """Match the WebSocket subscription to the current pending-order set.

        Best-effort: if the provider doesn't support streaming, this
        is a noop and the 1 s poll continues to drive reconciliation.
        Failures are logged at debug level — streaming is an
        optimisation, not a correctness gate.
        """
        try:
            from core.data import get_provider
            provider = get_provider()
        except Exception:
            return
        if not getattr(provider, "supports_streaming", False):
            return

        # No pending tickers → tear down any existing stream.
        if not tickers:
            if self._stream_subscription is not None:
                try:
                    provider.stop_websocket(self._stream_subscription)
                except Exception:
                    logger.debug("paper: stop_websocket raised", exc_info=True)
                self._stream_subscription = None
            self._stream_tickers = ()
            return

        # Existing stream → just retarget it.
        if self._stream_subscription is not None:
            try:
                provider.update_websocket_tickers(self._stream_subscription, tickers)
                self._stream_tickers = tuple(tickers)
                return
            except Exception:
                logger.debug("paper: update_websocket_tickers raised", exc_info=True)
                # Fall through and rebuild from scratch.
                try:
                    provider.stop_websocket(self._stream_subscription)
                except Exception:
                    pass
                self._stream_subscription = None

        # Fresh subscription. ``_on_stream_tick`` simply forces a
        # reconciliation pass — the provider has already given us the
        # tick, but the broker is the source of truth for fill prices,
        # so we let _reconcile_pending re-fetch through the price
        # cache (which the stream is already warming).
        try:
            sub = provider.start_websocket(tickers, self._on_stream_tick)
        except Exception:
            logger.debug("paper: start_websocket raised", exc_info=True)
            sub = None
        self._stream_subscription = sub
        self._stream_tickers = tuple(tickers) if sub is not None else ()

    def _on_stream_tick(self, quote: Any) -> None:
        """Stream callback — kicks reconciliation when a tick lands.

        Reconciliation under the lock would risk priority inversion
        with the polling loop; we instead nudge the cache and let the
        next monitor tick (≤1 s away) handle the fill. That keeps
        order book mutations on a single thread.
        """
        try:
            ticker = getattr(quote, "ticker", None)
            price = getattr(quote, "price", None)
            if ticker and price and price > 0:
                # Hot-load the price cache so the next reconciliation
                # tick uses the streamed value rather than re-fetching.
                self._prices._cache[str(ticker)] = (
                    time.monotonic() + _PRICE_TTL_SECONDS, float(price),
                )
        except Exception:
            logger.debug("paper: _on_stream_tick error", exc_info=True)

    def stop_monitor(self) -> None:
        """Signal the monitor thread to stop and wait briefly for it to exit.

        Also tears down the WebSocket subscription if one is active.
        """
        self._monitor_stop.set()
        if self._stream_subscription is not None:
            try:
                from core.data import get_provider
                get_provider().stop_websocket(self._stream_subscription)
            except Exception:
                logger.debug("paper: stop_websocket on shutdown raised", exc_info=True)
            self._stream_subscription = None
            self._stream_tickers = ()
        t = self._monitor_thread
        if t is not None:
            t.join(timeout=2.0)

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

        Runs at the top of every public entry point AND on a 1-second
        background tick (see ``_monitor_loop``) so stop-losses and
        take-profits trigger autonomously without waiting on an agent
        iteration. Cheap when the queue is empty (one list check) and
        batches its price lookups when it isn't.

        Trigger rules:
        * ``limit`` BUY  — fills when px <= limit_price
        * ``limit`` SELL — fills when px >= limit_price (take-profit)
        * ``stop``  SELL — fills when px <= stop_price  (stop-loss)
        * ``stop``  BUY  — fills when px >= stop_price  (breakout entry)
        * ``market``     — fills as soon as the exchange is open and priceable
        """
        if not self._state.pending_orders:
            return
        tickers = sorted({o.ticker for o in self._state.pending_orders})
        prices = self._prices.get_many(tickers)

        still_pending: List[_Order] = []
        dirty = False
        for order in list(self._state.pending_orders):
            exch = exchange_for_ticker(order.ticker)
            if exch is not None:
                # Only wait for market open when the ticker is tied to an
                # exchange we know the hours for. Stops and limits both
                # need an open book to fire — a stop-loss that triggers
                # on after-hours data would fill against a closed market.
                if not status(exch).get("is_open"):
                    still_pending.append(order)
                    continue

            px = prices.get(order.ticker, 0.0)
            if px <= 0:
                # No live price — can't evaluate a trigger. Keep waiting.
                still_pending.append(order)
                continue

            otype = order.order_type
            if otype == "limit":
                limit = float(order.limit_price or 0.0)
                if order.side == "BUY" and px > limit:
                    still_pending.append(order)
                    continue
                if order.side == "SELL" and px < limit:
                    still_pending.append(order)
                    continue
            elif otype == "stop":
                stop = float(order.stop_price or 0.0)
                if stop <= 0:
                    still_pending.append(order)
                    continue
                # Stop SELL fires on a drop; stop BUY fires on a rally.
                if order.side == "SELL" and px > stop:
                    still_pending.append(order)
                    continue
                if order.side == "BUY" and px < stop:
                    still_pending.append(order)
                    continue
            # "market" falls through — it fills as soon as we have a price.

            self._fill_order(order, px)
            dirty = True

        self._state.pending_orders = still_pending
        if dirty:
            self._save_state()

    # ── fills ────────────────────────────────────────────────────────

    def _fill_order(self, order: _Order, fill_price: float) -> None:
        """Mutate cash + positions to reflect a fill. No locking — caller owns it.

        ``fill_price`` is in the ticker's native currency (yfinance
        gives us whatever the exchange quotes). All cash moves on
        ``self._state.cash_free`` must be in the account's own
        currency, so we convert at the rate prevailing at fill time
        and store both legs for Task N's P&L attribution.
        """
        ticker = order.ticker
        qty = order.quantity
        side = order.side.upper()
        native_ccy = ticker_currency(ticker, default="USD")
        account_ccy = self._state.currency
        rate = fx_rate(native_ccy, account_ccy)
        native_cost = fill_price * qty
        acct_cost = native_cost * rate

        realised_pnl_acct = 0.0
        realised_trading_acct = 0.0
        realised_fx_acct = 0.0

        if side == "BUY":
            # Refund / top-up cash reservation to match actual fill.
            # Both ``reserved_cash`` and ``acct_cost`` are in account
            # currency — the reservation path does the conversion at
            # queue time so this subtraction is FX-consistent.
            refund = order.reserved_cash - acct_cost
            self._state.cash_free += refund  # may be negative on gap-up or FX overrun
            pos = self._state.positions.get(ticker)
            if pos is None:
                pos = _Position(currency=native_ccy)
            new_qty = pos.quantity + qty
            if new_qty > 0:
                pos.avg_price = (
                    (pos.avg_price * pos.quantity) + (fill_price * qty)
                ) / new_qty
            pos.quantity = new_qty
            pos.cost_basis_acct += acct_cost
            pos.currency = native_ccy
            self._state.positions[ticker] = pos
        elif side == "SELL":
            self._state.cash_free += acct_cost
            pos = self._state.positions.get(ticker)
            if pos is not None and pos.quantity > 0:
                # Proportionally drop cost basis and split the
                # realised P&L into trading vs FX components. The
                # average entry FX rate for this position is implicit
                # in ``cost_basis_acct / (avg_price * qty_held)`` —
                # that's the rate that maps the native cost to the
                # account cost we actually paid across all entries.
                sold_fraction = min(qty / pos.quantity, 1.0)
                cost_out = pos.cost_basis_acct * sold_fraction
                realised_pnl_acct = acct_cost - cost_out
                # Entry rate (weighted across top-ups) for the slice
                # being sold: cost_out is in account ccy, native cost
                # of the slice is pos.avg_price * qty.
                native_cost_slice = pos.avg_price * qty
                entry_rate = (
                    cost_out / native_cost_slice if native_cost_slice > 0 else rate
                )
                # Trading P&L: price move valued at entry FX rate (so
                # FX drift is excluded). FX P&L: whatever is left over
                # — the residual captures both the pure FX component
                # and the small price×FX cross term.
                realised_trading_acct = (
                    (fill_price - pos.avg_price) * qty * entry_rate
                )
                realised_fx_acct = realised_pnl_acct - realised_trading_acct
                self._state.realised_pnl_acct += realised_pnl_acct
                self._state.realised_trading_acct += realised_trading_acct
                self._state.realised_fx_acct += realised_fx_acct
                pos.cost_basis_acct -= cost_out
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
            "native_currency": native_ccy,
            "account_currency": account_ccy,
            "fx_rate": rate,
            "native_cost": native_cost,
            "account_cost": acct_cost,
            "realised_pnl_acct": realised_pnl_acct,
            "realised_trading_acct": realised_trading_acct,
            "realised_fx_acct": realised_fx_acct,
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
        """Best-guess price for cash reservation when queueing a buy.

        Uses a fresh price fetch (not the 30s cache) because this value
        becomes the actual fill price on an immediate market buy — a
        stale quote would book CVX at last-cached $150 even when the
        live tape is at $183.
        """
        if order_type == "limit" and limit_price:
            return float(limit_price)
        live = self._prices.get_fresh(ticker)
        return float(live) if live > 0 else 0.0

    # ── Broker interface ─────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._reconcile_pending()
            if not self._state.positions:
                return []
            tickers = list(self._state.positions.keys())
            prices = self._current_prices(tickers)
            account_ccy = self._state.currency
            out: List[Dict[str, Any]] = []
            for ticker, pos in self._state.positions.items():
                px_native = prices.get(ticker, 0.0) or pos.avg_price
                market_value_native = px_native * pos.quantity
                rate = fx_rate(pos.currency, account_ccy)
                market_value_acct = market_value_native * rate
                unrealised_acct = market_value_acct - pos.cost_basis_acct

                # Attribution split. Entry rate is implicit in the
                # ratio of account-currency cost to native-currency
                # cost for the position. Trading P&L uses entry rate
                # so it excludes FX drift; FX P&L is everything else.
                native_cost_total = pos.avg_price * pos.quantity
                entry_rate = (
                    pos.cost_basis_acct / native_cost_total
                    if native_cost_total > 0 else rate
                )
                unrealised_trading = (
                    (px_native - pos.avg_price) * pos.quantity * entry_rate
                )
                unrealised_fx = unrealised_acct - unrealised_trading

                out.append({
                    "ticker": ticker,
                    "quantity": pos.quantity,
                    # Native-currency view (what the exchange prints)
                    "avg_price": pos.avg_price,
                    "current_price": px_native,
                    "currency": pos.currency,
                    # Account-currency view (what our ledger uses)
                    "account_currency": account_ccy,
                    "fx_rate": rate,
                    "entry_fx_rate": entry_rate,
                    "cost_basis_acct": pos.cost_basis_acct,
                    "market_value": market_value_acct,
                    "unrealised_pnl": unrealised_acct,
                    "unrealised_trading_pnl": unrealised_trading,
                    "unrealised_fx_pnl": unrealised_fx,
                })
            return out

    def get_account_info(self) -> Dict[str, Any]:
        with self._lock:
            self._reconcile_pending()
            tickers = list(self._state.positions.keys())
            prices = self._current_prices(tickers) if tickers else {}
            account_ccy = self._state.currency
            invested_acct = 0.0
            unrealised_acct = 0.0
            unrealised_trading = 0.0
            unrealised_fx = 0.0
            for ticker, pos in self._state.positions.items():
                px_native = prices.get(ticker, 0.0) or pos.avg_price
                market_value_native = px_native * pos.quantity
                rate = fx_rate(pos.currency, account_ccy)
                market_value_acct = market_value_native * rate
                invested_acct += market_value_acct
                unrealised_acct += market_value_acct - pos.cost_basis_acct

                native_cost_total = pos.avg_price * pos.quantity
                entry_rate = (
                    pos.cost_basis_acct / native_cost_total
                    if native_cost_total > 0 else rate
                )
                trading_leg = (
                    (px_native - pos.avg_price) * pos.quantity * entry_rate
                )
                unrealised_trading += trading_leg
                unrealised_fx += (market_value_acct - pos.cost_basis_acct) - trading_leg

            total = self._state.cash_free + invested_acct
            return {
                "free": self._state.cash_free,
                "invested": invested_acct,
                "result": unrealised_acct,
                "total": total,
                "currency": account_ccy,
                # Attribution of unrealised P&L on open positions
                "unrealised_trading_pnl": unrealised_trading,
                "unrealised_fx_pnl": unrealised_fx,
                # Cumulative realised P&L since account reset
                "realised_pnl": self._state.realised_pnl_acct,
                "realised_trading_pnl": self._state.realised_trading_acct,
                "realised_fx_pnl": self._state.realised_fx_acct,
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

            # ── STOP path ────────────────────────────────────────────
            # Stop orders always queue — they wait for the 1s monitor
            # loop to detect the trigger price, regardless of whether
            # the market is open right now. A BUY stop still needs
            # enough cash reserved at the stop_price to cover the fill;
            # a SELL stop rides on the held position (no reservation).
            if order_type == "stop":
                if stop_price is None or float(stop_price) <= 0:
                    return self._reject(
                        order_id, ticker, side_upper, quantity,
                        "stop order requires a positive stop_price",
                        order_type, limit_price,
                    )
                reserved_acct = 0.0
                queue_reason = (
                    f"stop-{'loss' if side_upper == 'SELL' else 'entry'} "
                    f"trigger at {float(stop_price):.4f}"
                )
                if side_upper == "BUY":
                    native_ccy = ticker_currency(ticker, default="USD")
                    account_ccy = self._state.currency
                    rate = fx_rate(native_ccy, account_ccy)
                    # Reserve at stop_price × gap buffer — the trigger
                    # fills as a market order, so we could overshoot.
                    reserved_native = float(stop_price) * quantity * _GAP_BUFFER
                    reserved_acct = reserved_native * rate
                    if reserved_acct > self._state.cash_free + 1e-6:
                        return self._reject(
                            order_id, ticker, side_upper, quantity,
                            f"stop-BUY reservation {reserved_acct:.2f} {account_ccy} "
                            f"> free {self._state.cash_free:.2f} {account_ccy}",
                            order_type, limit_price,
                        )
                    self._state.cash_free -= reserved_acct
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    "stop", limit_price, stop_price,
                    created_at, reserved_cash=reserved_acct,
                    queue_reason=queue_reason,
                )

            # ── SELL path ────────────────────────────────────────────
            if side_upper == "SELL":
                if is_open:
                    # Fresh fetch — this becomes the fill price, so a
                    # 30s-stale cache would book at the wrong level.
                    live_px = self._prices.get_fresh(ticker)
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

            # Every cash move goes through the account's own currency.
            # ``reservation_px`` is what the exchange quotes the ticker
            # in (USD for TSLA, GBP for VOD.L), so we FX-convert before
            # touching ``cash_free`` — otherwise a £100 account would
            # silently compare a $300 reservation to £100 and look
            # under-funded even though it has enough buying power.
            native_ccy = ticker_currency(ticker, default="USD")
            account_ccy = self._state.currency
            rate = fx_rate(native_ccy, account_ccy)

            # Closed market → queue with gap-buffered reservation
            if not is_open:
                reserved_native = reservation_px * quantity * _GAP_BUFFER
                reserved_acct = reserved_native * rate
                if reserved_acct > self._state.cash_free + 1e-6:
                    return self._reject(
                        order_id, ticker, side_upper, quantity,
                        f"buy reservation {reserved_acct:.2f} {account_ccy} "
                        f"> free {self._state.cash_free:.2f} {account_ccy}",
                        order_type, limit_price,
                    )
                self._state.cash_free -= reserved_acct
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    order_type, limit_price, stop_price,
                    created_at, reserved_cash=reserved_acct,
                    queue_reason=self._queue_reason(ticker) or "market closed",
                )

            # Open market: limit buy that can't fill right now still queues.
            if order_type == "limit" and limit_price is not None and reservation_px > float(limit_price):
                reserved_native = float(limit_price) * quantity
                reserved_acct = reserved_native * rate
                if reserved_acct > self._state.cash_free + 1e-6:
                    return self._reject(
                        order_id, ticker, side_upper, quantity,
                        f"limit reservation {reserved_acct:.2f} {account_ccy} "
                        f"> free {self._state.cash_free:.2f} {account_ccy}",
                        order_type, limit_price,
                    )
                self._state.cash_free -= reserved_acct
                return self._enqueue_order(
                    order_id, ticker, side_upper, quantity,
                    order_type, limit_price, stop_price,
                    created_at, reserved_cash=reserved_acct,
                    queue_reason="limit buy above market",
                )

            # Market open, fillable now — commit immediately.
            actual_native_cost = reservation_px * quantity
            actual_acct_cost = actual_native_cost * rate
            if actual_acct_cost > self._state.cash_free + 1e-6:
                return self._reject(
                    order_id, ticker, side_upper, quantity,
                    f"cost {actual_acct_cost:.2f} {account_ccy} "
                    f"> free {self._state.cash_free:.2f} {account_ccy}",
                    order_type, limit_price,
                )
            self._state.cash_free -= actual_acct_cost  # reservation = cost
            order = _Order(
                order_id=order_id, ticker=ticker, side=side_upper,
                quantity=quantity, order_type=order_type,
                limit_price=limit_price, stop_price=stop_price,
                reserved_cash=actual_acct_cost, created_at=created_at,
                queue_reason="",
            )
            self._fill_order(order, reservation_px)
            self._save_state()
            return {
                "order_id": order_id, "status": "FILLED",
                "ticker": ticker, "side": side_upper,
                "quantity": quantity, "fill_price": reservation_px,
                "native_currency": native_ccy,
                "account_currency": account_ccy,
                "fx_rate": rate,
                "cost_account_ccy": actual_acct_cost,
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
        """Read recent audit rows, newest-first, collapsed per order_id.

        Skips RESET housekeeping rows (they carry no ticker/side and
        would render as blank red "SELL" entries in the orders panel)
        and keeps only the latest status per order_id — a BUY that
        was QUEUED and then FILLED must not show up twice.
        """
        if not self._audit_path.exists():
            return {"items": [], "next_cursor": None}
        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return {"items": [], "next_cursor": None}

        seen_ids: set[str] = set()
        items: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if str(row.get("status", "")).upper() == "RESET":
                continue
            if not row.get("ticker") or not row.get("side"):
                continue
            oid = str(row.get("order_id") or "")
            if oid and oid in seen_ids:
                continue
            if oid:
                seen_ids.add(oid)
            items.append(row)
            if len(items) >= limit:
                break
        return {"items": items, "next_cursor": None}

    def position_entry_time(self, ticker: str) -> Optional[datetime]:
        """Return the timestamp of the most recent BUY fill for *ticker*.

        Reads the audit log newest-first and stops at the first
        matching FILLED BUY. The agent's exit logic uses this to
        measure how long a position has been open so it can honour
        the ``min_hold_minutes`` floor from config.
        """
        if not self._audit_path.exists():
            return None
        try:
            with self._audit_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            return None
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if (str(row.get("ticker", "")) == ticker
                    and str(row.get("side", "")).upper() == "BUY"
                    and str(row.get("status", "")).upper() == "FILLED"):
                ts = row.get("timestamp")
                if not ts:
                    continue
                try:
                    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    continue
        return None
