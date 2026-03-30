"""Search ticker dialog — AI-powered ticker search."""
from __future__ import annotations
from typing import Any, List
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

class SearchTickerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Tickers")
        self.setMinimumSize(500, 400)
        self.selected_ticker: str = ""

        layout = QVBoxLayout(self)

        title = QLabel("SEARCH TICKERS")
        title.setStyleSheet("color: #ffb000; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel("Enter a search term (company name, sector, etc.)")
        hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search...")
        self._input.returnPressed.connect(self._search)
        layout.addWidget(self._input)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Ticker", "Reason"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add Selected")
        add_btn.clicked.connect(self._add_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(add_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def set_search_callback(self, fn: Any) -> None:
        """Set callback for background AI search requests."""
        self._search_callback = fn

    def _search(self) -> None:
        query = self._input.text().strip()
        if not query:
            return
        if hasattr(self, '_search_callback') and self._search_callback:
            self._status.setText("Searching...")
            self._status.setStyleSheet("color: #ffb000; font-size: 11px;")
            self._search_callback(query)
        else:
            self._status.setText("AI search not connected")
            self._status.setStyleSheet("color: #ff0000; font-size: 11px;")

    def populate_results(self, results: List[dict]) -> None:
        """Called by the main window after a background search completes."""
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            ticker = r.get("symbol", r.get("ticker", ""))
            reason = r.get("reason", "")
            t_item = QTableWidgetItem(ticker)
            t_item.setForeground(QColor("#00bfff"))
            r_item = QTableWidgetItem(reason)
            r_item.setForeground(QColor("#ffd700"))
            self._table.setItem(row, 0, t_item)
            self._table.setItem(row, 1, r_item)
        self._status.setText(f"Found {len(results)} results")
        self._status.setStyleSheet("color: #00ff00; font-size: 11px;")

    def _add_selected(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self.selected_ticker = item.text()
                self.accept()
