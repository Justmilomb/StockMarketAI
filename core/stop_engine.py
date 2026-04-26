"""StopEngine — native price-monitor for stop-loss / take-profit / trailing stops.

Why this exists
===============

The agent fires once every 30-60s. A stop-loss that only re-evaluates on
that cadence is dangerous: a flash crash that prints through the stop
between iterations gets sold at the bottom on the next wake-up rather
than at the trigger. We need a tighter loop than the agent's.

This module owns a daemon thread that polls live prices every second,
walks the active-stops list persisted in ``paper_state.json``, and
issues market sells via the broker the moment a trigger fires —
independently of whatever the supervisor agent happens to be doing.

Design notes
============

* **Paper mode only.** Trading 212 has native stop orders, so the live
  path leaves stop management to the broker. The engine no-ops when
  the underlying broker is not a ``PaperBroker``.
* **Source of truth.** Active stops live inside ``_State.active_stops``
  on the paper broker; the engine never persists state of its own.
  This means the broker's RLock + atomic state-file write protect
  every stop mutation, and a freshly-launched app sees yesterday's
  stops without the engine doing anything special.
* **GBX / GBP.** Yfinance quotes ``.L`` tickers in pence. The engine
  always compares prices in the broker's native unit. ``unit_to_native``
  and ``native_to_unit`` handle the user-facing pounds/pence translation
  on the way in and out of the tools.
* **Trailing stops.** ``high_water_mark`` is updated in-place on each
  tick when the live price exceeds it, then the trigger is computed
  as ``hwm - trail_distance`` (or ``hwm * (1 - trail_distance_pct/100)``).
  We never raise a trailing stop — only the high-water mark moves up.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: How often the monitor wakes to re-check live prices.
POLL_SECONDS: float = 1.0

#: When a yfinance batch fails we back off this long before retrying so
#: a transient network blip doesn't burn through 50 retries per second.
_BACKOFF_SECONDS: float = 5.0

#: Stop kinds the engine knows how to evaluate.
STOP_KINDS: Tuple[str, ...] = ("stop_loss", "take_profit", "trailing_stop")

#: Rolling window for momentum-trigger detection. The engine retains the
#: last N seconds of (timestamp, price) samples per ticker and computes
#: the percent move over that window each tick. 10s is short enough to
#: catch a flash spike, long enough to avoid false-positives on a single
#: noisy print.
MOMENTUM_WINDOW_SECONDS: float = 10.0


# ── unit helpers (GBX ↔ GBP) ────────────────────────────────────────────

def is_gbx_quoted(ticker: str) -> bool:
    """True for Yahoo .L tickers — these come back from yfinance in pence."""
    return ticker.upper().endswith(".L")


def unit_to_native(ticker: str, price: float, unit: str) -> float:
    """Convert a user-supplied ``price`` to the unit yfinance returns.

    ``unit`` is one of:
      * ``"native"`` — pass through unchanged (the default; assumes the
        agent is already working in the same unit yfinance prints).
      * ``"GBP"`` — pounds. For .L tickers we multiply by 100 to get pence.
      * ``"GBX"`` — pence. For .L tickers we pass through; for non-.L
        tickers it's an error to pass GBX, so we just pass through and
        let the comparison fail loudly rather than silently distort.
    """
    u = (unit or "native").strip().upper()
    if u == "GBP" and is_gbx_quoted(ticker):
        return float(price) * 100.0
    return float(price)


def native_to_unit(ticker: str, price: float, unit: str) -> float:
    """Inverse of :func:`unit_to_native` — for displaying triggers back."""
    u = (unit or "native").strip().upper()
    if u == "GBP" and is_gbx_quoted(ticker):
        return float(price) / 100.0
    return float(price)


# ── trigger evaluation (pure, no side effects) ──────────────────────────

def _trail_trigger(stop: Dict[str, Any]) -> Optional[float]:
    """Return the active trigger price for a trailing stop, or None.

    A trailing stop must define one of ``trail_distance`` (absolute) or
    ``trail_distance_pct`` (percentage of high-water mark). When neither
    is set the stop is malformed and we return None to skip evaluation.
    """
    hwm = stop.get("high_water_mark")
    if hwm is None:
        return None
    dist = stop.get("trail_distance")
    if dist is not None:
        return float(hwm) - float(dist)
    pct = stop.get("trail_distance_pct")
    if pct is not None:
        return float(hwm) * (1.0 - float(pct) / 100.0)
    return None


def evaluate_stop(stop: Dict[str, Any], price: float) -> bool:
    """Should this stop fire at *price*? Pure function — no state mutation."""
    if price <= 0:
        return False
    kind = str(stop.get("kind", "")).lower()
    if kind == "stop_loss":
        return price <= float(stop.get("trigger_price", 0.0))
    if kind == "take_profit":
        trigger = float(stop.get("trigger_price", 0.0))
        return trigger > 0 and price >= trigger
    if kind == "trailing_stop":
        trigger = _trail_trigger(stop)
        if trigger is None:
            return False
        return price <= trigger
    return False


# ── the engine ──────────────────────────────────────────────────────────

class StopEngine(threading.Thread):
    """Daemon thread monitoring active stops at sub-second cadence.

    Built once per session by ``AgentPool`` and started before the
    supervisor wakes for the first time. Stops persist across restarts
    via ``paper_state.json`` so an interrupted session resumes
    monitoring seamlessly.
    """

    def __init__(
        self,
        broker_service: Any,
        poll_seconds: float = POLL_SECONDS,
        price_fetcher: Optional[Any] = None,
    ) -> None:
        super().__init__(daemon=True, name="stop-engine")
        self._broker_service = broker_service
        self._poll_seconds = float(poll_seconds)
        # ``price_fetcher`` is a seam for tests — production passes None and
        # we pull live yfinance quotes; tests inject a deterministic
        # ``Callable[[List[str]], Dict[str, float]]``.
        self._price_fetcher = price_fetcher
        self._stop_event = threading.Event()
        self._fired: List[Dict[str, Any]] = []
        self._fired_lock = threading.Lock()
        # Per-ticker rolling price window for momentum detection. Each
        # entry is a deque of (monotonic_ts, price). Pruned to
        # MOMENTUM_WINDOW_SECONDS each tick.
        self._price_history: Dict[str, Deque[Tuple[float, float]]] = {}
        self._momentum_fired: List[Dict[str, Any]] = []

    # ── thread API ───────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the engine to exit on its next tick."""
        self._stop_event.set()

    def run(self) -> None:  # noqa: D401 — threading.Thread API
        if not self._broker_is_paper():
            logger.info("[stop-engine] live broker detected — stop engine idle")
            self._stop_event.wait()
            return

        logger.info("[stop-engine] started (poll=%.2fs)", self._poll_seconds)
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("[stop-engine] tick error")
                self._stop_event.wait(timeout=_BACKOFF_SECONDS)
                continue
            self._stop_event.wait(timeout=self._poll_seconds)
        logger.info("[stop-engine] stopped")

    # ── one tick (public so tests can drive it directly) ──────────────

    def tick(self) -> List[Dict[str, Any]]:
        """One monitor cycle. Returns the list of stops that fired this tick."""
        broker = self._paper_broker()
        if broker is None:
            return []
        stops = broker.list_stops()
        try:
            momentum_triggers = list(broker.list_momentum_triggers())
        except AttributeError:
            momentum_triggers = []

        ticker_set = {s["ticker"] for s in stops}
        ticker_set.update(str(t.get("ticker", "")) for t in momentum_triggers)
        ticker_set.discard("")
        if not ticker_set:
            return []

        prices = self._fetch_prices(sorted(ticker_set))
        now = time.monotonic()
        self._update_price_history(prices, now)
        fired: List[Dict[str, Any]] = []

        for stop in stops:
            ticker = str(stop.get("ticker", ""))
            price = float(prices.get(ticker, 0.0) or 0.0)
            if price <= 0:
                continue

            # Trailing stops walk their high-water mark up in place
            # before evaluation — a stop set the moment the price was
            # at $100 and now sees $105 should anchor at 105.
            if str(stop.get("kind")) == "trailing_stop":
                hwm = stop.get("high_water_mark")
                if hwm is None or price > float(hwm):
                    broker.update_stop(stop["stop_id"], {"high_water_mark": price})
                    stop["high_water_mark"] = price

            if not evaluate_stop(stop, price):
                continue

            if self._fire_stop(stop, price):
                fired.append({**stop, "fill_price": price})

        # Momentum triggers ride the same price feed but evaluate against
        # the rolling window rather than a fixed level.
        for trig in momentum_triggers:
            self._evaluate_momentum_trigger(broker, trig, prices, now)

        if fired:
            with self._fired_lock:
                self._fired.extend(fired)
        return fired

    def consume_fired(self) -> List[Dict[str, Any]]:
        """Drain and return every stop that has fired since the last call.

        The desktop UI polls this to surface fill toasts; tests use it
        to assert which stops triggered.
        """
        with self._fired_lock:
            out = list(self._fired)
            self._fired.clear()
        return out

    # ── internals ────────────────────────────────────────────────────

    def _broker_is_paper(self) -> bool:
        try:
            from paper_broker import PaperBroker
        except Exception:  # pragma: no cover — import error path
            return False
        return isinstance(self._underlying_broker(), PaperBroker)

    def _underlying_broker(self) -> Any:
        # BrokerService exposes ``broker`` for the default (stocks) broker,
        # but tests sometimes pass the PaperBroker instance directly.
        return getattr(self._broker_service, "broker", self._broker_service)

    def _paper_broker(self) -> Any:
        broker = self._underlying_broker()
        try:
            from paper_broker import PaperBroker
        except Exception:  # pragma: no cover
            return None
        return broker if isinstance(broker, PaperBroker) else None

    def _fetch_prices(self, tickers: List[str]) -> Dict[str, float]:
        if not tickers:
            return {}
        if self._price_fetcher is not None:
            try:
                return {t: float(p) for t, p in self._price_fetcher(tickers).items()}
            except Exception:
                logger.exception("[stop-engine] injected price fetcher failed")
                return {}
        try:
            from data_loader import fetch_live_prices
            live = fetch_live_prices(tickers)
        except Exception:
            logger.exception("[stop-engine] live price fetch failed")
            return {}
        return {t: float((live.get(t) or {}).get("price", 0.0) or 0.0) for t in tickers}

    def _fire_stop(self, stop: Dict[str, Any], price: float) -> bool:
        """Submit a market sell for the stopped quantity and remove the stop.

        Returns True when a sell actually went through, False otherwise
        (orphan stop with no position, or broker rejection). Callers
        only record a fill in the fired-buffer when this is True so the
        UI never displays a phantom trade.
        """
        ticker = str(stop["ticker"])
        qty = float(stop["quantity"])
        # Cap by held quantity so a stale stop on a position the agent
        # has already partially exited can't oversell.
        held = self._held_qty(ticker)
        if held <= 0:
            logger.warning(
                "[stop-engine] stop %s on %s has no held position — removing",
                stop.get("stop_id"), ticker,
            )
            self._paper_broker().remove_stop(stop["stop_id"])
            return False
        sell_qty = min(qty, held)
        try:
            self._broker_service.submit_order(
                ticker=ticker,
                side="SELL",
                quantity=sell_qty,
                order_type="market",
            )
        except Exception:
            logger.exception(
                "[stop-engine] failed to submit sell for stop %s on %s",
                stop.get("stop_id"), ticker,
            )
            return False
        self._paper_broker().remove_stop(stop["stop_id"])
        logger.info(
            "[stop-engine] fired %s on %s qty=%s @ %s (trigger=%s)",
            stop.get("kind"), ticker, sell_qty, price, stop.get("trigger_price"),
        )
        return True

    def _held_qty(self, ticker: str) -> float:
        try:
            positions = self._broker_service.get_positions()
        except Exception:
            logger.exception("[stop-engine] could not read positions")
            return 0.0
        for p in positions or []:
            if str(p.get("ticker")) == ticker:
                return float(p.get("quantity", 0.0) or 0.0)
        return 0.0

    # ── momentum trigger helpers ────────────────────────────────────

    def _update_price_history(
        self,
        prices: Dict[str, float],
        now: float,
    ) -> None:
        """Append the latest tick to each ticker's rolling price window."""
        cutoff = now - MOMENTUM_WINDOW_SECONDS
        for ticker, price in prices.items():
            if price <= 0:
                continue
            history = self._price_history.setdefault(ticker, deque())
            history.append((now, float(price)))
            while history and history[0][0] < cutoff:
                history.popleft()

    def _evaluate_momentum_trigger(
        self,
        broker: Any,
        trig: Dict[str, Any],
        prices: Dict[str, float],
        now: float,
    ) -> None:
        """Fire a momentum trigger if its threshold is crossed.

        Drops expired triggers (TTL passed) without firing. Removes the
        trigger after firing so a single trigger only fires once per
        arming.
        """
        trigger_id = str(trig.get("trigger_id", ""))
        ticker = str(trig.get("ticker", ""))
        if not trigger_id or not ticker:
            return

        ttl_ts = trig.get("ttl_ts")
        if ttl_ts is not None:
            try:
                if float(ttl_ts) <= time.time():
                    broker.remove_momentum_trigger(trigger_id)
                    return
            except (TypeError, ValueError):
                pass

        history = self._price_history.get(ticker)
        if not history or len(history) < 2:
            return

        first_price = history[0][1]
        latest_price = history[-1][1]
        if first_price <= 0:
            return

        pct = (latest_price - first_price) / first_price * 100.0
        threshold = float(trig.get("threshold_pct", 0.0) or 0.0)
        direction = str(trig.get("direction", "")).lower()
        if threshold <= 0 or direction not in ("up", "down"):
            return

        crossed = (direction == "up" and pct >= threshold) or (
            direction == "down" and pct <= -threshold
        )
        if not crossed:
            return

        action = str(trig.get("action", "")).lower()
        quantity = float(trig.get("quantity", 0.0) or 0.0)
        if action not in ("buy", "sell") or quantity <= 0:
            broker.remove_momentum_trigger(trigger_id)
            return

        try:
            self._broker_service.submit_order(
                ticker=ticker,
                side=action.upper(),
                quantity=quantity,
                order_type="market",
            )
        except Exception:
            logger.exception(
                "[stop-engine] failed to submit momentum %s for %s",
                action, ticker,
            )
            return

        broker.remove_momentum_trigger(trigger_id)
        fired_record = {
            **trig,
            "fired_price": latest_price,
            "observed_pct": round(pct, 4),
            "fired_at": now_iso(),
        }
        self._momentum_fired.append(fired_record)
        logger.info(
            "[stop-engine] fired momentum %s on %s qty=%s pct=%.3f (thr=%.3f)",
            action, ticker, quantity, pct, threshold,
        )

    def consume_fired_momentum(self) -> List[Dict[str, Any]]:
        """Drain and return every momentum trigger that has fired."""
        out = list(self._momentum_fired)
        self._momentum_fired.clear()
        return out


