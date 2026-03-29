"""Instruments browser dialog — search and add instruments."""
from __future__ import annotations
from typing import List
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

class InstrumentsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Instrument Browser")
        self.setMinimumSize(700, 500)
        self.selected_ticker: str = ""

        layout = QVBoxLayout(self)

        title = QLabel("INSTRUMENT BROWSER")
        title.setStyleSheet("color: #ffb000; font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by ticker or name...")
        self._filter.textChanged.connect(self._on_filter)
        layout.addWidget(self._filter)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Ticker", "Name", "Exchange", "Type", "Currency", "Min Qty"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add to Watchlist")
        add_btn.clicked.connect(self._add_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(add_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._all_instruments: List[dict] = []

    def populate(self, instruments: List[dict]) -> None:
        self._all_instruments = instruments
        self._show_instruments(instruments[:100])
        self._status.setText(f"{len(instruments)} instruments loaded")

    def _show_instruments(self, instruments: List[dict]) -> None:
        self._table.setRowCount(len(instruments))
        for row, inst in enumerate(instruments):
            vals = [
                inst.get("ticker", inst.get("shortName", "")),
                inst.get("name", inst.get("longName", "")),
                inst.get("exchange", ""),
                inst.get("type", inst.get("instrumentType", "")),
                inst.get("currency", inst.get("currencyCode", "")),
                str(inst.get("minTradeQuantity", inst.get("min_qty", ""))),
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setForeground(QColor("#00bfff" if col == 0 else "#ffd700"))
                self._table.setItem(row, col, item)

    def _on_filter(self, text: str) -> None:
        if not text:
            self._show_instruments(self._all_instruments[:100])
            return
        text_lower = text.lower()
        filtered = [
            i for i in self._all_instruments
            if text_lower in i.get("ticker", i.get("shortName", "")).lower()
            or text_lower in i.get("name", i.get("longName", "")).lower()
        ][:100]
        self._show_instruments(filtered)
        self._status.setText(f"Showing {len(filtered)} of {len(self._all_instruments)}")

    def _add_selected(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self.selected_ticker = item.text()
                self.accept()
