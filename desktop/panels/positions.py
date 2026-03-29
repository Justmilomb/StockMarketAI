"""Positions panel — holdings table."""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

class PositionsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("POSITIONS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Ticker", "Qty", "Avg Px", "Cur Px", "PnL"])
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
            avg_px = float(pos.get("averagePrice", pos.get("avg_price", 0)))
            live = state.live_data.get(ticker, {})
            cur_px = float(live.get("price", avg_px))
            pnl = (cur_px - avg_px) * qty

            items = [
                _item(ticker, "#00bfff"),
                _item(f"{qty:.4f}", "#ffd700"),
                _item(f"{avg_px:.2f}", "#ffd700"),
                _item(f"{cur_px:.2f}", "#ffd700"),
                _item(f"{pnl:+.2f}", "#00ff00" if pnl >= 0 else "#ff0000"),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
