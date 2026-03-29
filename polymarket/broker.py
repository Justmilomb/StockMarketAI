"""Broker implementations for Polymarket.

Two classes:
  - PolymarketBroker: real trading via py-clob-client (lazy import)
  - LogPolymarketBroker: paper trading that logs to JSONL

Both implement the Broker ABC from broker.py so the pipeline can
swap between them transparently.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from broker import Broker

logger = logging.getLogger(__name__)


# ── Live broker ───────────────────────────────────────────────────────


class PolymarketBroker(Broker):
    """Live Polymarket broker using py-clob-client for order execution.

    The py-clob-client package is lazily imported so the rest of the
    polymarket package works without it installed (read-only Gamma API
    calls only need requests).
    """

    def __init__(self, config: Dict[str, str | int | float | bool]) -> None:
        self._config = config
        self._api_url: str = str(config.get("api_url", "https://clob.polymarket.com"))
        self._chain_id: int = int(config.get("chain_id", 137))
        self._private_key_env: str = str(config.get("private_key_env", "POLYMARKET_PRIVATE_KEY"))

        # Lazy-initialised CLOB client
        self._client: object | None = None
        self._client_init_attempted: bool = False

    def _get_client(self) -> object:
        """Lazily initialise the CLOB client.

        Raises ImportError if py-clob-client is not installed, or
        ValueError if the private key env var is missing.
        """
        if self._client is not None:
            return self._client

        if self._client_init_attempted:
            raise ImportError("py-clob-client init previously failed")

        self._client_init_attempted = True

        try:
            from py_clob_client.client import ClobClient
        except ImportError as exc:
            logger.error(
                "py-clob-client not installed. Install with: "
                "pip install py-clob-client"
            )
            raise ImportError(
                "py-clob-client is required for live Polymarket trading"
            ) from exc

        private_key = os.environ.get(self._private_key_env)
        if not private_key:
            raise ValueError(
                f"Environment variable {self._private_key_env} not set. "
                "Required for Polymarket live trading."
            )

        self._client = ClobClient(
            self._api_url,
            key=private_key,
            chain_id=self._chain_id,
        )
        logger.info("Polymarket CLOB client initialised (chain_id=%d)", self._chain_id)
        return self._client

    # ── Core Broker ABC methods ───────────────────────────────────────

    def get_positions(self) -> List[Dict[str, str | float | int]]:
        """Return open positions on Polymarket."""
        try:
            client = self._get_client()
            # py-clob-client doesn't have a direct positions endpoint;
            # positions are tracked via filled orders.  For now, return
            # empty and log — full position tracking needs subgraph queries.
            logger.info("Position tracking via CLOB client is limited; use subgraph for full view")
            return []
        except (ImportError, ValueError) as exc:
            logger.warning("Cannot fetch positions: %s", exc)
            return []

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, str | float | int | None]:
        """Submit an order to Polymarket.

        Args:
            ticker: The condition_id of the market.
            side: "BUY_YES", "BUY_NO", "SELL_YES", or "SELL_NO".
            quantity: Amount in USD to spend.
            order_type: "market" or "limit".
            limit_price: Required for limit orders (probability price 0-1).
            stop_price: Not supported on Polymarket (ignored).
        """
        try:
            client = self._get_client()
        except (ImportError, ValueError) as exc:
            logger.error("Cannot submit order: %s", exc)
            return {"status": "FAILED", "error": str(exc)}

        # Map our side naming to CLOB API expectations
        clob_side = "BUY" if side.startswith("BUY") else "SELL"
        token_outcome = "Yes" if "YES" in side.upper() else "No"

        logger.info(
            "Polymarket order: %s %s on %s, qty=$%.2f, type=%s",
            clob_side, token_outcome, ticker[:16], quantity, order_type,
        )

        # Build and submit order via CLOB client
        try:
            from py_clob_client.order_builder.constants import BUY, SELL

            order_side = BUY if clob_side == "BUY" else SELL
            price = limit_price if limit_price is not None else 0.5

            order_args = {
                "token_id": ticker,
                "price": price,
                "size": quantity,
                "side": order_side,
            }

            signed_order = client.create_order(order_args)  # type: ignore[union-attr]
            result = client.post_order(signed_order)  # type: ignore[union-attr]

            return {
                "status": "SUBMITTED",
                "order_id": str(result.get("orderID", "")),
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "price": price,
            }
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            return {"status": "FAILED", "error": str(exc)}

    def get_account_info(self) -> Dict[str, float | str]:
        """Return account balance information."""
        try:
            self._get_client()
            # CLOB client doesn't expose balance directly;
            # balance is on-chain USDC on Polygon
            return {
                "currency": "USDC",
                "chain": "Polygon",
                "note": "Check USDC balance on Polygon via block explorer",
                "free": 0.0,
                "total": 0.0,
            }
        except (ImportError, ValueError) as exc:
            return {"error": str(exc), "free": 0.0, "total": 0.0}

    def get_pending_orders(self) -> List[Dict[str, str | float | int]]:
        """Return pending/open orders."""
        try:
            client = self._get_client()
            result = client.get_orders()  # type: ignore[union-attr]
            if isinstance(result, list):
                return result
            return []
        except (ImportError, ValueError, Exception) as exc:
            logger.warning("Cannot fetch pending orders: %s", exc)
            return []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID."""
        try:
            client = self._get_client()
            client.cancel(order_id)  # type: ignore[union-attr]
            logger.info("Cancelled Polymarket order %s", order_id)
            return True
        except (ImportError, ValueError, Exception) as exc:
            logger.warning("Cannot cancel order %s: %s", order_id, exc)
            return False


