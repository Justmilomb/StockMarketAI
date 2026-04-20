"""Dev-only remote monitoring — streams desktop snapshots to the server."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
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
        self._key: str = cfg.get("password", "")
        self._cadence: int = max(5, int(cfg.get("cadence_seconds", 20)))
        self._stop = False

        # license key for telemetry upload (best-effort; empty = skip)
        try:
            from desktop.license import _read_stored_key
            self._license_key: str = _read_stored_key() or ""
        except Exception:
            self._license_key = ""

        # derive telemetry endpoint from the dev-monitor base URL
        _base = self._url.split("/api/")[0] if "/api/" in self._url else self._url.rsplit("/", 3)[0]
        self._telemetry_url: str = f"{_base}/api/telemetry/snapshot"

        # personality file path from config (same default as agent runner)
        _agent_cfg = config.get("agent", {})
        self._personality_path: Path = Path(
            str(_agent_cfg.get("trader_personality_path") or "data/trader_personality.json")
        )

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        while not self._stop:
            snapshot: Optional[Dict[str, Any]] = None
            try:
                snapshot = self._build_snapshot()
                self._post(snapshot)
            except Exception:
                logger.debug("dev_monitor: post failed", exc_info=True)
            if snapshot is not None:
                try:
                    self._post_telemetry(snapshot)
                except Exception:
                    logger.debug("dev_monitor: telemetry post failed", exc_info=True)
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

        personality: Dict[str, Any] = {}
        try:
            ppath = self._personality_path
            if ppath.exists():
                personality = json.loads(ppath.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("dev_monitor: personality read failed", exc_info=True)

        sentiment: Dict[str, float] = {}
        try:
            ns = dict(state.news_sentiment or {})
            scored = [
                (t, float(v.get("sentiment_score", 0)) if isinstance(v, dict) else 0.0)
                for t, v in ns.items()
            ]
            scored.sort(key=lambda x: abs(x[1]), reverse=True)
            sentiment = {t: s for t, s in scored[:5]}
        except Exception:
            logger.debug("dev_monitor: sentiment read failed", exc_info=True)

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "license_key": self._license_key,
            "agent": agent,
            "account": account,
            "positions": positions,
            "trades": trades,
            "watchlist": list(state.active_watchlist_tickers),
            "log": log_tail,
            "personality": personality,
            "sentiment": sentiment,
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

    def _post_telemetry(self, snapshot: Dict[str, Any]) -> None:
        if not self._license_key:
            return
        r = requests.post(
            self._telemetry_url,
            json={"license_key": self._license_key, "snapshot": snapshot},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if r.status_code >= 300:
            logger.debug("dev_monitor: telemetry returned %d", r.status_code)
