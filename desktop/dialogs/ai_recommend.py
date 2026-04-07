"""AI recommend dialog — get AI stock recommendations."""
from __future__ import annotations
from typing import Any, List
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class AiRecommendDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Recommendations")
        self.setMinimumSize(500, 400)
        self.selected_tickers: List[str] = []
        self._loading = False
        self._dots = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._animate_dots)

        layout = QVBoxLayout(self)

        title = QLabel("AI RECOMMENDATIONS")
        title.setStyleSheet("color: #ffb000; font-weight: bold;")
        layout.addWidget(title)

        cat_row = QHBoxLayout()
        self._category = QLineEdit()
        self._category.setPlaceholderText("Category (e.g. tech, dividend, volatile)")
        cat_row.addWidget(self._category, 1)
        self._get_btn = QPushButton("Get Recommendations")
        self._get_btn.clicked.connect(self._get_recs)
        cat_row.addWidget(self._get_btn)
        layout.addLayout(cat_row)

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
        add_sel = QPushButton("Add Selected")
        add_sel.clicked.connect(self._add_selected)
        add_all = QPushButton("Add All")
        add_all.clicked.connect(self._add_all)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(add_sel)
        buttons.addWidget(add_all)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def set_request_callback(self, fn: Any) -> None:
        """Set callback for background AI recommendation requests."""
        self._request_callback = fn

    def _get_recs(self) -> None:
        if self._loading:
            return
        category = self._category.text().strip()
        if hasattr(self, '_request_callback') and self._request_callback:
            self._set_loading(True)
            self._request_callback(category)
        else:
            self._status.setText("AI not connected")
            self._status.setStyleSheet("color: #ff0000; font-size: 11px;")

    def _set_loading(self, loading: bool) -> None:
        self._loading = loading
        self._get_btn.setEnabled(not loading)
        if loading:
            self._dots = 0
            self._get_btn.setText("AI Thinking...")
            self._get_btn.setStyleSheet(
                "QPushButton { color: #555555; }"
            )
            self._status.setText("AI is analysing markets")
            self._status.setStyleSheet("color: #ffb000; font-size: 11px;")
            self._dot_timer.start(400)
        else:
            self._dot_timer.stop()
            self._get_btn.setText("Get Recommendations")
            self._get_btn.setStyleSheet("")

    def _animate_dots(self) -> None:
        self._dots = (self._dots % 3) + 1
        dots = "." * self._dots
        self._status.setText(f"AI is analysing markets{dots}")

    def populate_results(self, results: List[dict]) -> None:
        self._set_loading(False)
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
        if results:
            self._status.setText(f"Got {len(results)} recommendations")
            self._status.setStyleSheet("color: #00ff00; font-size: 11px;")
        else:
            self._status.setText("No recommendations returned")
            self._status.setStyleSheet("color: #ff0000; font-size: 11px;")

    def _add_selected(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self.selected_tickers = [item.text()]
                self.accept()

    def _add_all(self) -> None:
        tickers = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item:
                tickers.append(item.text())
        if tickers:
            self.selected_tickers = tickers
            self.accept()
