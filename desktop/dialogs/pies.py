"""Pies dialog — investment pies with drill-down."""
from __future__ import annotations
from typing import List
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

class PiesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Investment Pies")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)

        title = QLabel("INVESTMENT PIES")
        title.setStyleSheet("color: #ffb000; font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self._pies_table = QTableWidget(0, 6)
        self._pies_table.setHorizontalHeaderLabels(
            ["Name", "Invested", "Value", "Return %", "Cash", "Status"]
        )
        self._pies_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._pies_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._pies_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pies_table.verticalHeader().setVisible(False)
        layout.addWidget(self._pies_table, 1)

        self._detail_label = QLabel("Select a pie and click View Detail")
        self._detail_label.setStyleSheet("color: #888888;")
        layout.addWidget(self._detail_label)

        self._instruments_table = QTableWidget(0, 5)
        self._instruments_table.setHorizontalHeaderLabels(
            ["Ticker", "Target %", "Current %", "Qty", "Value"]
        )
        self._instruments_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._instruments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._instruments_table.verticalHeader().setVisible(False)
        self._instruments_table.setMaximumHeight(150)
        layout.addWidget(self._instruments_table)

        buttons = QHBoxLayout()
        detail_btn = QPushButton("View Detail")
        detail_btn.clicked.connect(self._view_detail)
        refresh_btn = QPushButton("Refresh")
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(detail_btn)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._pies_data: List[dict] = []

    def populate_pies(self, pies: List[dict]) -> None:
        self._pies_data = pies
        self._pies_table.setRowCount(len(pies))
        for row, p in enumerate(pies):
            vals = [
                p.get("name", ""),
                f"{p.get('invested', 0):.2f}",
                f"{p.get('value', 0):.2f}",
                f"{p.get('return_pct', 0):.1f}%",
                f"{p.get('cash', 0):.2f}",
                p.get("status", ""),
            ]
            ret = p.get("return_pct", 0)
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                color = "#00ff00" if col == 3 and ret > 0 else "#ff0000" if col == 3 and ret < 0 else "#ffd700"
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
                item.setForeground(QColor("#00bfff" if col == 0 else "#ffd700"))
                self._instruments_table.setItem(row, col, item)

    def _view_detail(self) -> None:
        row = self._pies_table.currentRow()
        if row >= 0 and row < len(self._pies_data):
            pie = self._pies_data[row]
            self._detail_label.setText(f"Pie: {pie.get('name', '')}")
            self._detail_label.setStyleSheet("color: #ffb000; font-weight: bold;")