# ── Paper-trading broker ──────────────────────────────────────────────


class LogPolymarketBroker(Broker):
    """Paper-trading broker for Polymarket that logs orders to JSONL.

    Maintains an in-memory virtual balance and position book.
    """

    def __init__(
        self,
        config: Optional[Dict[str, str | int | float | bool]] = None,
        log_path: Optional[Path] = None,
    ) -> None:
        cfg = config or {}
        self._log_path = log_path or Path("logs") / "polymarket_orders.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        self._balance: float = float(cfg.get("paper_balance", 1000.0))
        self._positions: Dict[str, Dict[str, float | str]] = {}

    def get_positions(self) -> List[Dict[str, str | float | int]]:
        """Return virtual open positions."""
        return [
            {
                "condition_id": cid,
                "side": str(pos.get("side", "")),
                "size": float(pos.get("size", 0)),
                "entry_price": float(pos.get("entry_price", 0)),
            }
            for cid, pos in self._positions.items()
        ]

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, str | float | int | None]:
        """Log a paper order and update virtual positions."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "condition_id": ticker,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
            "limit_price": limit_price,
            "status": "PAPER_FILLED",
        }

        # Update virtual balance
        if side.startswith("BUY"):
            cost = quantity
            if self._balance < cost:
                record["status"] = "PAPER_REJECTED_INSUFFICIENT_FUNDS"
            else:
                self._balance -= cost
                price = limit_price or 0.5
                self._positions[ticker] = {
                    "side": side,
                    "size": quantity / price if price > 0 else 0,
                    "entry_price": price,
                }
        elif side.startswith("SELL"):
            if ticker in self._positions:
                pos = self._positions.pop(ticker)
                # Credit back at current price (approximation)
                self._balance += quantity
            else:
                record["status"] = "PAPER_REJECTED_NO_POSITION"

        # Write to log
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError as exc:
            logger.warning("Failed to write paper trade log: %s", exc)

        logger.info(
            "Paper trade: %s %s on %s, qty=$%.2f [%s]",
            side, order_type, ticker[:16], quantity, record["status"],
        )
        return record

    def get_account_info(self) -> Dict[str, float | str]:
        """Return virtual account balance."""
        invested = sum(
            float(pos.get("size", 0)) * float(pos.get("entry_price", 0))
            for pos in self._positions.values()
        )
        return {
            "currency": "USDC (paper)",
            "free": round(self._balance, 2),
            "invested": round(invested, 2),
            "total": round(self._balance + invested, 2),
        }

    def get_pending_orders(self) -> List[Dict[str, str | float | int]]:
        """Paper broker fills instantly — no pending orders."""
        return []

    def cancel_order(self, order_id: str) -> bool:
        """Paper broker has no pending orders to cancel."""
        return False
