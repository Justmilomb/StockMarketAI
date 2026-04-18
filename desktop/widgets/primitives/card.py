"""Bordered card container — 1 px hairline, optional accent top edge."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from desktop import tokens as T


class Card(QFrame):
    """Generic panel with a 1-px hairline border and a raised background.

    Pass ``accent_top=True`` to get a 1-px accent stripe on the top
    edge. Contents are laid out in a vertical box — access the layout
    via :meth:`content_layout`.
    """

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        padding: int = 16,
        accent_top: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        top_border = f"1px solid {T.ACCENT}" if accent_top else f"1px solid {T.BORDER_0}"
        self.setStyleSheet(
            f"QFrame#Card {{"
            f"  background: {T.BG_1};"
            f"  border: 1px solid {T.BORDER_0};"
            f"  border-top: {top_border};"
            f"  border-radius: 0;"
            f"}}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(padding, padding, padding, padding)
        self._layout.setSpacing(10)

    def content_layout(self) -> QVBoxLayout:
        return self._layout
