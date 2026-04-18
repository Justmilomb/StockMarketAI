"""License activation dialog — blocks the app until a valid key is entered."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from desktop import tokens as T
from desktop.license import save_key, validate


class LicenseDialog(QDialog):
    """Frameless license gate shown before the app loads."""

    def __init__(self, server_url: str = "http://localhost:8000", parent: object = None) -> None:
        super().__init__(parent)
        self._server_url = server_url
        self.setFixedSize(480, 420)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_0}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(42, 40, 42, 34)
        root.setSpacing(0)

        wordmark = QLabel("blank")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 56px; font-weight: 500; letter-spacing: -0.04em;"
        )
        root.addWidget(wordmark)

        kicker = QLabel("LICENCE REQUIRED")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px; padding-top: 6px;"
        )
        root.addWidget(kicker)

        root.addSpacing(28)

        caption = QLabel("Enter your licence key")
        caption.setAlignment(Qt.AlignCenter)
        caption.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px;"
        )
        root.addWidget(caption)

        root.addSpacing(14)

        self._input = QLineEdit()
        self._input.setPlaceholderText("BLK-XXXX-XXXX")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {T.BORDER_1};"
            f" color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 18px; padding: 8px 0; letter-spacing: 3px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {T.ACCENT_HEX}; }}"
        )
        self._input.returnPressed.connect(self._activate)
        root.addWidget(self._input)

        root.addSpacing(6)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setFixedHeight(24)
        self._set_status("", "dim")
        root.addWidget(self._status)

        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        quit_btn = QPushButton("QUIT")
        quit_btn.setProperty("variant", "ghost")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(self.reject)
        btn_row.addWidget(quit_btn, 1)

        activate_btn = QPushButton("ACTIVATE")
        activate_btn.setProperty("variant", "primary")
        activate_btn.setCursor(Qt.PointingHandCursor)
        activate_btn.clicked.connect(self._activate)
        btn_row.addWidget(activate_btn, 1)

        root.addLayout(btn_row)

    def _set_status(self, text: str, tone: str) -> None:
        palette = {
            "dim": T.FG_2_HEX,
            "ok": T.ACCENT_HEX,
            "error": T.ALERT,
            "warn": T.WARN,
        }
        color = palette.get(tone, T.FG_2_HEX)
        self._status.setStyleSheet(
            f"color: {color}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        self._status.setText(text.upper() if text else "")

    def _activate(self) -> None:
        key = self._input.text().strip().upper()
        if not key:
            self._set_status("enter a licence key", "error")
            return

        self._set_status("connecting\u2026", "warn")
        self._status.repaint()

        def _on_status(msg: str) -> None:
            self._set_status(msg, "warn")
            self._status.repaint()

        result = validate(server_url=self._server_url, key=key, status_callback=_on_status)

        if result.get("valid"):
            save_key(key)
            self._set_status("licence activated", "ok")
            self.accept()
        else:
            reason = result.get("reason", "unknown error")
            self._set_status(reason, "error")

    def run(self) -> bool:
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
