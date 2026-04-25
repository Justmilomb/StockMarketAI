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
  closed elsewhere) — log warning, leave the order in place. The
  agent's next iteration will see the stop list and can decide what
  to do.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from core.protective_orders import ProtectiveOrder, ProtectiveStore

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

    def run(self) -> None:  # noqa: D401 - Thread.run override
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
        """Submit each fired order as a market SELL.

        Returns the ids we managed to send. Failures stay in the store
        so the agent can see them on its next iteration.
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
                    "protective: %s on %s fired @ trigger=%.4f -> %s",
                    o.kind.value, o.ticker, o.trigger_price,
                    (resp or {}).get("status", "?"),
                )
                executed.append(o.id)
            except Exception:
                logger.exception(
                    "protective: failed to execute %s on %s",
                    o.kind.value, o.ticker,
                )
        return executed
