"""Single-active-session enforcement client.

Talks to the three ``/api/me/session/*`` endpoints in ``server/app.py``:

* :meth:`SessionManager.register` claims the active-session slot for the
  signed-in account. Returns one of the :class:`RegisterOutcome` codes
  so the caller can either start the heartbeat loop, prompt the user to
  take over, or surface a network error.
* :meth:`SessionManager.force_takeover` evicts the incumbent device and
  registers ours.
* :meth:`SessionManager.start` begins a 1 s QTimer that POSTs heartbeats.
  When the server returns 409 (another device took over) the manager
  emits :attr:`SessionManager.session_taken_over` and stops the timer.

The device id is a fresh UUID per launch — each terminal invocation is
its own session, so closing and reopening the app naturally re-claims
the slot. The device label is informational only ("Milo's PC — Windows
10") so a future takeover dialog can name the other device.
"""
from __future__ import annotations

import logging
import platform
import socket
import uuid
from typing import Optional

import requests
from PySide6.QtCore import QObject, QTimer, Signal

from desktop.auth import read_token
from desktop.license import _read_server_url

logger = logging.getLogger("blank.session")

#: Heartbeat cadence. Matches SESSION_DEAD_AFTER_SECONDS=5 on the server
#: with comfortable headroom — a single dropped packet shouldn't evict us.
HEARTBEAT_INTERVAL_MS = 1000

#: HTTP timeout for register/heartbeat/takeover. Kept short so a network
#: stall doesn't freeze the UI thread on the synchronous registration call.
REQUEST_TIMEOUT_SECONDS = 8


class RegisterOutcome:
    """Result codes for :meth:`SessionManager.register`."""
    OK = "ok"
    CONFLICT = "conflict"          # another device holds the slot
    UNAUTHORISED = "unauthorised"  # token invalid/expired
    OFFLINE = "offline"            # network error or server down
    ERROR = "error"                # unexpected server response


