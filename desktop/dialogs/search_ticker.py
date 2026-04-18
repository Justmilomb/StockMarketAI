"""Search ticker dialog — AI-powered ticker search."""
from __future__ import annotations

from typing import Any, List

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
)

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


class SearchTickerDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            kicker="DISCOVERY",
            title="Search tickers",
            parent=parent,
        )
        self.setMinimumSize(560, 520)
        self.selected_ticker: str = ""
        self._search_callback: Any = None

        body = self.body_layout()

        hint = QLabel(
            "Describe what you are looking for \u2014 a company, a sector,"
            " a theme. The agent suggests matching tickers."
        )
        hint.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px;"
        )
        hint.setWordWrap(True)
        body.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("dividend aristocrats, AI infrastructure, UK small caps\u2026")
        self._input.returnPressed.connect(self._search)
        self._input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {T.BORDER_1};"
            f" color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 14px; padding: 6px 0; letter-spacing: 0.5px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {T.ACCENT_HEX}; }}"
        )
        body.addWidget(self._input)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        body.addWidget(self._status)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["TICKER", "REASON"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(
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
        body.addWidget(self._table, 1)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.reject)
        self.add_footer_button("ADD SELECTED", variant="primary", slot=self._add_selected)

    def set_search_callback(self, fn: Any) -> None:
        self._search_callback = fn

    def _search(self) -> None:
        query = self._input.text().strip()
        if not query:
            return
        if self._search_callback:
            self._status.setText("SEARCHING\u2026")
            self._status.setStyleSheet(
                f"color: {T.WARN}; font-family: {T.FONT_MONO};"
                f" font-size: 10px; letter-spacing: 2px;"
            )
            self._search_callback(query)
        else:
            self._status.setText("AGENT OFFLINE")
            self._status.setStyleSheet(
                f"color: {T.ALERT}; font-family: {T.FONT_MONO};"
                f" font-size: 10px; letter-spacing: 2px;"
            )

    def populate_results(self, results: List[dict]) -> None:
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            ticker = r.get("symbol", r.get("ticker", ""))
            reason = r.get("reason", "")
            t_item = QTableWidgetItem(ticker)
            t_item.setForeground(QColor(T.ACCENT_HEX))
            r_item = QTableWidgetItem(reason)
            r_item.setForeground(QColor(T.FG_1_HEX))
            self._table.setItem(row, 0, t_item)
            self._table.setItem(row, 1, r_item)
        self._status.setText(f"{len(results)} MATCHES")
        self._status.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )

    def _add_selected(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self.selected_ticker = item.text()
                self.accept()
