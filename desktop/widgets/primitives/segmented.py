"""Two- or three-option segmented control (buy/sell, etc.).

Sharp-cornered, single-row button group with a hairline border and the
active segment filled in the accent colour.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from desktop import tokens as T


class Segmented(QFrame):
    """Horizontal segmented toggle. Emits :attr:`changed` on click."""

    changed = Signal(str)

    def __init__(
        self,
        options: List[str],
        initial: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ border: 1px solid {T.BORDER_1}; background: {T.BG_1}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._buttons: dict[str, QPushButton] = {}
        self._value: str = initial or options[0]

        for opt in options:
            btn = QPushButton(opt.upper(), self)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            btn.clicked.connect(self._make_handler(opt))
            row.addWidget(btn, 1)
            self._buttons[opt] = btn

        self._refresh_styles()

    def _make_handler(self, option: str) -> Callable[[], None]:
        def _handle() -> None:
            self.set_value(option)
        return _handle

    def set_value(self, option: str) -> None:
        if option == self._value or option not in self._buttons:
            return
        self._value = option
        self._refresh_styles()
        self.changed.emit(option)

    def value(self) -> str:
        return self._value

    def _refresh_styles(self) -> None:
        for opt, btn in self._buttons.items():
            active = opt == self._value
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {T.ACCENT if active else 'transparent'};"
                f"  color: {T.BG_0 if active else T.FG_1};"
                f"  border: none;"
                f"  padding: 10px 16px;"
                f"  font-family: {T.FONT_MONO};"
                f"  font-size: {T.STEP_1};"
                f"  letter-spacing: 2px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  color: {T.BG_0 if active else T.FG_0};"
                f"  background: {T.ACCENT if active else T.BG_3};"
                f"}}"
            )
