"""Orders panel — full recent-order history table.

Shows pending + filled + cancelled + rejected orders (merged upstream in
``app.py`` from ``get_pending_orders`` + ``get_order_history(limit=200)``).
Colour-coded by status so the user can glance at whether the agent is
actually executing or the broker is silently rejecting trades.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

#: Upper bound for panel rows. Matches the history fetch in app.py.
_MAX_ROWS: int = 200

COLUMNS = ["Time", "Ticker", "Side", "Qty", "Type", "Status"]


class OrdersPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("ORDERS")
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
        orders = (state.recent_orders or [])[:_MAX_ROWS]
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            side = order.get("side", "")
            side_color = "#00ff00" if side.upper() == "BUY" else "#ff0000"
            status = order.get("status", "")
            status_upper = status.upper()
            if status_upper == "FILLED":
                status_color = "#00ff00"
            elif status_upper in ("CANCELLED", "REJECTED", "FAILED"):
                status_color = "#ff0000"
            elif status_upper in ("PENDING", "NEW", "WORKING", "ACCEPTED"):
                status_color = "#ffd700"
            else:
                status_color = "#aaaaaa"
            order_type = order.get("order_type", order.get("type", ""))
            time_str = _format_time(order)
            items = [
                _item(time_str, "#aaaaaa"),
                _item(order.get("ticker", ""), "#00bfff"),
                _item(side, side_color),
                _item(str(order.get("quantity", "")), "#ffd700"),
                _item(order_type, "#ffd700"),
                _item(status, status_color),
            ]
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)


def _format_time(order: dict) -> str:
    """Pull the most-specific timestamp available and format as HH:MM."""
    for key in ("fill_time", "executed_at", "filled_at", "time", "ts",
                "timestamp", "created_at", "creationDate"):
        raw = order.get(key)
        if not raw:
            continue
        try:
            if isinstance(raw, (int, float)):
                dt = datetime.fromtimestamp(raw if raw < 1e12 else raw / 1000)
            else:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except (ValueError, OSError, TypeError):
            continue
    return "--"


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
