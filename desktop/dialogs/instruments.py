"""Instruments browser dialog — search and add instruments."""
from __future__ import annotations

from typing import List

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


_TABLE_QSS = (
    "QTableWidget {{ background: transparent; border: none;"
    " color: {fg}; font-family: {sans}; font-size: 12px; }}"
    "QHeaderView::section {{ background: transparent; border: none;"
    " border-bottom: 1px solid {border};"
    " color: {fg_dim}; font-family: {mono};"
    " font-size: 10px; letter-spacing: 2px; padding: 6px 8px; }}"
    "QTableWidget::item {{ padding: 6px 8px; }}"
    "QTableWidget::item:selected {{ background: {accent_dim};"
    " color: {fg}; }}"
)


def _table_qss() -> str:
    return _TABLE_QSS.format(
        fg=T.FG_0,
        sans=T.FONT_SANS,
        border=T.BORDER_0,
        fg_dim=T.FG_2_HEX,
        mono=T.FONT_MONO,
        accent_dim=T.ACCENT_DIM,
    )


class InstrumentsDialog(BaseDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(
            kicker="DIRECTORY",
            title="Instrument browser",
            parent=parent,
        )
        self.setMinimumSize(760, 560)
        self.selected_ticker: str = ""

        body = self.body_layout()

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by ticker or name\u2026")
        self._filter.textChanged.connect(self._on_filter)
        self._filter.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" border-bottom: 1px solid {T.BORDER_1};"
            f" color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 14px; padding: 6px 0; letter-spacing: 0.5px; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {T.ACCENT_HEX}; }}"
        )
        body.addWidget(self._filter)

        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        body.addWidget(self._status)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["TICKER", "NAME", "EXCHANGE", "TYPE", "CURRENCY", "MIN QTY"]
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(_table_qss())
        body.addWidget(self._table, 1)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.reject)
        self.add_footer_button("ADD TO WATCHLIST", variant="primary", slot=self._add_selected)

        self._all_instruments: List[dict] = []

    def populate(self, instruments: List[dict]) -> None:
        self._all_instruments = instruments
        self._show_instruments(instruments[:100])
        self._status.setText(f"{len(instruments)} INSTRUMENTS LOADED")

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
                color = T.ACCENT_HEX if col == 0 else T.FG_1_HEX
                item.setForeground(QColor(color))
                self._table.setItem(row, col, item)

    def _on_filter(self, text: str) -> None:
        if not text:
            self._show_instruments(self._all_instruments[:100])
            self._status.setText(f"{len(self._all_instruments)} INSTRUMENTS LOADED")
            return
        text_lower = text.lower()
        filtered = [
            i for i in self._all_instruments
            if text_lower in i.get("ticker", i.get("shortName", "")).lower()
            or text_lower in i.get("name", i.get("longName", "")).lower()
        ][:100]
        self._show_instruments(filtered)
        self._status.setText(
            f"SHOWING {len(filtered)} OF {len(self._all_instruments)}"
        )

    def _add_selected(self) -> None:
        row = self._table.currentRow()
        if row >= 0:
            item = self._table.item(row, 0)
            if item:
                self.selected_ticker = item.text()
                self.accept()
