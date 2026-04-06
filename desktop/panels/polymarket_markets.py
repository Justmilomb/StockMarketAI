"""Polymarket markets panel — prediction market events table."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)

COLUMNS = ["Market", "YES", "NO", "Volume 24h", "Traders", "Signal"]

SIGNAL_COLORS = {
    "BUY": "#00ff00",
    "SELL": "#ff0000",
    "HOLD": "#ffd700",
}


class PolymarketPanel(QGroupBox):
    """Displays polymarket prediction markets with YES/NO prices."""

    def __init__(self, state: Any) -> None:
        super().__init__("POLYMARKET MARKETS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch,
        )
        for i in range(1, len(COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        self.refresh_view(state)

    def selected_market(self) -> str:
        """Return the market question text for the selected row."""
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return item.text() if item else ""

    def refresh_view(self, state: Any) -> None:
        """Update table from signals DataFrame (polymarket format)."""
        signals_df = state.signals
        if signals_df is None:
            self.table.setRowCount(0)
            return

        try:
            if hasattr(signals_df, "empty") and signals_df.empty:
                self.table.setRowCount(0)
                return
        except Exception:
            self.table.setRowCount(0)
            return

        self.table.setRowCount(len(signals_df))
        for r, (_, row_data) in enumerate(signals_df.iterrows()):
            question = str(row_data.get("ticker", ""))
            prob = float(row_data.get("prob_up", 0.5))
            signal = str(row_data.get("signal", "HOLD"))
            ai_rec = str(row_data.get("ai_rec", ""))

            yes_price = prob
            no_price = 1.0 - prob

            # Market question
            self.table.setItem(r, 0, _item(question, "#ffd700"))

            # YES price — green tint for high probability
            yes_color = "#00ff00" if yes_price > 0.6 else "#ffd700" if yes_price > 0.4 else "#ff0000"
            self.table.setItem(r, 1, _item(f"{yes_price:.1%}", yes_color))

            # NO price
            no_color = "#ff0000" if no_price > 0.6 else "#ffd700" if no_price > 0.4 else "#00ff00"
            self.table.setItem(r, 2, _item(f"{no_price:.1%}", no_color))

            # Volume (from ai_rec field which we formatted as "Vol: $X")
            self.table.setItem(r, 3, _item(ai_rec, "#888888"))

            # Traders (not available in basic fetch, placeholder)
            self.table.setItem(r, 4, _item("--", "#888888"))

            # Signal
            sig_color = SIGNAL_COLORS.get(signal, "#888888")
            self.table.setItem(r, 5, _item(signal, sig_color))


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
