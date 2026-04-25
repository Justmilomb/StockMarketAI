"""Persistent signed-out nudge.

A slim horizontal strip that sits near the top of the main window when
the user is signed out. Clicking it raises the sign-in dialog. It hides
itself the moment ``auth_state().is_signed_in`` flips to True."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from desktop import tokens as T
from desktop.auth_state import auth_state


class SignInBanner(QWidget):
    signin_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"SignInBanner {{ background: {T.BG_1}; border-bottom: 1px solid {T.BORDER_1}; }}"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 8, 12, 8)
        row.setSpacing(12)

        msg = QLabel("SIGN IN TO START TRADING")
        msg.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        row.addWidget(msg)
        row.addStretch(1)

        btn = QPushButton("SIGN IN")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {T.ACCENT_HEX};"
            f" border: 1px solid {T.ACCENT_HEX}; padding: 4px 14px;"
            f" font-family: {T.FONT_MONO}; font-size: 10px; letter-spacing: 2px; }}"
            f"QPushButton:hover {{ background: {T.ACCENT_HEX}; color: {T.BG_0}; }}"
        )
        btn.clicked.connect(self.signin_requested.emit)
        row.addWidget(btn)

        auth_state().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.setVisible(not auth_state().is_signed_in)
