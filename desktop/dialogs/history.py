"""History dialog — 3-tab view of orders, dividends, transactions."""
from __future__ import annotations

from typing import Any, List

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
)

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


def _table_qss() -> str:
    return (
        f"QTableWidget {{ background: transparent; border: none;"
        f" color: {T.FG_0}; font-family: {T.FONT_SANS}; font-size: 12px; }}"
        f"QHeaderView::section {{ background: transparent; border: none;"
        f" border-bottom: 1px solid {T.BORDER_0};"
        f" color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding: 6px 8px; }}"
        f"QTableWidget::item {{ padding: 6px 8px; }}"
        f"QTableWidget::item:selected {{ background: {T.ACCENT_DIM};"
        f" color: {T.FG_0}; }}"
    )


def _tabs_qss() -> str:
    return (
        f"QTabWidget::pane {{ background: transparent; border: none;"
        f" border-top: 1px solid {T.BORDER_0}; }}"
        f"QTabBar::tab {{ background: transparent; border: none;"
        f" color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px;"
        f" padding: 8px 18px 8px 0; margin: 0 18px 0 0; }}"
        f"QTabBar::tab:selected {{ color: {T.FG_0};"
        f" border-bottom: 1px solid {T.ACCENT_HEX}; }}"
        f"QTabBar::tab:hover {{ color: {T.FG_0}; }}"
    )


class HistoryDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            kicker="LEDGER",
            title="Account history",
            parent=parent,
        )
        self.setMinimumSize(780, 560)

        body = self.body_layout()

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(_tabs_qss())
        self._tabs.setDocumentMode(True)
        body.addWidget(self._tabs, 1)

        self._orders_table = self._make_table(
            ["DATE", "TICKER", "SIDE", "QTY", "FILL PX", "COST", "STATUS"]
        )
        self._tabs.addTab(self._orders_table, "Orders")

        self._dividends_table = self._make_table(
            ["DATE", "TICKER", "AMOUNT", "QTY", "PER SHARE"]
        )
        self._tabs.addTab(self._dividends_table, "Dividends")

        self._transactions_table = self._make_table(
            ["DATE", "TYPE", "AMOUNT", "CURRENCY", "STATUS"]
        )
        self._tabs.addTab(self._transactions_table, "Transactions")

        self._refresh_callback: Any = None

        self.add_footer_button("CLOSE", variant="ghost", slot=self.accept)
        self.add_footer_button("REFRESH", variant="primary", slot=self._on_refresh)

    def _make_table(self, headers: List[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setStyleSheet(_table_qss())
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
            side = o.get("side", "").upper()
            side_color = T.ACCENT_HEX if "BUY" in side else T.ALERT
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if col == 2:
                    color = side_color
                elif col == 1:
                    color = T.FG_0
                else:
                    color = T.FG_1_HEX
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
                color = T.ACCENT_HEX if col == 1 else T.FG_1_HEX
                item.setForeground(QColor(color))
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
                color = T.FG_0 if col == 1 else T.FG_1_HEX
                item.setForeground(QColor(color))
                self._transactions_table.setItem(row, col, item)
