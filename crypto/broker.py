"""Crypto broker implementations.

Provides two classes:
- ``CryptoBroker``: Live trading via ccxt exchange connections.
- ``LogCryptoBroker``: Paper trading that logs orders to JSONL.

Both implement the ``Broker`` ABC from ``broker.py``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from broker import Broker

logger = logging.getLogger(__name__)


@dataclass
class CryptoBrokerConfig:
    """Configuration for connecting to a crypto exchange."""

    exchange_name: str = "binance"
    api_key_env: str = "CRYPTO_API_KEY"
    secret_key_env: str = "CRYPTO_SECRET_KEY"
    testnet: bool = True
    rate_limit: bool = True
    timeout_ms: int = 30_000


class CryptoBroker(Broker):
    """Live crypto broker using ccxt.

    Maps the abstract Broker interface to ccxt exchange methods:
    - get_positions()    -> exchange.fetch_balance()
    - submit_order()     -> exchange.create_order()
    - get_account_info() -> exchange.fetch_balance()
    - get_pending_orders() -> exchange.fetch_open_orders()
    - cancel_order()     -> exchange.cancel_order()
    """

    def __init__(self, config: CryptoBrokerConfig | None = None) -> None:
        self._config = config or CryptoBrokerConfig()
        self._exchange = None  # Lazy init

    def _get_exchange(self):  # noqa: ANN202
        """Lazily initialise the ccxt exchange instance."""
        if self._exchange is not None:
            return self._exchange

        try:
            import ccxt
        except ImportError:
            raise ImportError(
                "ccxt is required for CryptoBroker. Install with: pip install ccxt"
            )

        api_key = os.environ.get(self._config.api_key_env, "")
        secret = os.environ.get(self._config.secret_key_env, "")

        exchange_class = getattr(ccxt, self._config.exchange_name, None)
        if exchange_class is None:
            raise ValueError(f"Exchange '{self._config.exchange_name}' not found in ccxt")

        exchange_params: Dict[str, object] = {
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": self._config.rate_limit,
            "timeout": self._config.timeout_ms,
        }

        self._exchange = exchange_class(exchange_params)

        # Enable testnet/sandbox if configured
        if self._config.testnet:
            self._exchange.set_sandbox_mode(True)
            logger.info("CryptoBroker: using %s TESTNET", self._config.exchange_name)

        return self._exchange

    def get_positions(self) -> List[Dict[str, object]]:
        """Fetch current holdings from the exchange."""
        exchange = self._get_exchange()
        try:
            balance = exchange.fetch_balance()
            positions: List[Dict[str, object]] = []

            # ccxt balance has 'total', 'free', 'used' dicts keyed by currency
            total = balance.get("total", {})
            for currency, amount in total.items():
                if amount and float(amount) > 0:
                    positions.append({
                        "ticker": currency,
                        "quantity": float(amount),
                        "currentPrice": 0.0,  # Would need a ticker fetch per asset
                        "ppl": 0.0,
                        "fxImpact": None,
                    })

            return positions
        except Exception as exc:
            logger.error("CryptoBroker.get_positions failed: %s", exc)
            return []

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, object]:
        """Submit an order to the exchange.

        Args:
            ticker: Trading pair (e.g. "BTC/USDT").
            side: "buy" or "sell".
            quantity: Amount to trade.
            order_type: "market" or "limit".
            limit_price: Required for limit orders.
            stop_price: Not directly supported -- ignored for now.
        """
        exchange = self._get_exchange()
        try:
            price = limit_price if order_type == "limit" else None
            result = exchange.create_order(
                symbol=ticker,
                type=order_type,
                side=side.lower(),
                amount=quantity,
                price=price,
            )
            logger.info(
                "CryptoBroker: %s %s %.6f %s @ %s",
                side, ticker, quantity, order_type,
                price or "market",
            )
            return {
                "id": result.get("id", ""),
                "status": result.get("status", "unknown"),
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "price": result.get("price") or result.get("average"),
            }
        except Exception as exc:
            logger.error("CryptoBroker.submit_order failed: %s", exc)
            return {"status": "ERROR", "error": str(exc)}

    def get_account_info(self) -> Dict[str, object]:
        """Fetch account balance summary."""
        exchange = self._get_exchange()
        try:
            balance = exchange.fetch_balance()
            total_info = balance.get("info", {})

            # Extract USDT balance as the primary denominator
            usdt_free = float(balance.get("free", {}).get("USDT", 0.0))
            usdt_used = float(balance.get("used", {}).get("USDT", 0.0))
            usdt_total = float(balance.get("total", {}).get("USDT", 0.0))

            return {
                "free": usdt_free,
                "invested": usdt_used,
                "result": 0.0,  # PnL requires historical tracking
                "total": usdt_total,
                "currency": "USDT",
                "raw": total_info,
            }
        except Exception as exc:
            logger.error("CryptoBroker.get_account_info failed: %s", exc)
            return {"free": 0.0, "invested": 0.0, "result": 0.0, "total": 0.0}

    def get_pending_orders(self) -> List[Dict[str, object]]:
        """Fetch open orders from the exchange."""
        exchange = self._get_exchange()
        try:
            open_orders = exchange.fetch_open_orders()
            return [
                {
                    "id": order.get("id", ""),
                    "ticker": order.get("symbol", ""),
                    "side": order.get("side", ""),
                    "quantity": order.get("amount", 0.0),
                    "order_type": order.get("type", ""),
                    "price": order.get("price"),
                    "status": order.get("status", ""),
                }
                for order in open_orders
            ]
        except Exception as exc:
            logger.error("CryptoBroker.get_pending_orders failed: %s", exc)
            return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by ID."""
        exchange = self._get_exchange()
        try:
            exchange.cancel_order(order_id)
            logger.info("CryptoBroker: cancelled order %s", order_id)
            return True
        except Exception as exc:
            logger.error("CryptoBroker.cancel_order failed: %s", exc)
            return False


@dataclass
class LogCryptoBrokerConfig:
    """Configuration for the paper-trading crypto broker."""

    log_path: Path = Path("logs") / "crypto_orders.jsonl"
    starting_balance: float = 10_000.0


class LogCryptoBroker(Broker):
    """Paper-trading crypto broker that logs orders to JSONL.

    Mirrors ``LogBroker`` from ``broker.py`` but with crypto-specific
    defaults (USDT balance, fractional quantities).
    """

    def __init__(self, config: LogCryptoBrokerConfig | None = None) -> None:
        self._config = config or LogCryptoBrokerConfig()
        self._config.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._balance: float = self._config.starting_balance

    def get_positions(self) -> List[Dict[str, object]]:
        return []

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, object]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "status": "LOGGED",
            "asset_class": "crypto",
        }
        with self._config.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        logger.info("LogCryptoBroker: %s %s %.6f %s", side, ticker, quantity, order_type)
        return record

    def get_account_info(self) -> Dict[str, object]:
        return {
            "free": self._balance,
            "invested": 0.0,
            "result": 0.0,
            "total": self._balance,
            "currency": "USDT",
        }

    def get_pending_orders(self) -> List[Dict[str, object]]:
        return []

    def cancel_order(self, order_id: str) -> bool:
        return False
