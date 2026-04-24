from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class Broker(ABC):
    """
    Abstract broker interface. Core trading methods are abstract;
    extended methods (history, pies, metadata) have default empty
    implementations so only brokers that support them need override.
    """

    # ── Core (abstract) ───────────────────────────────────────────────

    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_pending_orders(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError

    # ── Extended (default empty implementations) ──────────────────────

    def modify_order(
        self,
        order_id: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Adjust an open order's trigger levels in-place.

        Default: not supported. Brokers that can edit live orders
        (PaperBroker, and eventually Trading212Broker) override this.
        """
        return {
            "status": "REJECTED",
            "reason": "modify_order is not supported by this broker",
        }

    def get_account_metadata(self) -> Dict[str, Any]:
        return {}

    def get_order_history(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return {"items": [], "next_cursor": None}

    def get_dividends(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return {"items": [], "next_cursor": None}

    def get_transactions(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        return {"items": [], "next_cursor": None}

    def get_order_executions(self, order_id: str) -> List[Dict[str, Any]]:
        return []

    def get_pies(self) -> List[Dict[str, Any]]:
        return []

    def get_pie(self, pie_id: int) -> Dict[str, Any]:
        return {}

    def create_pie(self, name: str, instruments: Dict[str, float]) -> Dict[str, Any]:
        return {}

    def update_pie(self, pie_id: int, instruments: Dict[str, float]) -> Dict[str, Any]:
        return {}

    def delete_pie(self, pie_id: int) -> bool:
        return False

    def get_instruments(self) -> List[Dict[str, Any]]:
        return []

    def get_exchanges(self) -> List[Dict[str, Any]]:
        return []


@dataclass
class LogBrokerConfig:
    log_path: Path = Path("logs") / "orders.jsonl"


class LogBroker(Broker):
    """
    Development broker that logs intended orders to a JSONL file.
    Extended methods return empty data since there's no real account.
    """

    def __init__(self, config: Optional[LogBrokerConfig] = None) -> None:
        if config is None:
            config = LogBrokerConfig()
        self.config = config
        self.config.log_path.parent.mkdir(parents=True, exist_ok=True)

    def get_positions(self) -> List[Dict[str, Any]]:
        return []

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "status": "LOGGED",
        }
        with self.config.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record

    def get_account_info(self) -> Dict[str, Any]:
        return {
            "free": 100000.0,
            "invested": 0.0,
            "result": 0.0,
            "total": 100000.0,
            "currency": "USD",
        }

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        return []

    def cancel_order(self, order_id: str) -> bool:
        return False
