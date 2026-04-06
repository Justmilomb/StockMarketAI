"""Mode selector dialog — choose Stocks, Polymarket, or Crypto on startup."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ModeSelector(QDialog):
    """Sharp terminal dialog with 3 mode buttons."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Blank — Select Mode")
        self.setFixedSize(400, 380)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            "QDialog { background-color: #000000; border: 1px solid #444444; }"
        )

        self._selected: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(8)

        # Title
        title = QLabel("BLANK")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #ffd700; font-size: 32px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none; "
            "letter-spacing: 4px;",
        )
        layout.addWidget(title)

        subtitle = QLabel("SELECT TRADING MODE")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "color: #ff8c00; font-size: 11px; "
            "font-family: Consolas, monospace; border: none; "
            "letter-spacing: 2px;",
        )
        layout.addWidget(subtitle)

        layout.addSpacing(16)

        # ── Mode buttons ─────────────────────────────────────────────
        btn_style = (
            "QPushButton {{ "
            "  background-color: #1a1a1a; color: {color}; "
            "  border: 1px solid #444444; "
            "  font-size: 14px; font-weight: bold; "
            "  font-family: Consolas, monospace; "
            "  padding: 12px; min-height: 16px; "
            "}} "
            "QPushButton:hover {{ "
            "  background-color: #2a2a2a; border-color: #ff8c00; "
            "}} "
            "QPushButton:pressed {{ background-color: #333333; }}"
        )

        btn_disabled_style = (
            "QPushButton { "
            "  background-color: #0a0a0a; color: #333333; "
            "  border: 1px solid #222222; "
            "  font-size: 14px; font-weight: bold; "
            "  font-family: Consolas, monospace; "
            "  padding: 12px; min-height: 16px; "
            "}"
        )

        stocks_btn = QPushButton("STOCKS")
        stocks_btn.setStyleSheet(btn_style.format(color="#00ff00"))
        stocks_btn.clicked.connect(lambda: self._select("stocks"))
        layout.addWidget(stocks_btn)

        poly_btn = QPushButton("POLYMARKET")
        poly_btn.setStyleSheet(btn_style.format(color="#00bfff"))
        poly_btn.clicked.connect(lambda: self._select("polymarket"))
        layout.addWidget(poly_btn)

        crypto_btn = QPushButton("CRYPTO  --  COMING SOON")
        crypto_btn.setStyleSheet(btn_disabled_style)
        crypto_btn.setEnabled(False)
        crypto_btn.setToolTip("Crypto trading is not yet available")
        layout.addWidget(crypto_btn)

        layout.addSpacing(12)

        # Quit button
        quit_btn = QPushButton("QUIT")
        quit_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #444444; "
            "  border: none; font-size: 11px; padding: 4px; "
            "  font-family: Consolas, monospace; } "
            "QPushButton:hover { color: #ff0000; }",
        )
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _select(self, mode: str) -> None:
        self._selected = mode
        self.accept()

    def run(self) -> Optional[str]:
        """Show the dialog and return the selected mode, or None if cancelled."""
        _show_modal = getattr(self, "exec")
        result = _show_modal()
        if result == QDialog.Accepted:
            return self._selected
        return None
