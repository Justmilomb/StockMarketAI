"""License activation dialog — blocks the app until a valid key is entered."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from desktop.license import save_key, validate


class LicenseDialog(QDialog):
    """Terminal-styled dialog that prompts for a license key and validates it."""

    def __init__(self, server_url: str = "http://localhost:8000", parent: object = None) -> None:
        super().__init__(parent)
        self._server_url = server_url
        self.setWindowTitle("Blank — License")
        self.setFixedSize(440, 300)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            "QDialog { background-color: #000000; border: 1px solid #444444; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(8)

        # Title
        title = QLabel("BLANK")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #ffd700; font-size: 28px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none; letter-spacing: 4px;",
        )
        layout.addWidget(title)

        subtitle = QLabel("ENTER LICENSE KEY")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "color: #ff8c00; font-size: 11px; "
            "font-family: Consolas, monospace; border: none; letter-spacing: 2px;",
        )
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        # Input
        self._input = QLineEdit()
        self._input.setPlaceholderText("BLK-XXXX-XXXX")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setStyleSheet(
            "QLineEdit { "
            "  background-color: #0a0a0a; color: #ffffff; "
            "  border: 1px solid #444444; padding: 10px; "
            "  font-size: 16px; font-family: Consolas, monospace; "
            "  letter-spacing: 2px; "
            "} "
            "QLineEdit:focus { border-color: #ff8c00; }",
        )
        self._input.returnPressed.connect(self._activate)
        layout.addWidget(self._input)

        layout.addSpacing(8)

        # Status
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "color: #ff4444; font-size: 10px; "
            "font-family: Consolas, monospace; border: none;",
        )
        layout.addWidget(self._status)

        layout.addSpacing(4)

        # Activate button
        activate_btn = QPushButton("ACTIVATE")
        activate_btn.setStyleSheet(
            "QPushButton { "
            "  background-color: #1a1a1a; color: #00ff00; "
            "  border: 1px solid #444444; "
            "  font-size: 13px; font-weight: bold; "
            "  font-family: Consolas, monospace; "
            "  padding: 10px; "
            "} "
            "QPushButton:hover { background-color: #2a2a2a; border-color: #00ff00; } "
            "QPushButton:pressed { background-color: #333333; }",
        )
        activate_btn.clicked.connect(self._activate)
        layout.addWidget(activate_btn)

        # Quit
        quit_btn = QPushButton("QUIT")
        quit_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #444444; "
            "  border: none; font-size: 11px; padding: 4px; "
            "  font-family: Consolas, monospace; } "
            "QPushButton:hover { color: #ff0000; }",
        )
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _activate(self) -> None:
        key = self._input.text().strip().upper()
        if not key:
            self._status.setText("ENTER A LICENSE KEY")
            return

        self._status.setStyleSheet(
            "color: #888888; font-size: 10px; "
            "font-family: Consolas, monospace; border: none;",
        )
        self._status.setText("VALIDATING...")
        self._status.repaint()

        result = validate(server_url=self._server_url, key=key)

        if result.get("valid"):
            save_key(key)
            self._status.setStyleSheet(
                "color: #00ff00; font-size: 10px; "
                "font-family: Consolas, monospace; border: none;",
            )
            self._status.setText("LICENSE ACTIVATED")
            self.accept()
        else:
            reason = result.get("reason", "unknown error")
            self._status.setStyleSheet(
                "color: #ff4444; font-size: 10px; "
                "font-family: Consolas, monospace; border: none;",
            )
            self._status.setText(reason.upper())

    def run(self) -> bool:
        """Show the dialog. Returns True if license validated, False if cancelled."""
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
