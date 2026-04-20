"""Dev-only remote monitoring — streams desktop snapshots to the server."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests
from PySide6.QtCore import QThread

if TYPE_CHECKING:
    from desktop.state import AppState

logger = logging.getLogger("blank.dev_monitor")


class DevMonitor(QThread):
    """Posts periodic snapshots of desktop state to the server.

    Only started when config["dev_monitor"]["enabled"] is true.
    Authenticates with the admin key via Bearer token so the endpoint
    is not publicly readable.
    """

    def __init__(
        self,
        state: "AppState",
        broker_service: Any,
        config: Dict[str, Any],
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._broker = broker_service
        cfg = config.get("dev_monitor", {})
        self._url: str = cfg.get(
            "url", "https://api.useblank.ai/api/dev/agent-status"
        )
        self._key: str = cfg.get("key", "")
        self._cadence: int = max(5, int(cfg.get("cadence_seconds", 20)))
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        while not self._stop:
            try:
                snapshot = self._build_snapshot()
                self._post(snapshot)
            except Exception:
                logger.debug("dev_monitor: post failed", exc_info=True)
            for _ in range(self._cadence):
                if self._stop:
                    return
                time.sleep(1)

    # ── snapshot building ─────────────────────────────────────────────────

    def _build_snapshot(self) -> Dict[str, Any]:
        state = self._state

        last_at: Optional[str] = None
        if state.last_iteration_ts is not None:
            try:
                last_at = state.last_iteration_ts.isoformat()
            except Exception:
                pass

        agent: Dict[str, Any] = {
            "running": state.agent_running,
            "paper_mode": state.agent_paper_mode,
            "last_at": last_at,
            "summary": state.last_summary or "",
        }

        account: Dict[str, Any] = {
            "cash": 0.0,
            "invested": 0.0,
            "total": 0.0,
            "pnl": 0.0,
            "currency": "GBP",
        }
        try:
            info = self._broker.get_account_info()
            account = {
                "cash": float(info.get("free", 0)),
                "invested": float(info.get("invested", 0)),
                "total": float(info.get("total", 0)),
                "pnl": float(info.get("result", info.get("realised_pnl", 0))),
                "currency": info.get("currency", "GBP"),
            }
        except Exception:
            logger.debug("dev_monitor: get_account_info failed", exc_info=True)

        positions: List[Dict[str, Any]] = []
        try:
            for p in self._broker.get_positions():
                positions.append({
                    "ticker": p.get("ticker", ""),
                    "qty": float(p.get("quantity", 0)),
                    "cost": float(p.get("avg_price", 0)),
                    "price": float(p.get("current_price", 0)),
                    "pnl": float(p.get("unrealised_pnl", 0)),
                })
        except Exception:
            logger.debug("dev_monitor: get_positions failed", exc_info=True)

        trades: List[Dict[str, Any]] = []
        try:
            result = self._broker.get_order_history(limit=10)
            items = result.get("items", []) if isinstance(result, dict) else (result or [])
            for item in items[:10]:
                trades.append({
                    "side": item.get("side", ""),
                    "ticker": item.get("ticker", ""),
                    "qty": float(item.get("filled_quantity", item.get("quantity", 0))),
                    "price": float(item.get("fill_price", item.get("price", 0))),
                    "ts": str(item.get("filled_at", item.get("created_at", ""))),
                })
        except Exception:
            logger.debug("dev_monitor: get_order_history failed", exc_info=True)

        log_tail: List[str] = list(state.agent_journal_tail)[-30:]

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "account": account,
            "positions": positions,
            "trades": trades,
            "watchlist": list(state.active_watchlist_tickers),
            "log": log_tail,
        }

    def _post(self, snapshot: Dict[str, Any]) -> None:
        r = requests.post(
            self._url,
            json=snapshot,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if r.status_code >= 300:
            logger.debug("dev_monitor: server returned %d", r.status_code)
