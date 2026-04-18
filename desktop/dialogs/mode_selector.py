"""Startup mode picker — Paper vs Live.

Shown before ``MainWindow`` is constructed. Two buttons, no noise.
Live is the bolder primary CTA; paper is a secondary ghost. A third
button quits the app. The caller unwraps ``run()`` which returns:

* ``True``  — user picked live trading
* ``False`` — user picked paper trading
* ``None``  — user quit

Paper mode always starts with a fresh £100 GBP broker (see
``desktop.app.MainWindow.__init__``), so there is no further state to
collect here.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T


class ModeSelector(QDialog):
    """Paper / Live startup picker."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedSize(520, 440)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )

        self._selected: Optional[bool] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 32)
        root.setSpacing(0)

        kicker = QLabel("CERTIFIED RANDOM")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 4px;"
        )
        root.addWidget(kicker)

        root.addSpacing(14)

        wordmark = QLabel("blank")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 56px; font-weight: 500;"
            f" letter-spacing: -0.03em;"
        )
        root.addWidget(wordmark)

        root.addSpacing(4)

        prompt = QLabel("Pick a mode to begin.")
        prompt.setAlignment(Qt.AlignCenter)
        prompt.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px;"
        )
        root.addWidget(prompt)

        root.addSpacing(32)

        root.addWidget(_ModeButton(
            title="PAPER MODE",
            blurb="Practice with a fresh £100 simulated account. No real money.",
            primary=False,
            on_click=lambda: self._select(True),
        ))

        root.addSpacing(10)

        root.addWidget(_ModeButton(
            title="LIVE MODE",
            blurb="Real orders on your Trading 212 account. Real money.",
            primary=True,
            on_click=lambda: self._select(False),
        ))

        root.addStretch(1)

        quit_btn = QPushButton("QUIT")
        quit_btn.setProperty("variant", "ghost")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setFixedHeight(32)
        quit_btn.clicked.connect(self.reject)
        root.addWidget(quit_btn)

    def _select(self, paper: bool) -> None:
        self._selected = paper
        self.accept()

    def run(self) -> Optional[bool]:
        """Show the picker. Returns ``True`` for paper, ``False`` for live, ``None`` for quit."""
        _show_modal = getattr(self, "exec")
        if _show_modal() == QDialog.Accepted:
            return self._selected
        return None


class _ModeButton(QFrame):
    """Card-style button with a title line and explanation beneath."""

    def __init__(
        self,
        *,
        title: str,
        blurb: str,
        primary: bool,
        on_click,
    ) -> None:
        super().__init__()
        self.setObjectName("ModeCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._on_click = on_click
        self._primary = primary
        self._apply_style(hover=False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 12px; font-weight: 600;"
            f" letter-spacing: 3px;"
        )
        text_col.addWidget(title_label)

        blurb_label = QLabel(blurb)
        blurb_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px;"
        )
        blurb_label.setWordWrap(True)
        text_col.addWidget(blurb_label)

        layout.addLayout(text_col, 1)

        arrow = QLabel("→")
        arrow.setStyleSheet(
            f"color: {T.ACCENT_HEX if primary else T.FG_2_HEX};"
            f" font-family: {T.FONT_MONO}; font-size: 20px;"
        )
        layout.addWidget(arrow, 0, Qt.AlignRight | Qt.AlignVCenter)

    def _apply_style(self, *, hover: bool) -> None:
        if self._primary:
            border = T.ACCENT_HEX if hover else T.ACCENT_BORDER
            bg = T.ACCENT_DIM if hover else "transparent"
        else:
            border = T.BORDER_1_HEX if hover else T.BORDER_0_HEX
            bg = T.BG_2 if hover else "transparent"
        self.setStyleSheet(
            f"QFrame#ModeCard {{ background: {bg}; border: 1px solid {border}; }}"
        )

    def enterEvent(self, event) -> None:  # Qt camelCase
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._on_click()
        super().mousePressEvent(event)
