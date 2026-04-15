"""Faint rotated watermark overlay for paper/live mode.

Sits as a transparent overlay on top of the chart (or any parent it's
handed to) and paints the word ``PAPER`` or ``LIVE`` diagonally across
its area at low alpha. Second-order affordance next to the top banner
— if the banner disappears (e.g., hidden in a minimal layout) this
still screams "you are not trading real money" from behind every
candle.

Does not eat mouse events: pass-through is enforced via the
``WA_TransparentForMouseEvents`` attribute so clicking through the
watermark into the chart works normally.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


# Paper is the one that screams — the whole point of the watermark is
# to remind the user the money is fake even when the top banner is
# hidden. Live mode paints nothing at all (see ``paintEvent``): a pro
# trader staring at real orders doesn't need a giant diagonal LIVE
# bleeding through every candle.
_PAPER_RGBA = (255, 215, 0, 28)


class ModeWatermark(QWidget):
    """Rotated, low-alpha ``PAPER`` / ``LIVE`` label painted over its parent."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._paper: bool = True
        if parent is not None:
            # Stretch to cover the parent completely and follow resizes.
            parent.installEventFilter(self)
            self.resize(parent.size())
            self.raise_()

    # ── public API ───────────────────────────────────────────────────

    def set_mode(self, paper: bool) -> None:
        self._paper = bool(paper)
        self.update()

    # ── parent-follow plumbing ───────────────────────────────────────

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API
        from PySide6.QtCore import QEvent
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.resize(self.parent().size())
            self.raise_()
        return False

    # ── painting ─────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt API
        # Live mode: no watermark. The user explicitly opened the live
        # window, a gigantic translucent LIVE over the chart is just noise.
        if not self._paper:
            return
        text = "PAPER"
        rgba = _PAPER_RGBA
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            # Font scales with the widget — but capped so a huge
            # window doesn't end up with a wall of text.
            pixel_size = max(96, min(self.height() // 3, 260))
            font = QFont("Outfit", pointSize=-1)
            font.setPixelSize(pixel_size)
            font.setWeight(QFont.Black)
            font.setLetterSpacing(QFont.PercentageSpacing, 140.0)
            painter.setFont(font)

            painter.translate(self.width() / 2, self.height() / 2)
            painter.rotate(-28.0)

            colour = QColor(*rgba)
            painter.setPen(colour)
            rect = painter.fontMetrics().boundingRect(text)
            painter.drawText(-rect.width() // 2, rect.height() // 4, text)
        finally:
            painter.end()
