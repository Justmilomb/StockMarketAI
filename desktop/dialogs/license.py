"""License activation dialog -- blocks the app until a valid key is entered."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from desktop.design import (
    APP_NAME_UPPER,
    BASE_QSS,
    BG,
    BORDER,
    GLOW,
    GLOW_BORDER,
    RED,
    SECONDARY_BTN_QSS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)
from desktop.license import save_key, validate


class LicenseDialog(QDialog):
    """Prompts for a license key and validates it against the server."""

    def __init__(self, server_url: str = "http://localhost:8000", parent: object = None) -> None:
        super().__init__(parent)
        self._server_url = server_url
        self.setWindowTitle("blank")
        self.setFixedSize(440, 300)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(BASE_QSS + f"""
            QDialog {{ border: 1px solid {BORDER}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(0)

        # Title
        title = QLabel(APP_NAME_UPPER)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {TEXT}; font-size: 36px; font-weight: 700;
            font-family: {FONT_FAMILY}; letter-spacing: -1px;
        """)
        layout.addWidget(title)

        layout.addSpacing(4)

        # Subtitle
        subtitle = QLabel("ENTER LICENSE KEY")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 3px;
        """)
        layout.addWidget(subtitle)

        layout.addSpacing(24)

        # Input
        self._input = QLineEdit()
        self._input.setPlaceholderText("BLK-XXXX-XXXX")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 2px;
                padding: 12px; font-size: 16px; font-weight: 400;
                font-family: {FONT_FAMILY}; letter-spacing: 2px;
            }}
            QLineEdit:focus {{ border-color: {GLOW_BORDER}; }}
        """)
        self._input.returnPressed.connect(self._activate)
        layout.addWidget(self._input)

        layout.addSpacing(8)

        # Status
        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setFixedHeight(20)
        self._status.setStyleSheet(f"""
            color: {RED}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 1px;
        """)
        layout.addWidget(self._status)

        layout.addSpacing(12)

        # Activate button
        activate_btn = QPushButton("ACTIVATE")
        activate_btn.setCursor(Qt.PointingHandCursor)
        activate_btn.clicked.connect(self._activate)
        layout.addWidget(activate_btn)

        layout.addSpacing(8)

        # Quit
        quit_btn = QPushButton("QUIT")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setStyleSheet(SECONDARY_BTN_QSS)
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _activate(self) -> None:
        key = self._input.text().strip().upper()
        if not key:
            self._status.setText("ENTER A LICENSE KEY")
            return

        self._status.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 1px;
        """)
        self._status.setText("VALIDATING...")
        self._status.repaint()

        result = validate(server_url=self._server_url, key=key)

        if result.get("valid"):
            save_key(key)
            self._status.setStyleSheet(f"""
                color: {GLOW}; font-size: 11px; font-weight: 300;
                font-family: {FONT_FAMILY}; letter-spacing: 1px;
            """)
            self._status.setText("LICENSE ACTIVATED")
            self.accept()
        else:
            reason = result.get("reason", "unknown error")
            self._status.setStyleSheet(f"""
                color: {RED}; font-size: 11px; font-weight: 300;
                font-family: {FONT_FAMILY}; letter-spacing: 1px;
            """)
            self._status.setText(reason.upper())

    def run(self) -> bool:
        """Show the dialog. Returns True if license validated, False if cancelled."""
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
