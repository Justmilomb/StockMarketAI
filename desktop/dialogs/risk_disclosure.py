"""Risk disclosure dialog — shown at startup unless snoozed."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop.design import (
    AMBER,
    BASE_QSS,
    BG,
    BORDER,
    FONT_FAMILY,
    GLOW,
    SECONDARY_BTN_QSS,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
)

_SNOOZE_FILE = "risk_disclosure_snoozed_until.txt"
_SNOOZE_DAYS = 7


def _snooze_path() -> Path:
    try:
        from desktop.paths import user_data_dir
        return user_data_dir() / _SNOOZE_FILE
    except Exception:
        return Path.home() / ".blank" / _SNOOZE_FILE


def should_show() -> bool:
    """True if the risk disclosure should be shown on this launch."""
    p = _snooze_path()
    if not p.exists():
        return True
    try:
        until = datetime.fromisoformat(p.read_text(encoding="utf-8").strip())
        return datetime.now() >= until
    except Exception:
        return True


def _snooze() -> None:
    p = _snooze_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    until = datetime.now() + timedelta(days=_SNOOZE_DAYS)
    p.write_text(until.isoformat(), encoding="utf-8")


class RiskDisclosureDialog(QDialog):
    """One-paragraph risk warning shown at startup."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedWidth(480)
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowTitleHint
            | Qt.WindowCloseButtonHint
            | Qt.MSWindowsFixedSizeDialogHint
        )
        self.setStyleSheet(
            BASE_QSS
            + f"""
            QDialog {{
                border: 1px solid {BORDER};
                background: {BG};
            }}
        """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 24)
        outer.setSpacing(0)

        # amber label
        tag = QLabel("RISK DISCLOSURE")
        tag.setStyleSheet(
            f"color: {AMBER}; font-size: 9px; font-weight: 400;"
            f" font-family: {FONT_FAMILY}; letter-spacing: 3px;"
        )
        outer.addWidget(tag)
        outer.addSpacing(14)

        # body text
        body = QLabel(
            "blank is an autonomous AI trading tool. when connected to a live "
            "account, it places real orders using your funds without asking for "
            "approval on each trade. trading involves risk of financial loss — "
            "only trade with money you can afford to lose. past performance does "
            "not guarantee future results."
        )
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {TEXT_MID}; font-size: 13px; font-weight: 300;"
            f" font-family: {FONT_FAMILY}; line-height: 1.6;"
        )
        outer.addWidget(body)
        outer.addSpacing(24)

        # buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        snooze_btn = QPushButton("silence for 7 days")
        snooze_btn.setCursor(Qt.PointingHandCursor)
        snooze_btn.setStyleSheet(SECONDARY_BTN_QSS)
        snooze_btn.clicked.connect(self._on_snooze)
        btn_row.addWidget(snooze_btn)

        btn_row.addStretch()

        ok_btn = QPushButton("I understand")
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        outer.addLayout(btn_row)

    def _on_snooze(self) -> None:
        _snooze()
        self.accept()
