"""Pies dialog — investment pies with drill-down."""
from __future__ import annotations

from typing import List

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


def _table_qss() -> str:
    return (
        f"QTableWidget {{ background: transparent; border: none;"
        f" color: {T.FG_0}; font-family: {T.FONT_SANS}; font-size: 12px; }}"
        f"QHeaderView::section {{ background: transparent; border: none;"
        f" border-bottom: 1px solid {T.BORDER_0};"
        f" color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding: 6px 8px; }}"
        f"QTableWidget::item {{ padding: 6px 8px; }}"
        f"QTableWidget::item:selected {{ background: {T.ACCENT_DIM};"
        f" color: {T.FG_0}; }}"
    )


class PiesDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            kicker="ALLOCATION",
            title="Investment pies",
            parent=parent,
        )
        self.setMinimumSize(760, 560)

        body = self.body_layout()

        self._pies_table = QTableWidget(0, 6)
        self._pies_table.setHorizontalHeaderLabels(
            ["NAME", "INVESTED", "VALUE", "RETURN", "CASH", "STATUS"]
        )
        self._pies_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pies_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pies_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pies_table.verticalHeader().setVisible(False)
        self._pies_table.setShowGrid(False)
        self._pies_table.setStyleSheet(_table_qss())
        body.addWidget(self._pies_table, 2)

        self._detail_label = QLabel("Select a pie and click VIEW DETAIL.")
        self._detail_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px; padding-top: 6px;"
        )
        body.addWidget(self._detail_label)

        self._instruments_table = QTableWidget(0, 5)
        self._instruments_table.setHorizontalHeaderLabels(
            ["TICKER", "TARGET", "CURRENT", "QTY", "VALUE"]
        )
        self._instruments_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._instruments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._instruments_table.verticalHeader().setVisible(False)
        self._instruments_table.setShowGrid(False)
        self._instruments_table.setStyleSheet(_table_qss())
        self._instruments_table.setMaximumHeight(180)
        body.addWidget(self._instruments_table, 1)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.accept)
        self.add_footer_button("REFRESH", variant="ghost")
        self.add_footer_button("VIEW DETAIL", variant="primary", slot=self._view_detail)

        self._pies_data: List[dict] = []

    def populate_pies(self, pies: List[dict]) -> None:
        self._pies_data = pies
        self._pies_table.setRowCount(len(pies))
        for row, p in enumerate(pies):
            vals = [
                p.get("name", ""),
                f"{p.get('invested', 0):.2f}",
                f"{p.get('value', 0):.2f}",
                f"{p.get('return_pct', 0):+.2f}%",
                f"{p.get('cash', 0):.2f}",
                p.get("status", ""),
            ]
            ret = p.get("return_pct", 0)
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if col == 3:
                    color = T.ACCENT_HEX if ret > 0 else T.ALERT if ret < 0 else T.FG_1_HEX
                elif col == 0:
                    color = T.FG_0
                else:
                    color = T.FG_1_HEX
                item.setForeground(QColor(color))
                self._pies_table.setItem(row, col, item)

    def populate_instruments(self, instruments: List[dict]) -> None:
        self._instruments_table.setRowCount(len(instruments))
        for row, inst in enumerate(instruments):
            vals = [
                inst.get("ticker", ""),
                f"{inst.get('target_pct', 0):.1f}%",
                f"{inst.get('current_pct', 0):.1f}%",
                str(inst.get("quantity", "")),
                f"{inst.get('value', 0):.2f}",
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                color = T.ACCENT_HEX if col == 0 else T.FG_1_HEX
                item.setForeground(QColor(color))
                self._instruments_table.setItem(row, col, item)

    def _view_detail(self) -> None:
        row = self._pies_table.currentRow()
        if row >= 0 and row < len(self._pies_data):
            pie = self._pies_data[row]
            self._detail_label.setText(f"PIE \u2014 {pie.get('name', '')}".upper())
            self._detail_label.setStyleSheet(
                f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
                f" font-size: 10px; letter-spacing: 2px; padding-top: 6px;"
            )
