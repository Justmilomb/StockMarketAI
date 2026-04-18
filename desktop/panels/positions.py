"""Positions panel — holdings table.

Shows only what the agent-native pipeline actually populates: ticker,
quantity, average entry price, current price, and unrealised P/L.
The legacy Strategy / Regime / Held / Intent columns were removed
when the ``position_notes`` table stopped being written to — they
were rendering ``--`` on every row.
"""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

COLUMNS = ["Ticker", "Qty", "Avg Px", "Cur Px", "PnL"]

#: Currency symbol lookup for the prices column. Kept in-panel to avoid
#: a core-agent import from the UI layer. GBX (UK pence) is the odd one
#: out — Trading 212 quotes some LSE names in pence, so we divide by
#: 100 and render in pounds so the user doesn't read "7820" as £7,820.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$", "GBP": "£", "EUR": "€", "JPY": "¥", "CHF": "CHF ",
    "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "HKD": "HK$", "SGD": "S$",
    "SEK": "kr ", "NOK": "kr ", "DKK": "kr ", "PLN": "zł ",
    "GBX": "£",
}


def _format_price(value: float, currency: str) -> str:
    ccy = (currency or "").strip().upper()
    if ccy == "GBX":
        return f"£{value / 100:.2f}"
    symbol = _CURRENCY_SYMBOLS.get(ccy, "")
    return f"{symbol}{value:.2f}"


class PositionsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("POSITIONS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        positions = state.positions or []
        self.table.setRowCount(len(positions))
        for row, pos in enumerate(positions):
            ticker = pos.get("ticker", "")
            qty = float(pos.get("quantity", 0))
            avg_px = float(pos.get("avg_price", pos.get("averagePrice", 0)))
            cur_px = float(pos.get("current_price", avg_px))
            pnl_val = pos.get("unrealised_pnl") or pos.get("ppl") or 0.0
            try:
                pnl = float(pnl_val)
            except (TypeError, ValueError):
                pnl = 0.0

            # Trading 212 returns the native quote currency per instrument
            # (e.g. TSLA in USD, VUKG.L in GBX). Fall back to USD when the
            # field is missing so we at least get a $ symbol on US names.
            native_ccy = str(
                pos.get("native_currency")
                or pos.get("currency")
                or "USD",
            ).upper()

            items = [
                _item(ticker, "#00bfff"),
                _item(f"{qty:.4f}", "#ffd700"),
                _item(_format_price(avg_px, native_ccy), "#ffd700"),
                _item(_format_price(cur_px, native_ccy), "#ffd700"),
                _item(f"{pnl:+.2f}", "#00ff00" if pnl >= 0 else "#ff0000"),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
