"""Paper-mode onboarding — single-screen intro to practice trading.

Deliberately minimal. Paper mode is the safe sandbox, so the copy is
reassurance-first: explain what's happening, what isn't at risk, and how
to start. One "don't show again" checkbox, one primary button.

The "don't show again" state lives in
:mod:`desktop.onboarding_state` and is silently reset every 30 days.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.onboarding_state import mark_paper_done
from desktop.widgets.primitives.button import apply_variant


_BULLETS = [
    ("FRESH £100", "Every paper session starts with a clean £100 balance. No real money."),
    ("SAME ADVISOR", "Your blank advisor trades here exactly like it would live — only the orders are fake."),
    ("LESSONS CARRY", "What it learns in paper carries forward to live trading. The trades do not."),
    ("PRESS START", "Click START in the AGENT panel when you're ready. Click STOP any time."),
]


class PaperOnboardingDialog(QDialog):
    """One-screen introduction to paper mode."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank — paper mode")
        self.setFixedSize(560, 560)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )

        self._dont_show_cb = QCheckBox("Don't show this again")
        self._dont_show_cb.setStyleSheet(_checkbox_qss())
        self._dont_show_cb.setCursor(Qt.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 28)
        root.setSpacing(0)

        kicker = QLabel("PAPER MODE")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 4px;"
        )
        root.addWidget(kicker)

        root.addSpacing(10)

        title = QLabel("You're practising — nothing is real.")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em;"
        )
        root.addWidget(title)

        root.addSpacing(6)

        blurb = QLabel(
            "Paper mode runs your advisor against live prices with a simulated "
            "£100 account. No broker, no real orders, no risk."
        )
        blurb.setAlignment(Qt.AlignCenter)
        blurb.setWordWrap(True)
        blurb.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px; line-height: 1.5;"
        )
        root.addWidget(blurb)

        root.addSpacing(18)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        root.addSpacing(18)

        for label, text in _BULLETS:
            root.addWidget(_bullet_row(label, text))
            root.addSpacing(10)

        root.addStretch(1)

        check_row = QHBoxLayout()
        check_row.addWidget(self._dont_show_cb)
        check_row.addStretch(1)
        root.addLayout(check_row)

        root.addSpacing(10)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)

        start_btn = QPushButton("START PAPER TRADING")
        apply_variant(start_btn, "primary")
        start_btn.setCursor(Qt.PointingHandCursor)
        start_btn.setFixedHeight(36)
        start_btn.clicked.connect(self._on_start)
        button_row.addWidget(start_btn)

        root.addLayout(button_row)

    def _on_start(self) -> None:
        mark_paper_done(self._dont_show_cb.isChecked())
        self.accept()

    def run(self) -> None:
        _show_modal = getattr(self, "exec")
        _show_modal()


def _bullet_row(label: str, text: str) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)

    kicker = QLabel(label)
    kicker.setFixedWidth(110)
    kicker.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    kicker.setStyleSheet(
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding-top: 3px;"
    )
    row.addWidget(kicker)

    body = QLabel(text)
    body.setWordWrap(True)
    body.setStyleSheet(
        f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
        f" font-size: 13px; line-height: 1.5;"
    )
    row.addWidget(body, 1)

    return host


def _checkbox_qss() -> str:
    return (
        f"QCheckBox {{ color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
        f" font-size: 12px; spacing: 8px; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px;"
        f" border: 1px solid {T.BORDER_1}; background: transparent; }}"
        f"QCheckBox::indicator:hover {{ border-color: {T.FG_1_HEX}; }}"
        f"QCheckBox::indicator:checked {{ background: {T.ACCENT_HEX};"
        f" border-color: {T.ACCENT_HEX}; }}"
    )
