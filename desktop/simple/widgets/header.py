"""Header bar — app title and control buttons for the simple app."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from desktop.simple.theme import COLORS


class HeaderBar(QFrame):
    """Minimal header with app title and action buttons."""

    add_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet(
            f"HeaderBar {{ background: #000000; "
            f"border-bottom: 1px solid {COLORS['border']}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        # Title
        title = QLabel("blank")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #ffffff;"
            " letter-spacing: -0.5px; background: transparent;",
        )
        layout.addWidget(title)

        layout.addStretch()

        # Action buttons
        add_btn = QPushButton("+ add")
        add_btn.setFixedHeight(32)
        add_btn.clicked.connect(self.add_clicked.emit)
        layout.addWidget(add_btn)

        refresh_btn = QPushButton("refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(self.refresh_clicked.emit)
        layout.addWidget(refresh_btn)
