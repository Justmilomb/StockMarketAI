"""Orders panel — full recent-order history table.

Shows pending + filled + cancelled + rejected orders. Colour is reduced
to the new palette: green for BUY / FILLED, red for SELL / REJECTED,
amber for PENDING, dim white for neutral metadata.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from desktop import tokens as T

_MAX_ROWS: int = 200

COLUMNS = ["Time", "Ticker", "Side", "Qty", "Type", "Status"]


class OrdersPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("ORDERS")
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
        raw = state.recent_orders or []
        orders = [
            o for o in raw
            if isinstance(o, dict)
            and str(o.get("ticker", "")).strip()
            and str(o.get("side", "")).strip().upper() in ("BUY", "SELL")
        ][:_MAX_ROWS]
        self.table.setRowCount(len(orders))
        for row, order in enumerate(orders):
            side = order.get("side", "").upper()
            side_color = T.ACCENT_HEX if side == "BUY" else T.ALERT
            status = order.get("status", "")
            status_upper = status.upper()
            if status_upper == "FILLED":
                status_color = T.ACCENT_HEX
            elif status_upper in ("CANCELLED", "REJECTED", "FAILED"):
                status_color = T.ALERT
            elif status_upper in ("PENDING", "NEW", "WORKING", "ACCEPTED", "QUEUED"):
                status_color = T.WARN
            else:
                status_color = T.FG_2_HEX
            order_type = order.get("order_type", order.get("type", ""))
            time_str = _format_time(order)
            items = [
                _item(time_str, T.FG_2_HEX),
                _item(order.get("ticker", ""), T.FG_0, bold=True),
                _item(side, side_color, bold=True),
                _item(str(order.get("quantity", "")), T.FG_1_HEX, align=Qt.AlignRight),
                _item(str(order_type).upper(), T.FG_1_HEX),
                _item(status.upper(), status_color, bold=True),
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
    return "—"


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
