"""Watchlist panel — live price + sentiment view.

Columns: ticker, live price, day change %, sentiment (signed score).
Colouring maps onto the website palette — green for positive, red for
negative, dim grey for neutral. No gold / amber / cyan anywhere.
"""
from __future__ import annotations
from typing import Any, Dict, Tuple
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from desktop import tokens as T

COLUMNS = ["Ticker", "Live Px", "Day %", "Sentiment"]

# Cache key: (display_ticker, px_str, chg_str, sent_str, held)
_CacheKey = Tuple[str, str, str, str, bool]


class WatchlistPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("WATCHLIST")
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
        # Per-row cache: only rebuild cells when values actually change.
        self._row_cache: Dict[int, _CacheKey] = {}
        self.refresh_view(state)

    def selected_ticker(self) -> str:
        """Return the ticker string for the currently selected row."""
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        if not item:
            return ""
        import re
        return re.sub(r'\[[A-Z]\]', '', item.text()).strip()

    def refresh_view(self, state: Any) -> None:
        tickers = list(getattr(state, "active_watchlist_tickers", []) or [])
        n = len(tickers)

        # If row count changed, full teardown and cache invalidation.
        if self.table.rowCount() != n:
            self.table.setRowCount(n)
            self._row_cache.clear()

        self.table.setUpdatesEnabled(False)
        try:
            for r, ticker in enumerate(tickers):
                live = state.live_data.get(ticker, {})
                price = live.get("price", "")
                change_pct = live.get("change_pct", 0)

                news = state.news_sentiment.get(ticker, {})
                sent_score = news.get("sentiment_score", 0) if isinstance(news, dict) else 0

                is_protected = ticker in state.protected_tickers
                held = any(
                    p.get("ticker", "") == ticker for p in (state.positions or [])
                )

                prefix = "[L]" if is_protected else ""
                display_ticker = f"{prefix} {ticker}" if prefix else ticker
                px_str = f"{float(price):.2f}" if price else "—"
                try:
                    chg = float(change_pct) if change_pct else 0.0
                except (TypeError, ValueError):
                    chg = 0.0
                chg_str = f"{chg:+.2f}%"
                s_text = f"{sent_score:+.2f}" if sent_score else "—"

                cache_key: _CacheKey = (display_ticker, px_str, chg_str, s_text, held)
                if self._row_cache.get(r) == cache_key:
                    continue  # nothing changed — skip expensive item creation
                self._row_cache[r] = cache_key

                chg_color = _price_color(chg)
                s_color = _price_color(sent_score, threshold=0.05)

                self.table.setItem(r, 0, _item(display_ticker, T.FG_0, bold=True))
                self.table.setItem(r, 1, _item(px_str, T.FG_0, align=Qt.AlignRight))
                self.table.setItem(r, 2, _item(chg_str, chg_color, align=Qt.AlignRight))
                self.table.setItem(r, 3, _item(s_text, s_color, align=Qt.AlignRight))

                if held:
                    wash = QColor(0, 255, 135, int(255 * 0.04))
                    for col in range(len(COLUMNS)):
                        it = self.table.item(r, col)
                        if it:
                            it.setBackground(wash)
        finally:
            self.table.setUpdatesEnabled(True)


def _price_color(value: float, threshold: float = 0.0) -> str:
    if value > threshold:
        return T.ACCENT_HEX
    if value < -threshold:
        return T.ALERT
    return T.FG_2_HEX


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
    font.setPixelSize(14)
    font.setWeight(QFont.Medium if bold else QFont.Normal)
    item.setFont(font)
    return item
