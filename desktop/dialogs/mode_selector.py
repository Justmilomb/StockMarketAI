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
    """Full-screen-ish dark dialog with 3 large mode buttons."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Blank — Select Mode")
        self.setFixedSize(420, 400)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            "QDialog { background-color: #000000; border: 2px solid #ffb000; }"
        )

        self._selected: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)

        # Title
        title = QLabel("BLANK")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #ffd700; font-size: 32px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none;",
        )
        layout.addWidget(title)

        subtitle = QLabel("Select Trading Mode")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            "color: #888888; font-size: 12px; font-family: Consolas, monospace; "
            "border: none;",
        )
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # ── Mode buttons ─────────────────────────────────────────────
        btn_style = (
            "QPushButton {{ "
            "  background-color: #111111; color: {color}; "
            "  border: 1px solid #444444; font-size: 16px; "
            "  font-family: Consolas, monospace; font-weight: bold; "
            "  padding: 16px; min-height: 40px; "
            "}} "
            "QPushButton:hover {{ background-color: #222222; border-color: #ffb000; }} "
            "QPushButton:pressed {{ background-color: #333333; }}"
        )

        btn_disabled_style = (
            "QPushButton { "
            "  background-color: #0a0a0a; color: #444444; "
            "  border: 1px solid #222222; font-size: 16px; "
            "  font-family: Consolas, monospace; font-weight: bold; "
            "  padding: 16px; min-height: 40px; "
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

        crypto_btn = QPushButton("CRYPTO  (Coming Soon)")
        crypto_btn.setStyleSheet(btn_disabled_style)
        crypto_btn.setEnabled(False)
        crypto_btn.setToolTip("Crypto trading is not yet available")
        layout.addWidget(crypto_btn)

        layout.addSpacing(8)

        # Quit button
        quit_btn = QPushButton("Quit")
        quit_btn.setStyleSheet(
            "QPushButton { background-color: #0a0a0a; color: #666666; "
            "  border: 1px solid #333333; font-size: 11px; padding: 6px; } "
            "QPushButton:hover { color: #ff5555; border-color: #ff5555; }",
        )
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _select(self, mode: str) -> None:
        self._selected = mode
        self.accept()

    def run(self) -> Optional[str]:
        """Show the dialog and return the selected mode, or None if cancelled."""
        # QDialog modal — shows and blocks until user picks
        _show_modal = getattr(self, "exec")
        result = _show_modal()
        if result == QDialog.Accepted:
            return self._selected
        return None
