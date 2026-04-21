"""Borderless QLineEdit with only a bottom hairline — for forms."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLineEdit, QWidget

from desktop import tokens as T


class UnderlineInput(QLineEdit):
    """Form input styled as a single bottom line, like the website forms."""

    def __init__(self, placeholder: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(
            f"QLineEdit {{"
            f"  background: transparent;"
            f"  color: {T.FG_0};"
            f"  border: none;"
            f"  border-bottom: 1px solid {T.BORDER_1};"
            f"  padding: 10px 0 8px 0;"
            f"  font-family: {T.FONT_MONO};"
            f"  font-size: {T.STEP_4};"
            f"  selection-background-color: {T.ACCENT_DIM};"
            f"}}"
            f"QLineEdit:focus {{"
            f"  border-bottom-color: {T.ACCENT};"
            f"}}"
            f"QLineEdit::placeholder {{"
            f"  color: {T.FG_2};"
            f"}}"
        )
