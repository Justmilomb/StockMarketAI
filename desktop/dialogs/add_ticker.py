"""Add ticker dialog — single-input dialog for a symbol."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


class AddTickerDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            kicker="WATCHLIST",
            title="Add ticker",
            parent=parent,
        )
        self.setFixedSize(420, 220)
        self.ticker: str = ""

        body = self.body_layout()

        hint = QLabel("Enter a ticker symbol. Examples: AAPL, TSLA, RR.L.")
        hint.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px;"
        )
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("AAPL")
        self._input.returnPressed.connect(self._accept)
        self._input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {T.BORDER_1};"
            f" color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 16px; padding: 6px 0; letter-spacing: 1px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {T.ACCENT_HEX}; }}"
        )
        body.addWidget(self._input)
        body.addStretch(1)

        self.add_footer_button("CANCEL", variant="ghost", slot=self.reject)
        self.add_footer_button("ADD", variant="primary", slot=self._accept)

    def _accept(self) -> None:
        self.ticker = self._input.text().strip().upper()
        if self.ticker:
            self.accept()
