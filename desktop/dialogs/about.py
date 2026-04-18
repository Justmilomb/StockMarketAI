"""About dialog — app identity and version."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from desktop import __version__, tokens as T
from desktop.dialogs._base import BaseDialog


class AboutDialog(BaseDialog):
    """Shown from the Help menu."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(
            kicker="CERTIFIED RANDOM",
            title="blank",
            parent=parent,
        )
        self.setFixedSize(380, 260)

        body = self.body_layout()
        body.setAlignment(Qt.AlignCenter)

        version_label = QLabel(f"Version {__version__}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 12px; letter-spacing: 1px;"
        )
        body.addWidget(version_label)

        tagline = QLabel("AI-driven trading terminal.")
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px;"
        )
        body.addWidget(tagline)

        body.addStretch(1)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.accept)
