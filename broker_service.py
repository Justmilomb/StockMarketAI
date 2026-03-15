from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from broker import Broker, LogBroker, LogBrokerConfig
from trading212 import Trading212Broker, Trading212BrokerConfig


ConfigDict = Dict[str, Any]


@dataclass
class BrokerService:
    """
    Broker-agnostic facade that chooses and manages the concrete broker
    implementation (LogBroker vs Trading212Broker) based on configuration.
    """

    config: ConfigDict
    _broker: Broker | None = None

    def _create_broker(self) -> Broker:
        broker_cfg = self.config.get("broker", {}) or {}
        broker_type = broker_cfg.get("type", "log")

        if broker_type == "trading212":
            api_key = broker_cfg.get("api_key", "")
            secret_key = broker_cfg.get("secret_key", "")
            base_url = broker_cfg.get("base_url", "https://demo.trading212.com")
            practice = bool(broker_cfg.get("practice", True))
            if not api_key:
                print("[broker_service] Missing Trading 212 api_key - falling back to LogBroker.")
                return LogBroker(LogBrokerConfig())
            cfg = Trading212BrokerConfig(
                api_key=api_key, secret_key=secret_key,
                base_url=base_url, practice=practice,
            )
            return Trading212Broker(cfg)

        return LogBroker(LogBrokerConfig())

    @property
    def broker(self) -> Broker:
        if self._broker is None:
            self._broker = self._create_broker()
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
