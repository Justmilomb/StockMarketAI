"""Exchanges panel — open/closed clock for every venue we trade.

Mirrors the visual language of the positions panel (sharp corners,
terminal palette, centered cells) but the data is purely time-driven:
:mod:`core.market_hours` reports each exchange's current state and
:mod:`core.market_hours.exchange_for_ticker` joins the broker's
positions to their host venue so the table can show how many holdings
the user has on each market.

A single QTimer ticks every 30 seconds so the OPEN/CLOSED column flips
within half a minute of a real session boundary. Refreshing is also
called explicitly whenever ``state.positions`` changes via
``refresh_view``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.market_hours import (
    Exchange,
    all_exchanges,
    exchange_for_ticker,
    status,
)


COLUMNS = ["Exchange", "Country", "Status", "Local Time", "Next", "Pos"]

#: Terminal palette (matches positions / orders panels).
COLOR_TICKER = "#00bfff"   # cyan — exchange code
COLOR_VALUE = "#ffd700"    # gold — counts and times
COLOR_DIM = "#aaaaaa"      # dim grey — country / inactive
COLOR_OPEN = "#00ff00"     # green — market open
COLOR_CLOSED = "#ff0000"   # red — market closed


class ExchangesPanel(QGroupBox):
    """Terminal-style markets clock with positions-per-venue."""

    def __init__(self, state: Any) -> None:
        super().__init__("MARKETS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Cache the last state so the timer-driven refresh sees the latest
        # positions even if MainWindow doesn't push an update.
        self._last_state: Any = state

        # Tick the OPEN/CLOSED column every 30 s so a session boundary
        # is reflected within half a minute. The timer is parented to
        # the panel so it dies with it.
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        """Repaint the table from the latest ``AppState``."""
        self._last_state = state
        positions: List[Dict[str, Any]] = list(getattr(state, "positions", []) or [])
        counts = _positions_per_exchange(positions)
        self._render(counts)

    def _tick(self) -> None:
        """Timer-driven repaint. Uses cached positions from last refresh."""
        positions: List[Dict[str, Any]] = list(
            getattr(self._last_state, "positions", []) or []
        )
        counts = _positions_per_exchange(positions)
        self._render(counts)

    def _render(self, counts: Dict[str, int]) -> None:
        exchanges = all_exchanges()
        self.table.setRowCount(len(exchanges))
        now = datetime.utcnow()
        for row, ex in enumerate(exchanges):
            snap = status(ex, now)
            is_open = bool(snap["is_open"])
            local_now = _hhmm(str(snap["local_now"]))
            transition = _hhmm(
                str(snap["next_close" if is_open else "next_open"])
            )
            count = counts.get(ex.code, 0)

            row_items = [
                _item(ex.code, COLOR_TICKER),
                _item(ex.country, COLOR_DIM),
                _item("OPEN" if is_open else "CLOSED",
                      COLOR_OPEN if is_open else COLOR_CLOSED),
                _item(local_now, COLOR_VALUE),
                _item(transition, COLOR_VALUE if is_open else COLOR_DIM),
                _item(str(count) if count else "--",
                      COLOR_VALUE if count else COLOR_DIM),
            ]
            for col, item in enumerate(row_items):
                if col == 0:
                    item.setToolTip(f"{ex.name} — {ex.timezone}")
                self.table.setItem(row, col, item)


def _positions_per_exchange(positions: List[Dict[str, Any]]) -> Dict[str, int]:
    """Bucket broker positions by exchange code (UNKNOWN for unmapped)."""
    counts: Dict[str, int] = {}
    for p in positions:
        ticker = str(p.get("ticker", ""))
        ex: Exchange | None = exchange_for_ticker(ticker)
        code = ex.code if ex else "UNKNOWN"
        counts[code] = counts.get(code, 0) + 1
    return counts


def _hhmm(iso_local: str) -> str:
    """``2026-04-14T09:30-04:00`` → ``09:30``."""
    if not iso_local:
        return "--"
    try:
        # Drop the date portion and the trailing tz offset.
        time_part = iso_local.split("T", 1)[1]
        # `09:30-04:00` → `09:30`
        for sep in ("+", "-"):
            idx = time_part.find(sep, 1)
            if idx > 0:
                time_part = time_part[:idx]
                break
        return time_part[:5]
    except Exception:
        return "--"


def _item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setForeground(QColor(color))
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item
