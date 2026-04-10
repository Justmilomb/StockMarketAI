"""Positions panel — holdings table with position notes (patient chart)."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

COLUMNS = ["Ticker", "Qty", "Avg Px", "Cur Px", "PnL", "Strategy", "Regime", "Held", "Intent"]

STRATEGY_COLORS = {
    "conservative": "#888888",
    "day_trader": "#00ff00",
    "swing": "#ffd700",
    "crisis_alpha": "#ff0000",
    "trend_follower": "#00bfff",
    "scalper": "#ff00ff",
    "intraday_momentum": "#ff8c00",
}


class PositionsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("POSITIONS")
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

    def refresh_view(self, state: Any) -> None:
        positions = state.positions or []
        notes = getattr(state, "position_notes", {})
        self.table.setRowCount(len(positions))
        for row, pos in enumerate(positions):
            ticker = pos.get("ticker", "")
            qty = float(pos.get("quantity", 0))
            avg_px = float(pos.get("avg_price", pos.get("averagePrice", 0)))
            cur_px = float(pos.get("current_price", avg_px))
            pnl_val = pos.get("unrealised_pnl") or pos.get("ppl") or 0.0
            try:
                pnl = float(pnl_val)
            except (TypeError, ValueError):
                pnl = 0.0

            # Position notes (patient chart)
            note = notes.get(ticker, {})
            strategy = note.get("strategy_profile", "--")
            regime = note.get("regime_at_entry", "--")
            intended = note.get("intended_hold", "--")
            held = _days_held(note.get("opened_at", ""))

            strat_color = STRATEGY_COLORS.get(strategy, "#888888")

            items = [
                _item(ticker, "#00bfff"),
                _item(f"{qty:.4f}", "#ffd700"),
                _item(f"{avg_px:.2f}", "#ffd700"),
                _item(f"{cur_px:.2f}", "#ffd700"),
                _item(f"{pnl:+.2f}", "#00ff00" if pnl >= 0 else "#ff0000"),
                _item(strategy, strat_color),
                _item(regime, "#aaaaaa"),
                _item(held, "#aaaaaa"),
                _item(intended, "#aaaaaa"),
            ]
            for col, item in enumerate(items):
                # Tooltip with full entry reason on the ticker cell
                if col == 0 and note.get("entry_reason"):
                    item.setToolTip(note["entry_reason"])
                self.table.setItem(row, col, item)


def _days_held(opened_at: str) -> str:
    """Compute human-readable time held from an ISO timestamp."""
    if not opened_at:
        return "--"
    try:
        opened = datetime.fromisoformat(opened_at)
        delta = datetime.now() - opened
        if delta.days > 0:
            return f"{delta.days}d"
        hours = delta.seconds // 3600
        return f"{hours}h" if hours > 0 else "<1h"
    except (ValueError, TypeError):
        return "--"


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
