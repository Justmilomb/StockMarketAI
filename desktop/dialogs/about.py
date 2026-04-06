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
        self.setFixedSize(360, 220)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        name_label = QLabel("BLANK")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(
            "color: #ffd700; font-size: 36px; font-weight: bold; "
            "font-family: Consolas, monospace;",
        )
        layout.addWidget(name_label)

        company_label = QLabel("Certified Random")
        company_label.setAlignment(Qt.AlignCenter)
        company_label.setStyleSheet(
            "color: #ffb000; font-size: 14px; font-family: Consolas, monospace;",
        )
        layout.addWidget(company_label)

        version_label = QLabel(f"v{__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(
            "color: #888888; font-size: 11px; font-family: Consolas, monospace;",
        )
        layout.addWidget(version_label)

        layout.addSpacing(16)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
