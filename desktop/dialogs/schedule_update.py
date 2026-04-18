"""Modal dialog for picking when an update should install."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateTimeEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.dialogs._base import BaseDialog


_RADIO_QSS = f"""
QRadioButton {{
    color: {T.FG_0};
    font-family: {T.FONT_SANS};
    font-size: 13px;
    padding: 6px 4px;
    spacing: 10px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 10px;
    height: 10px;
    border: 1px solid {T.BORDER_1};
    border-radius: 0;
    background: transparent;
}}
QRadioButton::indicator:hover {{
    border-color: {T.ACCENT_HEX};
}}
QRadioButton::indicator:checked {{
    background: {T.ACCENT_HEX};
    border-color: {T.ACCENT_HEX};
}}
"""

_DATE_EDIT_QSS = f"""
QDateTimeEdit {{
    background: transparent;
    color: {T.FG_0};
    border: none;
    border-bottom: 1px solid {T.BORDER_1};
    border-radius: 0;
    padding: 6px 0;
    font-family: {T.FONT_MONO};
    font-size: 13px;
}}
QDateTimeEdit:focus {{
    border-bottom: 1px solid {T.ACCENT_HEX};
}}
"""


class ScheduleUpdateDialog(BaseDialog):
    """Preset-first schedule picker."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            kicker="POSTPONE",
            title="Schedule install",
            parent=parent,
        )
        self.setFixedWidth(460)

        self._result_dt: Optional[datetime] = None
        self._group = QButtonGroup(self)
        self._options: list[tuple[QRadioButton, datetime]] = []

        body = self.body_layout()

        now = datetime.now()
        self._add_preset(body, "In 1 hour", now + timedelta(hours=1))
        self._add_preset(body, "In 4 hours", now + timedelta(hours=4))
        self._add_preset(body, "Tonight at 22:00", self._next_time(now, hour=22, minute=0))
        self._add_preset(
            body, "Tomorrow at 03:00",
            self._next_time(now, hour=3, minute=0, min_offset_hours=6),
        )

        self._custom_radio = QRadioButton("Custom")
        self._custom_radio.setStyleSheet(_RADIO_QSS)
        self._group.addButton(self._custom_radio)
        body.addWidget(self._custom_radio)

        self._custom_edit = QDateTimeEdit()
        self._custom_edit.setCalendarPopup(True)
        self._custom_edit.setDisplayFormat("yyyy-MM-dd  HH:mm")
        self._custom_edit.setDateTime(now + timedelta(hours=2))
        self._custom_edit.setEnabled(False)
        self._custom_edit.setStyleSheet(_DATE_EDIT_QSS)
        body.addWidget(self._custom_edit)

        self._custom_radio.toggled.connect(self._custom_edit.setEnabled)

        if self._options:
            self._options[0][0].setChecked(True)

        body.addStretch(1)

        self.add_footer_button("CANCEL", variant="ghost", slot=self.reject)
        self.add_footer_button("SCHEDULE", variant="primary", slot=self._on_confirm)

    def chosen_datetime(self) -> Optional[datetime]:
        return self._result_dt

    def _add_preset(self, layout: QVBoxLayout, label: str, when: datetime) -> None:
        display = f"{label}  \u2014  {when.strftime('%a %H:%M')}"
        radio = QRadioButton(display)
        radio.setStyleSheet(_RADIO_QSS)
        radio.setCursor(Qt.PointingHandCursor)
        self._group.addButton(radio)
        layout.addWidget(radio)
        self._options.append((radio, when))

    @staticmethod
    def _next_time(
        now: datetime,
        *,
        hour: int,
        minute: int,
        min_offset_hours: int = 1,
    ) -> datetime:
        target = datetime.combine(now.date(), time(hour=hour, minute=minute))
        if target < now + timedelta(hours=min_offset_hours):
            target = target + timedelta(days=1)
        return target

    def _on_confirm(self) -> None:
        if self._custom_radio.isChecked():
            q_dt = self._custom_edit.dateTime().toPython()
            if isinstance(q_dt, datetime):
                self._result_dt = q_dt
        else:
            for radio, when in self._options:
                if radio.isChecked():
                    self._result_dt = when
                    break
        if self._result_dt is None:
            self.reject()
            return
        self.accept()
