"""Ticker card -- stat-card style widget matching the blank admin panel."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from desktop.design import (
    BG,
    BORDER,
    BORDER_HOVER,
    GLOW,
    GLOW_BORDER,
    RED,
    AMBER,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)


def _signal_color(signal: str) -> str:
    s = signal.upper()
    if "BUY" in s:
        return GLOW
    if "SELL" in s:
        return RED
    return AMBER


def _change_color(pct: float) -> str:
    if pct > 0.01:
        return GLOW
    if pct < -0.01:
        return RED
    return TEXT_DIM


class TickerCard(QFrame):
    """Stat-card style ticker widget matching the admin panel design."""

    clicked = Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._ticker = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            TickerCard {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 2px;
            }}
            TickerCard:hover {{
                border-color: {BORDER_HOVER};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(0)

        # Row 1: dim label (ticker name) + signal badge on right
        top_row = QHBoxLayout()
        top_row.setSpacing(0)

        self._ticker_label = QLabel("")
        self._ticker_label.setStyleSheet(f"""
            font-size: 13px; font-weight: 300; color: {TEXT_MID};
            font-family: {FONT_FAMILY};
            letter-spacing: 0.06em; background: transparent;
        """)
        top_row.addWidget(self._ticker_label)

        top_row.addStretch()

        self._signal_label = QLabel("")
        self._signal_label.setAlignment(Qt.AlignCenter)
        self._signal_label.setStyleSheet(f"""
            font-size: 11px; font-weight: 400; color: {TEXT_DIM};
            font-family: {FONT_FAMILY};
            letter-spacing: 1px; padding: 2px 10px;
            border: 1px solid {BORDER}; border-radius: 2px;
            background: transparent;
        """)
        top_row.addWidget(self._signal_label)

        layout.addLayout(top_row)
        layout.addSpacing(8)

        # Row 2: big price number + change percentage
        price_row = QHBoxLayout()
        price_row.setSpacing(12)

        self._price_label = QLabel("--")
        self._price_label.setStyleSheet(f"""
            font-size: 32px; font-weight: 700; color: {TEXT};
            font-family: {FONT_FAMILY};
            letter-spacing: -0.02em; background: transparent;
        """)
        price_row.addWidget(self._price_label)

        self._change_label = QLabel("")
        self._change_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 400; color: {TEXT_DIM};
            font-family: {FONT_FAMILY};
            background: transparent;
        """)
        self._change_label.setAlignment(Qt.AlignBottom)
        price_row.addWidget(self._change_label)

        price_row.addStretch()

        self._prob_label = QLabel("")
        self._prob_label.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        self._prob_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 300; color: {TEXT_DIM};
            font-family: {FONT_FAMILY};
            background: transparent;
        """)
        price_row.addWidget(self._prob_label)

        layout.addLayout(price_row)
        layout.addSpacing(8)

        # Row 3: AI summary in green (like admin subtitle)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"""
            font-size: 12px; font-weight: 300; color: {GLOW};
            font-family: {FONT_FAMILY};
            letter-spacing: 0.02em; background: transparent;
        """)
        self._summary_label.setWordWrap(True)
        layout.addWidget(self._summary_label)

    def update_data(
        self,
        ticker: str,
        signal: str = "HOLD",
        prob: float = 0.5,
        change_pct: float = 0.0,
        summary: str = "",
        price: float = 0.0,
    ) -> None:
        self._ticker = ticker

        # Ticker label (dim, like admin card header)
        self._ticker_label.setText(ticker.lower())

        # Signal badge
        sig_color = _signal_color(signal)
        self._signal_label.setText(signal.lower())
        self._signal_label.setStyleSheet(f"""
            font-size: 11px; font-weight: 400;
            font-family: {FONT_FAMILY};
            letter-spacing: 1px; padding: 2px 10px;
            color: {sig_color}; border: 1px solid {sig_color};
            border-radius: 2px; background: transparent;
        """)

        # Price (big number, like admin stat)
        if price > 0:
            self._price_label.setText(f"{price:,.2f}")
        else:
            self._price_label.setText("--")

        # Change
        chg_color = _change_color(change_pct)
        sign = "+" if change_pct >= 0 else ""
        self._change_label.setText(f"{sign}{change_pct:.2f}%")
        self._change_label.setStyleSheet(f"""
            font-size: 14px; font-weight: 400; color: {chg_color};
            font-family: {FONT_FAMILY};
            background: transparent;
        """)

        # Probability
        self._prob_label.setText(f"{prob * 100:.0f}% confidence")

        # Summary (green subtitle, like admin card detail)
        if summary:
            self._summary_label.setText(summary.lower())
            self._summary_label.show()
        else:
            self._summary_label.hide()

    def ticker(self) -> str:
        return self._ticker

    def mousePressEvent(self, event: Any) -> None:
        if self._ticker:
            self.clicked.emit(self._ticker)
        super().mousePressEvent(event)
