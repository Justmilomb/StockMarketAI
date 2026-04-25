from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from broker import Broker


@dataclass
class Trading212BrokerConfig:
    api_key: str
    secret_key: str
    base_url: str = "https://demo.trading212.com"
    practice: bool = True


class Trading212Broker(Broker):
    """
    Full Trading 212 broker via REST API v0.
    Covers: portfolio, orders, account, history (orders/dividends/transactions),
    pies (CRUD), instrument metadata, and order executions.
    """

    def __init__(self, config: Trading212BrokerConfig) -> None:
        self.config = config
        if not config.practice:
            self.config.base_url = "https://live.trading212.com"

        token_str = f"{self.config.api_key}:{self.config.secret_key}"
        encoded_token = base64.b64encode(token_str.encode("utf-8")).decode("utf-8")

        self._headers = {
            "Authorization": f"Basic {encoded_token}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}/api/v0{path}"

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        resp = requests.get(
            self._url(path), headers=self._headers, params=params, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Dict) -> Any:
        resp = requests.post(
            self._url(path), headers=self._headers, json=body, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _patch(self, path: str, body: Dict) -> Any:
        resp = requests.patch(
            self._url(path), headers=self._headers, json=body, timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> bool:
        resp = requests.delete(self._url(path), headers=self._headers, timeout=15)
        return resp.status_code in (200, 204)

    # ── Portfolio ──────────────────────────────────────────────────────

    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch all open positions.

        LSE-listed tickers (T212 spelling: ``RRl_EQ``, ``BBYl_EQ``,
        ``VUKGl_EQ`` — lowercase ``l`` before ``_EQ``) are quoted in
        pence by the T212 portfolio API. Divide ``avg_price`` and
        ``current_price`` by 100 here so the rest of the app reads
        pounds. The P&L fields (``ppl`` / ``fxPpl``) come back in the
        account currency already and need no conversion.
        """
        from fx import is_pence_quoted
        try:
            raw = self._get("/equity/portfolio")
            out: List[Dict[str, Any]] = []
            for p in raw:
                ticker = p.get("ticker", "")
                avg = float(p.get("averagePrice", 0.0) or 0.0)
                cur = float(p.get("currentPrice", 0.0) or 0.0)
                if is_pence_quoted(ticker):
                    avg /= 100.0
                    cur /= 100.0
                out.append({
                    "ticker": ticker,
                    "quantity": p.get("quantity", 0),
                    "avg_price": avg,
                    "current_price": cur,
                    "ppl": p.get("ppl"),
                    "unrealised_pnl": p.get("fxPpl") if p.get("fxPpl") is not None else p.get("ppl", 0.0),
                    "pie_quantity": p.get("pieQuantity", 0.0),
                    "initial_fill_date": p.get("initialFillDate", ""),
                })
            return out
        except Exception as e:
            print(f"[t212] Error fetching positions: {e}")
            return []

    # ── Account ────────────────────────────────────────────────────────

    def get_account_info(self) -> Dict[str, Any]:
        """Get account cash and equity info."""
        try:
            raw = self._get("/equity/account/cash")
            pie_result = raw.get("pieTotalResult", {})
            return {
                "free": raw.get("free", 0.0),
                "invested": raw.get("invested", 0.0),
                "result": pie_result.get("result", 0.0) if isinstance(pie_result, dict) else raw.get("result", 0.0),
                "total": raw.get("total", 0.0),
                "pie_invested": pie_result.get("investedOverall", 0.0) if isinstance(pie_result, dict) else 0.0,
                "pie_value": pie_result.get("value", 0.0) if isinstance(pie_result, dict) else 0.0,
                "blocked": raw.get("blocked", 0.0),
            }
        except Exception as e:
            print(f"[t212] Error fetching account info: {e}")
            return {"free": 0.0, "invested": 0.0, "result": 0.0, "total": 0.0}

    def get_account_metadata(self) -> Dict[str, Any]:
        """Get account ID, currency, and creation date."""
        try:
            return self._get("/equity/account/info")
        except Exception as e:
            print(f"[t212] Error fetching account metadata: {e}")
            return {}

    # ── Orders (pending) ───────────────────────────────────────────────

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get all pending/open orders."""
        try:
            raw = self._get("/equity/orders")
            return [
                {
                    "id": o.get("id", ""),
                    "ticker": o.get("ticker", ""),
                    "side": "BUY" if o.get("quantity", 0) > 0 else "SELL",
                    "quantity": abs(o.get("quantity", 0)),
                    "order_type": o.get("type", "UNKNOWN"),
                    "limit_price": o.get("limitPrice"),
                    "stop_price": o.get("stopPrice"),
                    "status": o.get("status", "PENDING"),
                    "created": o.get("creationTime", ""),
                }
                for o in raw
            ]
        except Exception as e:
            print(f"[t212] Error fetching orders: {e}")
            return []

    def cancel_order(self, order_id: str) -> bool:
        return self._delete(f"/equity/orders/{order_id}")

    # ── Order Submission ───────────────────────────────────────────────

    def submit_order(
        self,
        ticker: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Place an order. T212 uses negative quantity for SELL."""
        qty = quantity if side.upper() == "BUY" else -abs(quantity)

        endpoints = {
            "market": ("/equity/orders/market", {"ticker": ticker, "quantity": qty}),
            "limit": ("/equity/orders/limit", {
                "ticker": ticker, "quantity": qty,
                "limitPrice": limit_price, "timeValidity": "Day",
            }),
            "stop": ("/equity/orders/stop", {
                "ticker": ticker, "quantity": qty,
                "stopPrice": stop_price, "timeValidity": "Day",
            }),
            "stop_limit": ("/equity/orders/stop_limit", {
                "ticker": ticker, "quantity": qty,
                "limitPrice": limit_price, "stopPrice": stop_price,
                "timeValidity": "Day",
            }),
        }

        if order_type not in endpoints:
            raise ValueError(f"Unknown order type: {order_type}")

        endpoint, body = endpoints[order_type]
        try:
            result = self._post(endpoint, body)
            return {
                "ticker": ticker, "side": side, "quantity": abs(quantity),
                "order_type": order_type, "status": "SUBMITTED", "response": result,
            }
        except requests.HTTPError as e:
            error_msg = str(e)
            try:
                error_msg = e.response.text
            except Exception:
                pass
            return {
                "ticker": ticker, "side": side, "quantity": abs(quantity),
                "order_type": order_type, "status": "FAILED", "error": error_msg,
            }

    # ── Order Executions ───────────────────────────────────────────────

    def get_order_executions(self, order_id: str) -> List[Dict[str, Any]]:
        """Get execution details for a specific order."""
        try:
            raw = self._get(f"/equity/history/orders/{order_id}")
            executions = raw.get("fills", [])
            return [
                {
                    "price": f.get("price", 0.0),
                    "quantity": f.get("quantity", 0.0),
                    "date": f.get("dateTime", ""),
                }
                for f in executions
            ]
        except Exception as e:
            print(f"[t212] Error fetching executions for {order_id}: {e}")
            return []

    # ── History ────────────────────────────────────────────────────────

    def _get_paginated(self, path: str, limit: int, cursor: Optional[str]) -> Dict[str, Any]:
        """Shared cursor-based pagination for history endpoints."""
        params: Dict[str, Any] = {"limit": min(limit, 50)}
        if cursor:
            params["cursor"] = cursor
        try:
            raw = self._get(path, params=params)
            items = raw.get("items", [])
            next_path = raw.get("nextPagePath", "")
            next_cursor = None
            if next_path and "cursor=" in next_path:
                next_cursor = next_path.split("cursor=")[-1].split("&")[0]
            return {"items": items, "next_cursor": next_cursor}
        except Exception as e:
            print(f"[t212] Error fetching {path}: {e}")
            return {"items": [], "next_cursor": None}

    def get_order_history(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Historical completed orders with pagination.

        Derives ``side`` from the signed raw ``quantity`` first — a
        cancelled order keeps its sign there even when
        ``filledQuantity`` is 0. Falls back to signed filled qty when
        raw is missing. Rows with no attributable side are skipped
        entirely so they don't render as blank red "SELL" entries in
        the orders panel.
        """
        result = self._get_paginated("/equity/history/orders", limit, cursor)
        cleaned: List[Dict[str, Any]] = []
        for o in result["items"]:
            raw_qty = o.get("quantity", 0) or 0
            filled_qty = o.get("filledQuantity", 0) or 0
            signed = raw_qty if raw_qty else filled_qty
            if signed == 0:
                continue
            cleaned.append({
                "id": o.get("id", ""),
                "ticker": o.get("ticker", ""),
                "side": "BUY" if signed > 0 else "SELL",
                "quantity": abs(filled_qty or raw_qty),
                "fill_price": o.get("fillPrice", o.get("filledPrice", 0.0)),
                "order_type": o.get("type", ""),
                "status": o.get("status", ""),
                "date": o.get("dateModified", o.get("dateCreated", "")),
                "fill_cost": o.get("fillCost", 0.0),
            })
        result["items"] = cleaned
        return result

    def get_dividends(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Dividend payout history with pagination."""
        result = self._get_paginated("/equity/history/dividends", limit, cursor)
        result["items"] = [
            {
                "ticker": d.get("ticker", ""),
                "amount": d.get("amount", 0.0),
                "amount_in_euro": d.get("amountInEuro", 0.0),
                "quantity": d.get("quantity", 0.0),
                "gross_per_share": d.get("grossAmountPerShare", 0.0),
                "paid_on": d.get("paidOn", ""),
                "reference": d.get("reference", ""),
            }
            for d in result["items"]
        ]
        return result

    def get_transactions(self, limit: int = 50, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Transaction history (deposits, withdrawals, fees, etc.) with pagination."""
        result = self._get_paginated("/equity/history/transactions", limit, cursor)
        result["items"] = [
            {
                "type": t.get("type", ""),
                "amount": t.get("amount", 0.0),
                "currency": t.get("currency", ""),
                "date": t.get("dateTime", t.get("dateModified", "")),
                "reference": t.get("reference", ""),
                "status": t.get("status", ""),
            }
            for t in result["items"]
        ]
        return result

    # ── Pies ───────────────────────────────────────────────────────────

    def get_pies(self) -> List[Dict[str, Any]]:
        """List all investment pies."""
        try:
            raw = self._get("/equity/pies")
            return [
                {
                    "id": p.get("id", 0),
                    "name": p.get("settings", {}).get("name", "Unnamed"),
                    "dividend_action": p.get("settings", {}).get("dividendCashAction", ""),
                    "icon": p.get("settings", {}).get("icon", ""),
                    "goal": p.get("settings", {}).get("goal", 0),
                    "invested": p.get("result", {}).get("investedOverall", 0.0),
                    "value": p.get("result", {}).get("value", 0.0),
                    "result_coef": p.get("result", {}).get("resultCoef", 1.0),
                    "cash": p.get("cash", 0.0),
                    "status": p.get("status", ""),
                }
                for p in raw
            ]
        except Exception as e:
            print(f"[t212] Error fetching pies: {e}")
            return []

    def get_pie(self, pie_id: int) -> Dict[str, Any]:
        """Get detailed info for a specific pie including instrument allocations."""
        try:
            raw = self._get(f"/equity/pies/{pie_id}")
            instruments = raw.get("instruments", [])
            settings = raw.get("settings", {})
            result = raw.get("result", {})
            return {
                "id": pie_id,
                "name": settings.get("name", ""),
                "dividend_action": settings.get("dividendCashAction", ""),
                "goal": settings.get("goal", 0),
                "end_date": settings.get("endDate"),
                "instruments": [
                    {
                        "ticker": i.get("ticker", ""),
                        "expected_share": i.get("expectedShare", 0.0),
                        "current_share": i.get("currentShare", 0.0),
                        "owned_quantity": i.get("ownedQuantity", 0.0),
                        "result": i.get("result", {}).get("investedValue", 0.0),
                        "value": i.get("result", {}).get("value", 0.0),
                    }
                    for i in instruments
                ],
                "invested": result.get("investedOverall", 0.0),
                "value": result.get("value", 0.0),
                "cash": raw.get("cash", 0.0),
            }
        except Exception as e:
            print(f"[t212] Error fetching pie {pie_id}: {e}")
            return {}

    def create_pie(self, name: str, instruments: Dict[str, float]) -> Dict[str, Any]:
        """
        Create a new pie. instruments is {ticker: target_share_pct}.
        Shares must sum to 1.0.
        """
        body = {
            "dividendCashAction": "Reinvest",
            "goal": 0,
            "icon": "Home",
            "instrumentShares": instruments,
            "name": name,
        }
        try:
            return self._post("/equity/pies", body)
        except Exception as e:
            print(f"[t212] Error creating pie: {e}")
            return {}

    def update_pie(self, pie_id: int, instruments: Dict[str, float]) -> Dict[str, Any]:
        """Update pie instrument allocations. Shares must sum to 1.0."""
        body = {"instrumentShares": instruments}
        try:
            return self._patch(f"/equity/pies/{pie_id}", body)
        except Exception as e:
            print(f"[t212] Error updating pie {pie_id}: {e}")
            return {}

    def delete_pie(self, pie_id: int) -> bool:
        return self._delete(f"/equity/pies/{pie_id}")

    # ── Metadata ───────────────────────────────────────────────────────

    def get_instruments(self) -> List[Dict[str, Any]]:
        """Get all tradeable instruments with metadata."""
        try:
            raw = self._get("/equity/metadata/instruments")
            return [
                {
                    "ticker": i.get("ticker", ""),
                    "name": i.get("name", ""),
                    "currency": i.get("currencyCode", ""),
                    "exchange": i.get("exchangeId", ""),
                    "type": i.get("type", ""),
                    "isin": i.get("isin", ""),
                    "min_trade_qty": i.get("minTradeQuantity", 0.0),
                    "max_open_qty": i.get("maxOpenQuantity", 0.0),
                    "added_on": i.get("addedOn", ""),
                }
                for i in raw
            ]
        except Exception as e:
            print(f"[t212] Error fetching instruments: {e}")
            return []

    def get_exchanges(self) -> List[Dict[str, Any]]:
        """Get all available exchanges."""
        try:
            raw = self._get("/equity/metadata/exchanges")
            return [
                {
                    "id": ex.get("id", ""),
                    "name": ex.get("name", ""),
                    "open_time": ex.get("workingSchedules", [{}])[0].get("open", "") if ex.get("workingSchedules") else "",
                    "close_time": ex.get("workingSchedules", [{}])[0].get("close", "") if ex.get("workingSchedules") else "",
                }
                for ex in raw
            ]
        except Exception as e:
            print(f"[t212] Error fetching exchanges: {e}")
            return []
