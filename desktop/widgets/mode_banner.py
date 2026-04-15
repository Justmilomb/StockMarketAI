"""Top-of-window mode banner — loud gold for PAPER, quiet for LIVE.

Paper mode is the one we want to shout about: it's easy to forget
you're playing with fake money when the chrome is identical to the
live window, and a mistakenly-reassuring £100 return looks great
until you notice the 'PAPER' suffix. Live mode is the opposite — the
user explicitly chose to trade real money; they don't need a red
strobe reminding them. A small, dim status strip is enough.

v1.0.0: the banner is **not** clickable any more. Paper and live are
now separate windows opened from the mode selector, so there is no
in-place toggle to emit. ``MainWindow`` handles the mode flip via
the agent menu; the banner is purely informational.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


# Paper: loud gold-on-black — impossible to miss.
_PAPER_BG = "#ffd700"
_PAPER_FG = "#000000"
# Live: near-black strip with dim red text — present, but calm.
_LIVE_BG = "#0a0a0a"
_LIVE_FG = "#8a1c1c"


class ModeBanner(QFrame):
    """Full-width banner announcing the current trading mode."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ModeBanner")
        self.setFixedHeight(28)

        self._label = QLabel("", self)
        self._label.setAlignment(Qt.AlignCenter)

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
            text = "PAPER MODE — fake money — no real orders sent"
            tip = "Paper trading mode. No real orders are sent."
            weight = 700
            letter_spacing = 1.5
            font_size = 12
        else:
            bg, fg = _LIVE_BG, _LIVE_FG
            text = "LIVE"
            tip = "Live trading mode. Orders hit your real broker account."
            weight = 500
            letter_spacing = 3.0
            font_size = 10
        self.setStyleSheet(
            f"QFrame#ModeBanner {{ background: {bg}; border: none; }}"
            f"QFrame#ModeBanner QLabel {{ background: transparent; "
            f"color: {fg}; font-weight: {weight}; "
            f"letter-spacing: {letter_spacing}px; "
            f"font-size: {font_size}px; }}",
        )
        self._label.setText(text)
        self.setToolTip(tip)
