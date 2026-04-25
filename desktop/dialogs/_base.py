"""Shared dialog scaffold.

Every user-facing QDialog in the app should inherit from ``BaseDialog``
so the chrome stays uniform: tracked-out mono kicker, uppercase title,
hairline footer divider, and consistent padding. The dialog body is
the caller's QLayout slotted into ``body_layout``.
"""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.widgets.primitives.button import apply_variant


class BaseDialog(QDialog):
    """Terminal-styled dialog with kicker + title + optional footer buttons.

    Subclasses populate ``body_layout()`` with their content. Footer
    buttons (if any) are appended via ``add_footer_button``.
    """

    def __init__(
        self,
        *,
        kicker: str,
        title: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title.capitalize())
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_0}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(0)

        kicker_label = QLabel(kicker.upper())
        kicker_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px; padding: 0;"
        )
        root.addWidget(kicker_label)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em; padding: 4px 0 14px 0;"
        )
        title_label.setWordWrap(True)
        root.addWidget(title_label)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        self._body_host = QWidget()
        self._body_layout = QVBoxLayout(self._body_host)
        self._body_layout.setContentsMargins(0, 14, 0, 14)
        self._body_layout.setSpacing(10)
        root.addWidget(self._body_host, 1)

        foot_rule = QFrame()
        foot_rule.setFixedHeight(1)
        foot_rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(foot_rule)

        self._footer = QHBoxLayout()
        self._footer.setContentsMargins(0, 14, 0, 0)
        self._footer.setSpacing(8)
        self._footer.addStretch(1)
        root.addLayout(self._footer)

    # Public access for subclasses ────────────────────────────────────
    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def set_body_layout(self, layout: QLayout) -> None:
        """Replace the default body layout with a caller-supplied one."""
        old = self._body_layout
        QWidget().setLayout(old)  # detach the old layout
        self._body_host.setLayout(layout)
        layout.setContentsMargins(0, 14, 0, 14)
        self._body_layout = layout  # type: ignore[assignment]

    def add_footer_button(
        self,
        text: str,
        *,
        variant: str = "ghost",
        slot=None,
    ) -> QPushButton:
        btn = QPushButton(text.upper())
        apply_variant(btn, variant)
        btn.setCursor(Qt.PointingHandCursor)
        if slot is not None:
            btn.clicked.connect(slot)
        self._footer.addWidget(btn)
        return btn

    def add_footer_buttons(
        self, buttons: Iterable[tuple[str, str, object]],
    ) -> list[QPushButton]:
        """Convenience helper — each tuple is ``(text, variant, slot)``."""
        out: list[QPushButton] = []
        for text, variant, slot in buttons:
            out.append(self.add_footer_button(text, variant=variant, slot=slot))
        return out
