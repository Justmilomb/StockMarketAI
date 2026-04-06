"""About dialog — app identity and version."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from desktop import __version__


class AboutDialog(QDialog):
    """Shows app name, company, and version."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Blank")
        self.setFixedSize(340, 200)
        self.setStyleSheet(
            "QDialog { background-color: #000000; border: 1px solid #444444; }"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 20, 24, 16)

        name_label = QLabel("BLANK")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(
            "color: #ffd700; font-size: 28px; font-weight: bold; "
            "font-family: Consolas, monospace; letter-spacing: 3px; border: none;",
        )
        layout.addWidget(name_label)

        company_label = QLabel("CERTIFIED RANDOM")
        company_label.setAlignment(Qt.AlignCenter)
        company_label.setStyleSheet(
            "color: #ff8c00; font-size: 11px; "
            "font-family: Consolas, monospace; letter-spacing: 2px; border: none;",
        )
        layout.addWidget(company_label)

        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(
            "color: #555555; font-size: 10px; "
            "font-family: Consolas, monospace; border: none;",
        )
        layout.addWidget(version_label)

        layout.addSpacing(12)

        close_btn = QPushButton("CLOSE")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)
