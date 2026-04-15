from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from broker import Broker, LogBroker, LogBrokerConfig
from trading212 import Trading212Broker, Trading212BrokerConfig
from types_shared import AssetClass


ConfigDict = Dict[str, Any]


@dataclass
class BrokerService:
    """
    Broker-agnostic facade that chooses and manages the concrete broker
    implementation (LogBroker vs Trading212Broker) based on configuration.

    Supports multi-broker routing: different asset classes (stocks, crypto,
    polymarket) can each have their own broker instance.  The default
    ``broker`` property delegates to the stocks broker for backwards
    compatibility.
    """

    config: ConfigDict
    _broker: Broker | None = None
    _brokers: Dict[AssetClass, Broker] = field(default_factory=dict)

    def _create_broker(self, asset_class: AssetClass = "stocks") -> Broker:
        """Create and return a broker for the given asset class.

        Currently only stocks brokers are created here.  Crypto and
        polymarket brokers will register themselves via ``register_broker``
        once their implementations exist.
        """
        if asset_class != "stocks":
            # Non-stock asset classes are not yet supported for auto-creation;
            # they must be registered externally via register_broker().
            return LogBroker(LogBrokerConfig())

        broker_cfg = self.config.get("broker", {}) or {}
        broker_type = broker_cfg.get("type", "log")

        if broker_type == "trading212":
            api_key_env = broker_cfg.get("api_key_env", "T212_API_KEY")
            secret_key_env = broker_cfg.get("secret_key_env", "T212_SECRET_KEY")
            api_key = os.getenv(api_key_env, "")
            secret_key = os.getenv(secret_key_env, "")
            base_url = broker_cfg.get("base_url", "https://live.trading212.com")
            practice = bool(broker_cfg.get("practice", False))
            if not api_key:
                print("[broker_service] Missing Trading 212 api_key - falling back to LogBroker.")
                return LogBroker(LogBrokerConfig())
            cfg = Trading212BrokerConfig(
                api_key=api_key, secret_key=secret_key,
                base_url=base_url, practice=practice,
            )
            return Trading212Broker(cfg)

        return LogBroker(LogBrokerConfig())

    def get_broker(self, asset_class: AssetClass = "stocks") -> Broker:
        """Return the broker for *asset_class*, creating it on first access."""
        if asset_class not in self._brokers:
            self._brokers[asset_class] = self._create_broker(asset_class)
        return self._brokers[asset_class]

    def register_broker(self, asset_class: AssetClass, broker: Broker) -> None:
        """Register an externally-created broker for a given asset class."""
        self._brokers[asset_class] = broker

    @property
    def broker(self) -> Broker:
        """Default broker — delegates to the stocks broker for backwards compat."""
        if self._broker is None:
            self._broker = self.get_broker("stocks")
        return self._broker

    @property
    def is_live(self) -> bool:
        """True if connected to a real broker (not LogBroker)."""
        return isinstance(self.broker, Trading212Broker)

    # ── Core Trading ──────────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.broker.get_positions()

    def get_account_info(self) -> Dict[str, Any]:
        return self.broker.get_account_info()

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        return self.broker.get_pending_orders()

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        return self.broker.submit_order(
            ticker=ticker, side=side, quantity=quantity,
            order_type=order_type, limit_price=limit_price,
            stop_price=stop_price,
        )

    def submit_orders(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Submit a batch of orders."""
        return [
            self.submit_order(
                ticker=str(o["ticker"]), side=str(o["side"]),
                quantity=float(o["quantity"]),
                order_type=str(o.get("order_type", "market")),
                limit_price=o.get("limit_price"),
                stop_price=o.get("stop_price"),
            )
            for o in orders
        ]

    def cancel_order(self, order_id: str) -> bool:
        return self.broker.cancel_order(order_id)

    def reset_paper(self) -> bool:
        """Reset the paper stocks broker to its config starting cash.

        No-op + ``False`` when the stocks broker is not a
        ``PaperBroker`` (i.e. live mode). Returns ``True`` on a
        successful reset so callers can show a status message.
        """
        from paper_broker import PaperBroker
        broker = self.get_broker("stocks")
        if not isinstance(broker, PaperBroker):
            return False
        broker.reset()
        return True

    # ── Account Extended ──────────────────────────────────────────────

    def get_account_metadata(self) -> Dict[str, Any]:
        return self.broker.get_account_metadata()

    # ── History ────────────────────────────────────────────────────────

    def get_order_history(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return self.broker.get_order_history(limit=limit, cursor=cursor)

    def get_dividends(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return self.broker.get_dividends(limit=limit, cursor=cursor)

    def get_transactions(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return self.broker.get_transactions(limit=limit, cursor=cursor)

    def get_order_executions(self, order_id: str) -> List[Dict[str, Any]]:
        return self.broker.get_order_executions(order_id)

    # ── Pies ──────────────────────────────────────────────────────────

    def get_pies(self) -> List[Dict[str, Any]]:
        return self.broker.get_pies()

    def get_pie(self, pie_id: int) -> Dict[str, Any]:
        return self.broker.get_pie(pie_id)

    def create_pie(self, name: str, instruments: Dict[str, float]) -> Dict[str, Any]:
        return self.broker.create_pie(name, instruments)

    def update_pie(self, pie_id: int, instruments: Dict[str, float]) -> Dict[str, Any]:
        return self.broker.update_pie(pie_id, instruments)

    def delete_pie(self, pie_id: int) -> bool:
        return self.broker.delete_pie(pie_id)

    # ── Metadata ──────────────────────────────────────────────────────

    def get_instruments(self) -> List[Dict[str, Any]]:
        return self.broker.get_instruments()

    def get_exchanges(self) -> List[Dict[str, Any]]:
        return self.broker.get_exchanges()
