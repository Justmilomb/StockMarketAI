"""Watchlist panel — main signal table with 11 columns."""
from __future__ import annotations
from typing import Any, Optional
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from intraday_data import is_intraday_supported

COLUMNS = ["Ticker", "Verdict", "Live Px", "Day %", "Prob", "Signal", "AI Rec", "Consensus", "Conf", "Sentiment", "Strategy"]

STRATEGY_COLORS = {
    "conservative": "#888888",
    "day_trader": "#00ff00",
    "swing": "#ffd700",
    "crisis_alpha": "#ff0000",
    "trend_follower": "#00bfff",
    "scalper": "#ff00ff",
    "intraday_momentum": "#ff8c00",
}

def compute_verdict(prob: float, consensus_pct: float) -> str:
    """Compute a verdict label from probability and consensus."""
    if prob >= 0.65 and consensus_pct >= 70:
        return "GREEN"
    elif prob <= 0.40 or consensus_pct <= 40:
        return "RED"
    elif prob >= 0.55 and consensus_pct >= 55:
        return "AMBER"
    return "NEUTRAL"

VERDICT_COLORS = {
    "GREEN": "#00ff00",
    "RED": "#ff0000",
    "AMBER": "#ffd700",
    "ORANGE": "#ff8c00",
    "NEUTRAL": "#888888",
}

SIGNAL_COLORS = {
    "BUY": "#00ff00",
    "SELL": "#ff0000",
    "HOLD": "#ffd700",
}

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
        return item.text().replace("[P] ", "")

    def refresh_view(self, state: Any) -> None:
        signals_df = state.signals
        if signals_df is None or signals_df.empty if hasattr(signals_df, 'empty') else signals_df is None:
            self.table.setRowCount(0)
            return

        rows = []
        for _, row_data in signals_df.iterrows():
            ticker = str(row_data.get("ticker", ""))
            prob = float(row_data.get("prob_up", 0.5))
            signal = str(row_data.get("signal", "HOLD"))
            ai_rec = str(row_data.get("ai_rec", ""))

            live = state.live_data.get(ticker, {})
            price = live.get("price", "")
            change_pct = live.get("change_pct", 0)

            consensus = state.consensus_data.get(ticker, {})
            cons_pct = consensus.get("consensus_pct", 50) if isinstance(consensus, dict) else 50
            conf = consensus.get("confidence", 0) if isinstance(consensus, dict) else 0

            news = state.news_sentiment.get(ticker, {})
            sent_score = news.get("sentiment_score", 0) if isinstance(news, dict) else 0

            # Verdict
            ai_grade = state.ai_color_grades.get(ticker) if hasattr(state, "ai_color_grades") else None
            verdict = ai_grade if ai_grade else compute_verdict(prob, cons_pct)

            # Strategy
            strat_data = state.strategy_assignments.get(ticker, {})
            strat_name = strat_data.get("name", "") if isinstance(strat_data, dict) else ""

            # Protected / daily-only tags
            is_protected = ticker in state.protected_tickers
            daily_only = not is_intraday_supported(ticker)
            prefix = ""
            if is_protected:
                prefix += "[P] "
            if daily_only:
                prefix += "[D] "
            display_ticker = f"{prefix}{ticker}" if prefix else ticker

            rows.append((
                display_ticker, verdict, price, change_pct, prob,
                signal, ai_rec, cons_pct, conf, sent_score, strat_name,
                is_protected, ticker,
            ))

        self.table.setRowCount(len(rows))
        for r, row_data in enumerate(rows):
            (display_ticker, verdict, price, change_pct, prob,
             signal, ai_rec, cons_pct, conf, sent_score, strat_name,
             is_protected, raw_ticker) = row_data

            held = any(
                p.get("ticker", "") == raw_ticker for p in (state.positions or [])
            )

            # Ticker
            ticker_color = "#00bfff" if held else "#ffd700"
            self.table.setItem(r, 0, _item(display_ticker, ticker_color))

            # Verdict
            v_color = VERDICT_COLORS.get(verdict, "#888888")
            self.table.setItem(r, 1, _item(verdict, v_color))

            # Live Price
            px_str = f"{float(price):.2f}" if price else "--"
            self.table.setItem(r, 2, _item(px_str, "#ffd700"))

            # Day %
            chg = float(change_pct) if change_pct else 0
            chg_color = "#00ff00" if chg > 0 else "#ff0000" if chg < 0 else "#888888"
            self.table.setItem(r, 3, _item(f"{chg:+.1f}%", chg_color))

            # Prob
            self.table.setItem(r, 4, _item(f"{prob:.2f}", "#ffd700"))

            # Signal
            sig_color = SIGNAL_COLORS.get(signal, "#888888")
            self.table.setItem(r, 5, _item(signal, sig_color))

            # AI Rec
            self.table.setItem(r, 6, _item(ai_rec, "#ffb000"))

            # Consensus %
            self.table.setItem(r, 7, _item(f"{cons_pct:.0f}%", "#ffd700"))

            # Confidence
            self.table.setItem(r, 8, _item(f"{conf:.2f}" if conf else "--", "#888888"))

            # Sentiment
            s_color = "#00ff00" if sent_score > 0.1 else "#ff0000" if sent_score < -0.1 else "#888888"
            self.table.setItem(r, 9, _item(f"{sent_score:+.2f}" if sent_score else "--", s_color))

            # Strategy
            st_color = STRATEGY_COLORS.get(strat_name, "#888888")
            self.table.setItem(r, 10, _item(strat_name or "-", st_color))

            # Held row highlight
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
