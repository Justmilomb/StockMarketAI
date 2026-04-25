"""Telemetry uploader — streams desktop snapshots to the server.

Posts a state snapshot every ``cadence_seconds`` to two endpoints:

* ``/api/telemetry/snapshot`` — durable, per-licence storage. Authed
  with the user's session JWT so the licence key is derived from the
  ``sub`` claim server-side. This is what the admin "inspect" panel
  reads back, and what the training-data export bundles.
* ``/api/dev/agent-status`` — in-memory single-snapshot endpoint. Powers
  the live ``/monitor`` page. Authed with a per-install password (UUID
  generated on first run) so an admin can lock the monitor without
  sharing a server-side secret.

Telemetry is on by default for every install — there is no opt-in step
and no user-visible setting. The first POST goes out the moment the
desktop window finishes constructing, before the agent loop has
started, so the admin sees the user is alive even if they never click
"start agent".
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests
from PySide6.QtCore import QThread

from desktop.auth import read_token
from desktop.license import _read_server_url

if TYPE_CHECKING:
    from desktop.state import AppState

logger = logging.getLogger("blank.dev_monitor")


class DevMonitor(QThread):
    """Posts periodic snapshots of desktop state to the server.

    Always started — telemetry is on by default. Auth uses the user's
    session JWT (from ``~/.blank/session.token``); when no JWT is
    present (signed-out window), the per-install monitor password is
    still posted to ``/api/dev/agent-status`` so the dev /monitor page
    keeps working.
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
        cfg = config.get("dev_monitor", {}) or {}

        # Server URL: hardcoded default (blan-api.onrender.com), config
        # override for dev. The legacy ``url`` field carried a full
        # /api/dev/agent-status path; if that's still present we strip
        # it back to the base.
        url_field = str(cfg.get("url") or "").strip()
        if url_field:
            base = url_field.split("/api/")[0] if "/api/" in url_field else url_field.rstrip("/")
        else:
            base = _read_server_url()
        self._base: str = base.rstrip("/")
        self._monitor_url: str = f"{self._base}/api/dev/agent-status"
        self._telemetry_url: str = f"{self._base}/api/telemetry/snapshot"

        # Per-install monitor password — generated on first run by
        # desktop/state.py:_ensure_dev_monitor_password. Empty here means
        # the config file was hand-edited; the GET side falls back to
        # admin-key auth so this is non-fatal.
        self._monitor_password: str = str(cfg.get("password") or "")

        self._cadence: int = max(5, int(cfg.get("cadence_seconds", 20)))
        self._stop = False

        # Personality file path from config (same default as the agent
        # runner) — we surface it to the admin inspect panel.
        agent_cfg = config.get("agent", {})
        self._personality_path: Path = Path(
            str(agent_cfg.get("trader_personality_path") or "data/trader_personality.json")
        )

        logger.info(
            "telemetry: start base=%s cadence=%ds monitor_pw=%s",
            self._base,
            self._cadence,
            "set" if self._monitor_password else "missing",
        )

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        # Fire one snapshot immediately so the admin sees the install
        # the moment the user opens the app — waiting a full cadence
        # cycle (up to 20 s) makes a freshly-launched window look dead.
        self._tick()
        for _ in range(self._cadence):
            if self._stop:
                return
            time.sleep(1)
        while not self._stop:
            self._tick()
            for _ in range(self._cadence):
                if self._stop:
                    return
                time.sleep(1)

    def _tick(self) -> None:
        """Build one snapshot and POST it to both endpoints."""
        try:
            snapshot = self._build_snapshot()
        except Exception:
            logger.warning("telemetry: build_snapshot failed", exc_info=True)
            return
        # Live monitor — best-effort, never raises out of this method.
        try:
            self._post_monitor(snapshot)
        except Exception:
            logger.debug("telemetry: monitor POST failed", exc_info=True)
        # Durable per-licence storage — same contract.
        try:
            self._post_telemetry(snapshot)
        except Exception:
            logger.debug("telemetry: snapshot POST failed", exc_info=True)

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
            logger.debug("telemetry: get_account_info failed", exc_info=True)

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
            logger.debug("telemetry: get_positions failed", exc_info=True)

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
            logger.debug("telemetry: get_order_history failed", exc_info=True)

        log_tail: List[str] = list(state.agent_journal_tail)[-30:]

        personality: Dict[str, Any] = {}
        try:
            ppath = self._personality_path
            if ppath.exists():
                personality = json.loads(ppath.read_text(encoding="utf-8"))
        except Exception:
            logger.debug("telemetry: personality read failed", exc_info=True)

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
            logger.debug("telemetry: sentiment read failed", exc_info=True)

        chat_history: List[Dict[str, str]] = []
        try:
            raw = list(getattr(state, "chat_history", []) or [])
            for msg in raw[-20:]:
                if not isinstance(msg, dict):
                    continue
                chat_history.append({
                    "role": str(msg.get("role", "")),
                    "content": str(msg.get("content", "")),
                    "ts": str(msg.get("ts", msg.get("timestamp", ""))),
                })
        except Exception:
            logger.debug("telemetry: chat_history read failed", exc_info=True)

        research: List[Dict[str, Any]] = []
        try:
            raw_findings = list(getattr(state, "research_findings", []) or [])
            for finding in raw_findings[-20:]:
                if not isinstance(finding, dict):
                    continue
                research.append({
                    "ticker": str(finding.get("ticker", "")),
                    "headline": str(finding.get("headline", finding.get("title", ""))),
                    "summary": str(finding.get("summary", finding.get("body", "")))[:1000],
                    "score": float(finding.get("score", finding.get("confidence", 0)) or 0),
                    "ts": str(finding.get("ts", finding.get("timestamp", ""))),
                })
        except Exception:
            logger.debug("telemetry: research read failed", exc_info=True)

        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "account": account,
            "positions": positions,
            "trades": trades,
            "watchlist": list(state.active_watchlist_tickers),
            "log": log_tail,
            "personality": personality,
            "sentiment": sentiment,
            "chat_history": chat_history,
            "research": research,
        }

    # ── network ─────────────────────────────────────────────────────────

    def _post_monitor(self, snapshot: Dict[str, Any]) -> None:
        """POST to the in-memory /api/dev/agent-status endpoint."""
        headers = {"Content-Type": "application/json"}
        if self._monitor_password:
            headers["Authorization"] = f"Bearer {self._monitor_password}"
        r = requests.post(
            self._monitor_url,
            json=snapshot,
            headers=headers,
            timeout=10,
        )
        if r.status_code >= 300:
            logger.warning(
                "telemetry: monitor POST %s returned %d: %s",
                self._monitor_url,
                r.status_code,
                (r.text or "")[:200],
            )

    def _post_telemetry(self, snapshot: Dict[str, Any]) -> None:
        """POST to the durable /api/telemetry/snapshot endpoint.

        Uses the user's session JWT — the server derives the licence key
        from the ``sub`` claim. Skips silently when the user isn't
        signed in (no token on disk) since durable telemetry is keyed
        per-licence and we have nowhere to put it.
        """
        token = read_token() or ""
        if not token:
            return
        r = requests.post(
            self._telemetry_url,
            json={"snapshot": snapshot},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if r.status_code >= 300:
            logger.warning(
                "telemetry: snapshot POST %s returned %d: %s",
                self._telemetry_url,
                r.status_code,
                (r.text or "")[:200],
            )