class SessionManager(QObject):
    """Holds the active-session slot for a signed-in user.

    The class is a Qt object so the heartbeat fires on the main thread —
    POST + JSON parsing is fast enough at 1 Hz that this won't visibly
    block the UI, and it keeps the takeover-detected signal trivially
    safe to react to (e.g. raising a QMessageBox)."""

    #: Emitted when a heartbeat returns 409 — another device claimed
    #: the slot. Payload is a human-readable message for the dialog.
    session_taken_over = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._device_id = uuid.uuid4().hex
        self._device_label = self._build_device_label()
        self._server_url = _read_server_url()
        self._timer: Optional[QTimer] = None
        self._active = False
        self._consecutive_network_errors = 0

    @staticmethod
    def _build_device_label() -> str:
        """Best-effort human label for the takeover dialog. We never
        rely on this being unique — the device_id is the identity."""
        try:
            host = socket.gethostname() or "unknown"
        except Exception:
            host = "unknown"
        try:
            os_name = f"{platform.system()} {platform.release()}".strip()
        except Exception:
            os_name = "unknown"
        label = f"{host} — {os_name}".strip(" —")
        return label[:120]

    @property
    def device_id(self) -> str:
        return self._device_id

    @property
    def device_label(self) -> str:
        return self._device_label

    @property
    def is_active(self) -> bool:
        return self._active

    # ── HTTP helpers ────────────────────────────────────────────────

    def _post(self, path: str, body: dict[str, object]) -> requests.Response:
        token = read_token() or ""
        url = f"{self._server_url.rstrip('/')}{path}"
        return requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    # ── Public API ──────────────────────────────────────────────────

    def register(self) -> str:
        """Claim the session slot. Returns a :class:`RegisterOutcome`."""
        try:
            resp = self._post(
                "/api/me/session/register",
                {"device_id": self._device_id, "device_label": self._device_label},
            )
        except requests.RequestException as exc:
            logger.info("session/register network error: %s", exc)
            return RegisterOutcome.OFFLINE

        if resp.status_code == 200:
            return RegisterOutcome.OK
        if resp.status_code == 409:
            return RegisterOutcome.CONFLICT
        if resp.status_code in (401, 403):
            return RegisterOutcome.UNAUTHORISED
        logger.warning(
            "session/register unexpected status %s: %s", resp.status_code, resp.text[:200],
        )
        return RegisterOutcome.ERROR

    def force_takeover(self) -> str:
        """Evict the incumbent device and claim the slot."""
        try:
            resp = self._post(
                "/api/me/session/force-takeover",
                {"device_id": self._device_id, "device_label": self._device_label},
            )
        except requests.RequestException as exc:
            logger.info("session/force-takeover network error: %s", exc)
            return RegisterOutcome.OFFLINE

        if resp.status_code == 200:
            return RegisterOutcome.OK
        if resp.status_code in (401, 403):
            return RegisterOutcome.UNAUTHORISED
        logger.warning(
            "session/force-takeover unexpected status %s: %s",
            resp.status_code, resp.text[:200],
        )
        return RegisterOutcome.ERROR

    def start(self) -> None:
        """Begin posting heartbeats every second."""
        if self._timer is not None:
            return
        self._active = True
        self._consecutive_network_errors = 0
        timer = QTimer(self)
        timer.setInterval(HEARTBEAT_INTERVAL_MS)
        timer.timeout.connect(self._on_tick)
        timer.start()
        self._timer = timer
        logger.info("session heartbeat started (device_id=%s)", self._device_id)

    def stop(self) -> None:
        """Stop the heartbeat timer. Idempotent."""
        if self._timer is not None:
            try:
                self._timer.stop()
                self._timer.deleteLater()
            except Exception:
                pass
            self._timer = None
        self._active = False

    # ── Internals ───────────────────────────────────────────────────

    def _on_tick(self) -> None:
        if not self._active:
            return
        try:
            resp = self._post(
                "/api/me/session/heartbeat",
                {"device_id": self._device_id},
            )
        except requests.RequestException as exc:
            # Tolerate transient network drops — we only treat the
            # session as lost when the server explicitly tells us so.
            self._consecutive_network_errors += 1
            if self._consecutive_network_errors in (1, 5, 30):
                logger.info(
                    "session heartbeat network error (#%d): %s",
                    self._consecutive_network_errors, exc,
                )
            return

        self._consecutive_network_errors = 0

        if resp.status_code == 200:
            return
        if resp.status_code == 409:
            message = "your session was taken over by another device"
            try:
                detail = resp.json().get("detail")
                if isinstance(detail, dict):
                    message = detail.get("message") or message
                elif isinstance(detail, str) and detail:
                    message = detail
            except Exception:
                pass
            logger.warning("session heartbeat: server says taken over")
            self.stop()
            self.session_taken_over.emit(message)
            return
        if resp.status_code in (401, 403):
            # Token revoked / expired — treat the same as a takeover so
            # the user gets booted instead of silently flat-lining.
            logger.warning("session heartbeat: auth rejected (%s)", resp.status_code)
            self.stop()
            self.session_taken_over.emit("your session has expired — please sign in again")
            return
        logger.warning(
            "session heartbeat unexpected status %s: %s",
            resp.status_code, resp.text[:200],
        )


_singleton: Optional[SessionManager] = None


def session_manager() -> SessionManager:
    """Process-wide :class:`SessionManager` (lazy)."""
    global _singleton
    if _singleton is None:
        _singleton = SessionManager()
    return _singleton


def reset_session_manager() -> None:
    """Drop the singleton (used on sign-out so the next sign-in mints a
    fresh device_id and starts a clean heartbeat loop)."""
    global _singleton
    if _singleton is not None:
        try:
            _singleton.stop()
        except Exception:
            pass
        try:
            _singleton.deleteLater()
        except Exception:
            pass
    _singleton = None
