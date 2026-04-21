"""Startup sign-in prompt — fully skippable.

Unlike the old licence dialog, this never blocks the app. The user can
skip and browse the UI; gated actions will nudge them to sign in later.

Flow:
  1. User clicks Sign In → we open a loopback HTTP server on a random
     port and pop the browser at ``/auth/login?callback_port=<port>``.
  2. User authenticates on the website.
  3. Website redirects the browser to
     ``http://127.0.0.1:<port>/auth/callback?token=<jwt>``.
  4. Our local handler captures the token. A Qt timer polls for it,
     saves it, pulls user info, and closes the dialog.
"""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Optional
from urllib.parse import urlencode

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop import tokens as T
from desktop.auth import fetch_me, save_token
from desktop.auth_callback_server import CallbackServer, start as start_callback_server
from desktop.auth_state import auth_state
from desktop.license import _read_server_url
from desktop.widgets.primitives.button import apply_variant

logger = logging.getLogger("blank.auth.dialog")


class SignInDialog(QDialog):
    signed_in = Signal()

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setFixedSize(480, 360)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0}; border: 1px solid {T.BORDER_0}; }}"
        )
        self._server_url = _read_server_url()
        self._poll_timer: Optional[QTimer] = None
        self._callback_server: Optional[CallbackServer] = None
        self._done_event: Optional[threading.Event] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(42, 40, 42, 34)

        wordmark = QLabel("blank")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 56px; font-weight: 500; letter-spacing: -0.04em;"
        )
        root.addWidget(wordmark)

        kicker = QLabel("SIGN IN")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px; padding-top: 6px;"
        )
        root.addWidget(kicker)
        root.addSpacing(28)

        caption = QLabel(
            "sign in to enable trading, chat, and the agent.\n"
            "you can skip and explore the app first."
        )
        caption.setAlignment(Qt.AlignCenter)
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS}; font-size: 13px;"
        )
        root.addWidget(caption)

        root.addStretch(1)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFixedHeight(22)
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        skip_btn = QPushButton("SKIP")
        apply_variant(skip_btn, "ghost")
        skip_btn.setCursor(Qt.PointingHandCursor)
        skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(skip_btn, 1)

        self._signin_btn = QPushButton("SIGN IN")
        apply_variant(self._signin_btn, "primary")
        self._signin_btn.setCursor(Qt.PointingHandCursor)
        self._signin_btn.clicked.connect(self._start_browser_flow)
        btn_row.addWidget(self._signin_btn, 1)

        root.addLayout(btn_row)

    def _set_status(self, text: str) -> None:
        self._status.setText(text.upper() if text else "")

    def _start_browser_flow(self) -> None:
        self._signin_btn.setEnabled(False)
        self._set_status("waiting for sign-in in your browser...")
        port, _thread, done, srv = start_callback_server(timeout_seconds=180)
        self._callback_server = srv
        self._done_event = done

        qs = urlencode({"callback_port": str(port)})
        webbrowser.open(f"{self._server_url.rstrip('/')}/auth/login?{qs}")

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._check_callback)
        self._poll_timer.start()

    def _check_callback(self) -> None:
        if not self._callback_server or not self._done_event:
            return
        token = self._callback_server.captured_token
        if token is None and not self._done_event.is_set():
            return

        if self._poll_timer:
            self._poll_timer.stop()
        try:
            self._callback_server.server_close()
        except Exception:
            pass

        if not token:
            self._set_status("sign-in cancelled or timed out")
            self._signin_btn.setEnabled(True)
            return

        save_token(token)
        result = fetch_me(token=token, server_url=self._server_url)
        if not result.get("ok"):
            self._set_status(result.get("reason", "sign-in failed"))
            self._signin_btn.setEnabled(True)
            return

        auth_state().set_signed_in(
            email=result.get("email", ""),
            name=result.get("name", ""),
        )
        self.signed_in.emit()
        self.accept()

    def _on_skip(self) -> None:
        if self._poll_timer:
            self._poll_timer.stop()
        if self._callback_server:
            try:
                self._callback_server.server_close()
            except Exception:
                pass
        self.reject()

    def run(self) -> bool:
        _show = getattr(self, "exec")
        return _show() == QDialog.Accepted
