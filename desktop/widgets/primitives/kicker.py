"""Tracked-out uppercase mono label.

Used for section labels, panel kickers, and metadata captions. Matches
the ``.kicker`` class on the marketing site: mono font, wide
``letter-spacing``, uppercase, low-contrast colour.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QWidget

from desktop import tokens as T


class Kicker(QLabel):
    """Small uppercase mono caption with wide letter spacing."""

    def __init__(
        self,
        text: str = "",
        parent: Optional[QWidget] = None,
        *,
        accent: bool = False,
        size: str = T.STEP_0,
        spacing: str = T.TRACK_KICKER,
    ) -> None:
        super().__init__(text.upper(), parent)
        color = T.ACCENT if accent else T.FG_2
        self.setStyleSheet(
            f"color: {color};"
            f"font-family: {T.FONT_MONO};"
            f"font-size: {size};"
            f"letter-spacing: {spacing};"
            f"background: transparent;"
        )
