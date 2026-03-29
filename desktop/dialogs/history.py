"""History dialog — 3-tab view of orders, dividends, transactions."""
from __future__ import annotations
from typing import Any, List
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
)

class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Account History")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, 1)

        # Orders tab
        self._orders_table = self._make_table(
            ["Date", "Ticker", "Side", "Qty", "Fill Px", "Cost", "Status"]
        )
        self._tabs.addTab(self._orders_table, "Orders")

        # Dividends tab
        self._dividends_table = self._make_table(
            ["Date", "Ticker", "Amount", "Qty", "Per Share"]
        )
        self._tabs.addTab(self._dividends_table, "Dividends")

        # Transactions tab
        self._transactions_table = self._make_table(
            ["Date", "Type", "Amount", "Currency", "Status"]
        )
        self._tabs.addTab(self._transactions_table, "Transactions")

        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._on_refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh_callback = None

    def _make_table(self, headers: List[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        return table

    def set_refresh_callback(self, fn: Any) -> None:
        self._refresh_callback = fn

    def _on_refresh(self) -> None:
        if self._refresh_callback:
            self._refresh_callback()

    def populate_orders(self, orders: List[dict]) -> None:
        self._orders_table.setRowCount(len(orders))
        for row, o in enumerate(orders):
            vals = [
                o.get("date", ""),
                o.get("ticker", ""),
                o.get("side", ""),
                str(o.get("quantity", "")),
                str(o.get("fill_price", o.get("fillPrice", ""))),
                str(o.get("cost", "")),
                o.get("status", ""),
            ]
            side = o.get("side", "")
            side_color = "#00ff00" if "BUY" in side.upper() else "#ff0000"
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                color = side_color if col == 2 else "#ffd700"
                item.setForeground(QColor(color))
                self._orders_table.setItem(row, col, item)

    def populate_dividends(self, dividends: List[dict]) -> None:
        self._dividends_table.setRowCount(len(dividends))
        for row, d in enumerate(dividends):
            vals = [
                d.get("date", ""),
                d.get("ticker", ""),
                str(d.get("amount", "")),
                str(d.get("quantity", "")),
                str(d.get("per_share", d.get("amountPerShare", ""))),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setForeground(QColor("#ffd700"))
                self._dividends_table.setItem(row, col, item)

    def populate_transactions(self, transactions: List[dict]) -> None:
        self._transactions_table.setRowCount(len(transactions))
        for row, t in enumerate(transactions):
            vals = [
                t.get("date", ""),
                t.get("type", ""),
                str(t.get("amount", "")),
                t.get("currency", ""),
                t.get("status", ""),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setForeground(QColor("#ffd700"))
                self._transactions_table.setItem(row, col, item)
