"""Risk disclosure dialog — shown at startup unless snoozed."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QLabel

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog

_SNOOZE_FILE = "risk_disclosure_snoozed_until.txt"
_SNOOZE_DAYS = 7


def _snooze_path() -> Path:
    try:
        from desktop.paths import user_data_dir
        return user_data_dir() / _SNOOZE_FILE
    except Exception:
        return Path.home() / ".blank" / _SNOOZE_FILE


def should_show() -> bool:
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


class RiskDisclosureDialog(BaseDialog):
    """One-paragraph risk warning shown at startup."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(
            kicker="RISK DISCLOSURE",
            title="Trading involves risk",
            parent=parent,
        )
        self.setFixedSize(520, 360)

        body = self.body_layout()

        text = QLabel(
            "blank is an autonomous AI trading tool. When connected to a"
            " live account it places real orders using your funds without"
            " asking for approval on each trade. Trading carries risk of"
            " financial loss \u2014 only trade with money you can afford"
            " to lose. Past performance does not guarantee future results."
        )
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px; line-height: 1.6;"
        )
        body.addWidget(text)
        body.addStretch(1)

        self.add_footer_button(
            "SILENCE FOR 7 DAYS", variant="ghost", slot=self._on_snooze,
        )
        self.add_footer_button(
            "I UNDERSTAND", variant="primary", slot=self.accept,
        )

    def _on_snooze(self) -> None:
        _snooze()
        self.accept()
