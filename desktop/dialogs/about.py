"""About dialog -- app identity and version."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from desktop import __version__
from desktop.design import (
    APP_NAME_UPPER,
    BASE_QSS,
    BORDER,
    COMPANY_UPPER,
    GLOW,
    SECONDARY_BTN_QSS,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)


class AboutDialog(QDialog):
    """Shows app name, company, and version."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedSize(340, 220)
        self.setStyleSheet(BASE_QSS + f"""
            QDialog {{ border: 1px solid {BORDER}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(32, 28, 32, 20)

        name_label = QLabel(APP_NAME_UPPER)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(f"""
            color: {TEXT}; font-size: 36px; font-weight: 700;
            font-family: {FONT_FAMILY}; letter-spacing: -1px;
        """)
        layout.addWidget(name_label)

        layout.addSpacing(2)

        company_label = QLabel(COMPANY_UPPER)
        company_label.setAlignment(Qt.AlignCenter)
        company_label.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 3px;
        """)
        layout.addWidget(company_label)

        layout.addSpacing(4)

        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 10px; font-weight: 300;
            font-family: {FONT_FAMILY};
        """)
        layout.addWidget(version_label)

        layout.addSpacing(16)

        close_btn = QPushButton("CLOSE")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(SECONDARY_BTN_QSS)
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)