# ── stop-id helper ──────────────────────────────────────────────────────

def new_stop_id() -> str:
    """Short opaque id used by tools to address an active stop."""
    return f"st-{uuid.uuid4().hex[:10]}"


def now_iso() -> str:
    """ISO-8601 UTC timestamp matching the rest of the broker audit log."""
    return datetime.now(tz=timezone.utc).isoformat()


# ── public construction helpers ─────────────────────────────────────────

def build_stop(
    *,
    ticker: str,
    kind: str,
    quantity: float,
    trigger_price: float = 0.0,
    trail_distance: Optional[float] = None,
    trail_distance_pct: Optional[float] = None,
    high_water_mark: Optional[float] = None,
    reason: str = "",
) -> Dict[str, Any]:
    """Build a stop dict ready for ``PaperBroker.add_stop``.

    Centralised so the tools and tests share validation. Raises
    ``ValueError`` for malformed inputs — callers wrap this in a
    rejected-tool-result envelope.
    """
    kind = (kind or "").strip().lower()
    if kind not in STOP_KINDS:
        raise ValueError(f"unknown stop kind {kind!r}; must be one of {STOP_KINDS}")
    if not ticker:
        raise ValueError("ticker is required")
    if quantity <= 0:
        raise ValueError(f"quantity must be > 0, got {quantity}")

    if kind in ("stop_loss", "take_profit"):
        if trigger_price <= 0:
            raise ValueError(f"{kind} requires a positive trigger_price")
    else:  # trailing_stop
        if trail_distance is None and trail_distance_pct is None:
            raise ValueError(
                "trailing_stop requires trail_distance or trail_distance_pct",
            )
        if trail_distance is not None and trail_distance <= 0:
            raise ValueError("trail_distance must be > 0")
        if trail_distance_pct is not None and not (0 < trail_distance_pct < 100):
            raise ValueError("trail_distance_pct must be between 0 and 100")

    return {
        "stop_id": new_stop_id(),
        "ticker": ticker,
        "kind": kind,
        "quantity": float(quantity),
        "trigger_price": float(trigger_price),
        "trail_distance": (
            float(trail_distance) if trail_distance is not None else None
        ),
        "trail_distance_pct": (
            float(trail_distance_pct) if trail_distance_pct is not None else None
        ),
        "high_water_mark": (
            float(high_water_mark) if high_water_mark is not None else None
        ),
        "reason": reason,
        "created_at": now_iso(),
    }
