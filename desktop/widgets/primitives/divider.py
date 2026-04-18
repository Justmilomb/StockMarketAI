"""1-px horizontal and vertical hairlines used throughout the UI."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QWidget

from desktop import tokens as T


class HDivider(QFrame):
    """1-px horizontal hairline (``border-bottom: 1px solid border_0``)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {T.BORDER_0};")


class VDivider(QFrame):
    """1-px vertical hairline (useful in status bars)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(1)
        self.setStyleSheet(f"background-color: {T.BORDER_0};")
