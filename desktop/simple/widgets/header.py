"""Header bar -- app title, status, and controls for the simple app."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from desktop.design import (
    BG,
    BORDER,
    GLOW,
    GLOW_BORDER,
    SECONDARY_BTN_QSS,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)


class HeaderBar(QFrame):
    """Minimal header matching the blank admin panel style."""

    add_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setStyleSheet(f"""
            HeaderBar {{
                background: {BG};
                border-bottom: 1px solid {BORDER};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 0, 28, 0)
        layout.setSpacing(0)

        # Brand: "blank" bold + "terminal" dim (like admin panel)
        title = QLabel("blank")
        title.setStyleSheet(f"""
            font-size: 20px; font-weight: 700; color: {TEXT};
            font-family: {FONT_FAMILY};
            letter-spacing: -0.5px; background: transparent;
        """)
        layout.addWidget(title)

        mode = QLabel("  terminal")
        mode.setStyleSheet(f"""
            font-size: 20px; font-weight: 300; color: {TEXT_MID};
            font-family: {FONT_FAMILY};
            background: transparent;
        """)
        layout.addWidget(mode)

        layout.addStretch()

        # Status indicator (like "all systems operational")
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(8, 8)
        self._status_dot.setStyleSheet(f"""
            background: {GLOW}; border-radius: 4px;
        """)
        layout.addWidget(self._status_dot)

        self._status_text = QLabel("loading")
        self._status_text.setStyleSheet(f"""
            font-size: 13px; font-weight: 300; color: {TEXT_MID};
            font-family: {FONT_FAMILY};
            padding-left: 8px; background: transparent;
        """)
        layout.addWidget(self._status_text)

        layout.addSpacing(24)

        # Action buttons
        add_btn = QPushButton("+ add")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: 12px; font-weight: 400;
                font-family: {FONT_FAMILY};
                letter-spacing: 0.5px;
                padding: 4px 16px;
                color: {GLOW}; border: 1px solid {GLOW_BORDER};
                border-radius: 2px; background: transparent;
            }}
            QPushButton:hover {{
                background: {GLOW}; color: {BG};
            }}
        """)
        add_btn.clicked.connect(self.add_clicked.emit)
        layout.addWidget(add_btn)

        layout.addSpacing(8)

        refresh_btn = QPushButton("refresh")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setFixedHeight(32)
        refresh_btn.setStyleSheet(SECONDARY_BTN_QSS + f"""
            QPushButton {{
                font-size: 12px; font-weight: 400;
                font-family: {FONT_FAMILY};
                letter-spacing: 0.5px;
                padding: 4px 16px;
            }}
        """)
        refresh_btn.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(refresh_btn)

    def set_status(self, text: str, ok: bool = True) -> None:
        """Update the status indicator."""
        color = GLOW if ok else TEXT_DIM
        self._status_dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self._status_text.setText(text)
