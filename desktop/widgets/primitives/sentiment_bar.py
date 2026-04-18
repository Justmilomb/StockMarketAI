"""Thin horizontal bar that encodes a sentiment score from -1..+1.

Used in the watchlist sentiment column and news cards. Renders as a
single-pixel track with a filled bar that shifts colour from red (-1)
through a dim mid-colour (0) to green (+1).
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from desktop import tokens as T


def _score_color(score: float) -> str:
    """Map -1..+1 onto the alert / fg-dim / accent palette."""
    if score >= 0.05:
        return T.ACCENT_HEX
    if score <= -0.05:
        return T.ALERT
    return T.FG_2_HEX


class SentimentBar(QWidget):
    """A 4-px track with a fill bar showing signed sentiment."""

    def __init__(self, score: float = 0.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setMinimumWidth(40)
        self._score = max(-1.0, min(1.0, float(score)))

    def set_score(self, score: float) -> None:
        self._score = max(-1.0, min(1.0, float(score)))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        painter.setPen(Qt.NoPen)
        # Track
        painter.setBrush(QColor(T.BORDER_0_HEX))
        painter.drawRect(0, 0, w, h)
        # Fill — starts at centre and extends either left (negative) or right
        half = w // 2
        magnitude = int(half * abs(self._score))
        painter.setBrush(QColor(_score_color(self._score)))
        if self._score >= 0:
            painter.drawRect(half, 0, magnitude, h)
        else:
            painter.drawRect(half - magnitude, 0, magnitude, h)
        painter.end()
