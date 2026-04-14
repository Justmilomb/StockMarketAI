"""Top-of-window mode banner — gold for PAPER, red for LIVE.

The Bloomberg-dark chrome is uniform across paper and live mode, so
before this banner it was alarmingly easy to forget which one you were
in. The banner is the loudest possible affordance: a full-width stripe
pinned above the chart, colour-coded, clickable to instantly flip the
mode. It is also the carrier for a keyboard shortcut
(``Ctrl+Shift+P``) that ``MainWindow`` wires directly to
``_toggle_agent_paper_mode``.

No confirmation dialog on click — the user explicitly asked for an
instant flip, and the click target is large + intentional enough that
accidental activation is unlikely. The banner itself never mutates
config; it only emits ``mode_clicked`` and lets the main window own
the state change.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


# Tuned for maximum legibility against the black chrome. Gold reads as
# "safe / fake"; red reads as "real money, pay attention".
_PAPER_BG = "#ffd700"
_PAPER_FG = "#000000"
_LIVE_BG = "#ff0000"
_LIVE_FG = "#ffffff"


class ModeBanner(QFrame):
    """Full-width, clickable banner announcing the current trading mode."""

    mode_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ModeBanner")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)

        self._label = QLabel("", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(0)
        row.addWidget(self._label, 1)

        # Default to paper so an uninitialised banner never implies live.
        self.set_mode(paper=True)

    # ── public API ───────────────────────────────────────────────────

    def set_mode(self, paper: bool) -> None:
        """Update the banner's colour and label to reflect ``paper``."""
        if paper:
            bg, fg = _PAPER_BG, _PAPER_FG
            text = "PAPER MODE — fake money — click to go LIVE"
            tip = (
                "You are in paper trading mode. No real orders are sent. "
                "Click to switch to LIVE trading (real money)."
            )
        else:
            bg, fg = _LIVE_BG, _LIVE_FG
            text = "LIVE TRADING — REAL MONEY — click to go PAPER"
            tip = (
                "You are in LIVE trading mode. Orders hit your real "
                "broker account. Click to switch back to paper."
            )
        self.setStyleSheet(
            f"QFrame#ModeBanner {{ background: {bg}; border: none; }}"
            f"QFrame#ModeBanner QLabel {{ background: transparent; "
            f"color: {fg}; font-weight: 700; letter-spacing: 1.5px; "
            f"font-size: 12px; }}",
        )
        self._label.setText(text)
        self.setToolTip(tip)

    # ── click-to-toggle ──────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.LeftButton:
            self.mode_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)
