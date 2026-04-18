"""Positions panel — holdings table.

Shows ticker, quantity, average entry price, current price, and
unrealised P/L. Colouring follows the new palette: white for neutral
numbers, green for positive PnL, red for negative.
"""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from desktop import tokens as T

COLUMNS = ["Ticker", "Qty", "Avg Px", "Cur Px", "PnL"]

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
        layout.setContentsMargins(2, 18, 2, 2)
        layout.setSpacing(0)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c.upper() for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
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

            native_ccy = str(
                pos.get("native_currency")
                or pos.get("currency")
                or "USD",
            ).upper()

            pnl_color = T.ACCENT_HEX if pnl > 0 else T.ALERT if pnl < 0 else T.FG_2_HEX
            pnl_sign = "+" if pnl >= 0 else ""

            items = [
                _item(ticker, T.FG_0, bold=True),
                _item(f"{qty:.4f}", T.FG_0, align=Qt.AlignRight),
                _item(_format_price(avg_px, native_ccy), T.FG_1_HEX, align=Qt.AlignRight),
                _item(_format_price(cur_px, native_ccy), T.FG_0, align=Qt.AlignRight),
                _item(f"{pnl_sign}{pnl:.2f}", pnl_color, align=Qt.AlignRight, bold=True),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


def _item(
    text: str,
    color: str,
    *,
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter,
    bold: bool = False,
) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(align | Qt.AlignVCenter)
    font = QFont(T.FONT_MONO_FAMILY)
    font.setStyleHint(QFont.Monospace)
    font.setWeight(QFont.Medium if bold else QFont.Normal)
    item.setFont(font)
    return item
