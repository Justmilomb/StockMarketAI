"""Small coloured dot used in status bars and the exchanges panel."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from desktop import tokens as T


_COLOR_FOR_STATE = {
    "ok":       T.ACCENT_HEX,
    "warn":     T.WARN,
    "alert":    T.ALERT,
    "off":      T.FG_2_HEX,
    "muted":    T.FG_3_HEX,
}


class StatusDot(QWidget):
    """6-px dot that renders a status colour. Colour selected by state.

    States: ``ok`` (green), ``warn`` (amber), ``alert`` (red),
    ``off`` (muted grey), ``muted`` (near-invisible).
    """

    def __init__(self, state: str = "off", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._state = state

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt API
        color_hex = _COLOR_FOR_STATE.get(self._state, T.FG_3_HEX)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color_hex))
        painter.drawEllipse(1, 1, 6, 6)
        painter.end()
