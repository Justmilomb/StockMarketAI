"""Watchlist panel — live price + sentiment view.

Only the columns the agent-native pipeline actually populates remain:
ticker, live price, day change %, and aggregated news sentiment. The
legacy ML columns (Verdict, Signal, AI Rec, Consensus, Prob, Conf)
and the orphan Strategy column were removed — they were rendering
``--`` on every row once the scikit-learn ensemble and strategy
selector were retired in favour of the agent loop.
"""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

COLUMNS = ["Ticker", "Live Px", "Day %", "Sentiment"]


class WatchlistPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("WATCHLIST")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
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
        # Watchlist is owned by the agent loop now — we enumerate the
        # active watchlist directly rather than relying on the legacy
        # ``signals`` DataFrame which is no longer populated.
        config = getattr(state, "_config_snapshot", None)
        if config is None:
            # Derive the active watchlist from state fields populated
            # by app.py on each refresh.
            tickers = list(getattr(state, "active_watchlist_tickers", []) or [])
        else:
            tickers = list(config)

        self.table.setRowCount(len(tickers))
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
            ticker_color = "#00bfff" if held else "#ffd700"
            self.table.setItem(r, 0, _item(display_ticker, ticker_color))

            px_str = f"{float(price):.2f}" if price else "--"
            self.table.setItem(r, 1, _item(px_str, "#ffd700"))

            try:
                chg = float(change_pct) if change_pct else 0.0
            except (TypeError, ValueError):
                chg = 0.0
            chg_color = "#00ff00" if chg > 0 else "#ff0000" if chg < 0 else "#888888"
            self.table.setItem(r, 2, _item(f"{chg:+.1f}%", chg_color))

            s_color = "#00ff00" if sent_score > 0.1 else "#ff0000" if sent_score < -0.1 else "#888888"
            self.table.setItem(r, 3, _item(f"{sent_score:+.2f}" if sent_score else "--", s_color))

            if held:
                for col in range(len(COLUMNS)):
                    item = self.table.item(r, col)
                    if item:
                        item.setBackground(QColor("#111111"))


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
