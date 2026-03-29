"""Orders panel — recent orders table."""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

class OrdersPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("ORDERS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Ticker", "Side", "Qty", "Type", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        orders = (state.recent_orders or [])[:20]
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            side = order.get("side", "")
            side_color = "#00ff00" if side.upper() == "BUY" else "#ff0000"
            items = [
                _item(order.get("ticker", ""), "#00bfff"),
                _item(side, side_color),
                _item(str(order.get("quantity", "")), "#ffd700"),
                _item(order.get("type", ""), "#ffd700"),
                _item(order.get("status", ""), "#888888"),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
