"""Ticker card — clean card widget for a single stock in the simple app."""
from __future__ import annotations

from typing import Any, Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from desktop.simple.theme import COLORS, change_color, signal_color


class TickerCard(QFrame):
    """Minimal card showing ticker, signal, probability, change, and AI summary."""

    clicked = Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._ticker = ""
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "TickerCard {"
            f"  background: {COLORS['surface']};"
            f"  border: 1px solid {COLORS['border']};"
            "  border-radius: 2px;"
            "  padding: 16px 20px;"
            "}"
            "TickerCard:hover {"
            f"  border-color: {COLORS['border_hover']};"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Top row: ticker | signal badge | prob | change
        top = QHBoxLayout()
        top.setSpacing(12)

        self._ticker_label = QLabel("")
        self._ticker_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #ffffff; background: transparent;",
        )
        top.addWidget(self._ticker_label)

        self._signal_label = QLabel("")
        self._signal_label.setAlignment(Qt.AlignCenter)
        self._signal_label.setFixedWidth(60)
        self._signal_label.setStyleSheet(
            "font-size: 11px; font-weight: 500; letter-spacing: 1px;"
            "padding: 3px 8px; border-radius: 2px; background: transparent;",
        )
        top.addWidget(self._signal_label)

        top.addStretch()

        self._prob_label = QLabel("")
        self._prob_label.setStyleSheet(
            f"font-size: 14px; font-weight: 300; color: {COLORS['text_mid']};"
            " background: transparent;",
        )
        top.addWidget(self._prob_label)

        self._change_label = QLabel("")
        self._change_label.setStyleSheet(
            "font-size: 14px; font-weight: 400; background: transparent;",
        )
        top.addWidget(self._change_label)

        layout.addLayout(top)

        # Bottom row: AI summary
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"font-size: 12px; font-weight: 200; color: {COLORS['text_dim']};"
            " background: transparent;",
        )
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
        """Populate the card with current data."""
        self._ticker = ticker
        self._ticker_label.setText(ticker)

        # Signal badge
        sig_color = signal_color(signal)
        self._signal_label.setText(signal.upper())
        self._signal_label.setStyleSheet(
            f"font-size: 11px; font-weight: 500; letter-spacing: 1px;"
            f"padding: 3px 8px; border-radius: 2px;"
            f"color: {sig_color}; border: 1px solid {sig_color};"
            f"background: transparent;",
        )

        # Probability
        self._prob_label.setText(f"{prob * 100:.0f}%")

        # Day change
        chg_color = change_color(change_pct)
        sign = "+" if change_pct >= 0 else ""
        self._change_label.setText(f"{sign}{change_pct:.1f}%")
        self._change_label.setStyleSheet(
            f"font-size: 14px; font-weight: 400; color: {chg_color}; background: transparent;",
        )

        # Summary
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
