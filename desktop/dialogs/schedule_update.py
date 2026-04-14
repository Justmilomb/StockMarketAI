"""Modal dialog for picking when an update should install.

The update banner opens this dialog when the user clicks "schedule".
Returns a naive ``datetime`` in local wall-clock time on accept, which
``UpdateService.schedule_install`` then normalises to UTC before
persisting.

The preset options are deliberately coarse: the goal is "get the user
out of my way in one click", not to build a full calendar picker. A
custom slot is available for power users who want a specific time.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDateTimeEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from desktop.design import (
    BASE_QSS,
    BORDER,
    FONT_FAMILY,
    GLOW,
    GLOW_BORDER,
    GLOW_DIM,
    GLOW_MID,
    SECONDARY_BTN_QSS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
)


_DIALOG_QSS = f"""
QDialog {{
    background: #000000;
    border: 1px solid {GLOW_BORDER};
}}
QDialog QLabel {{
    color: {TEXT_MID};
    font-family: {FONT_FAMILY};
    font-size: 12px;
    background: transparent;
}}
QDialog QLabel#TitleLabel {{
    color: {TEXT};
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QDialog QLabel#SubtitleLabel {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 300;
    letter-spacing: 0.8px;
}}
QDialog QRadioButton {{
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: 12px;
    padding: 6px 4px;
    spacing: 10px;
    background: transparent;
}}
QDialog QRadioButton::indicator {{
    width: 12px;
    height: 12px;
    border: 1px solid {BORDER};
    border-radius: 0;
    background: {SURFACE};
}}
QDialog QRadioButton::indicator:hover {{
    border-color: {GLOW_BORDER};
}}
QDialog QRadioButton::indicator:checked {{
    background: {GLOW};
    border-color: {GLOW};
}}
QDialog QDateTimeEdit {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 0;
    padding: 6px 10px;
    font-family: {FONT_FAMILY};
    font-size: 12px;
    selection-background-color: {GLOW_MID};
}}
QDialog QDateTimeEdit:focus {{
    border-color: {GLOW_BORDER};
}}
QDialog QPushButton {{
    background: transparent;
    color: {GLOW};
    border: 1px solid {GLOW_BORDER};
    border-radius: 0;
    padding: 8px 20px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 1px;
}}
QDialog QPushButton:hover {{
    background: {GLOW};
    color: #000000;
}}
"""


class ScheduleUpdateDialog(QDialog):
    """Preset-first schedule picker.

    Presets are relative to "now at time the dialog opens", so "tonight
    at 22:00" means 22:00 today if it hasn't passed yet, otherwise 22:00
    tomorrow.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Schedule update")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(BASE_QSS + _DIALOG_QSS)

        self._result_dt: Optional[datetime] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(10)

        title = QLabel("SCHEDULE INSTALL")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("pick when blank should install the update")
        subtitle.setObjectName("SubtitleLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(12)

        # Preset radios
        self._group = QButtonGroup(self)
        now = datetime.now()
        self._options: list[tuple[QRadioButton, datetime]] = []

        self._add_preset(layout, "in 1 hour", now + timedelta(hours=1))
        self._add_preset(layout, "in 4 hours", now + timedelta(hours=4))
        self._add_preset(layout, "tonight at 22:00", self._next_time(now, hour=22, minute=0))
        self._add_preset(layout, "tomorrow at 03:00", self._next_time(now, hour=3, minute=0, min_offset_hours=6))

        self._custom_radio = QRadioButton("custom")
        self._group.addButton(self._custom_radio)
        layout.addWidget(self._custom_radio)

        self._custom_edit = QDateTimeEdit()
        self._custom_edit.setCalendarPopup(True)
        self._custom_edit.setDisplayFormat("yyyy-MM-dd  HH:mm")
        self._custom_edit.setDateTime(now + timedelta(hours=2))
        self._custom_edit.setEnabled(False)
        layout.addWidget(self._custom_edit)

        self._custom_radio.toggled.connect(self._custom_edit.setEnabled)

        # Default to the first preset
        if self._options:
            self._options[0][0].setChecked(True)

        layout.addSpacing(16)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setStyleSheet(SECONDARY_BTN_QSS)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("SCHEDULE")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(confirm_btn)

        layout.addLayout(btn_row)

    # ─── public ─────────────────────────────────────────────────────────

    def chosen_datetime(self) -> Optional[datetime]:
        """Local wall-clock datetime the user picked, or None on cancel."""
        return self._result_dt

    # ─── preset construction ────────────────────────────────────────────

    def _add_preset(self, layout: QVBoxLayout, label: str, when: datetime) -> None:
        display = f"{label}  —  {when.strftime('%a %H:%M')}"
        radio = QRadioButton(display)
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
        """Return the next occurrence of ``hour:minute`` after ``now``.

        ``min_offset_hours`` ensures "tomorrow at 03:00" really means
        tomorrow even when the user opens the dialog at 02:30 — without
        it, the "tomorrow" preset would resolve to 30 minutes from now,
        which would be surprising.
        """
        target = datetime.combine(now.date(), time(hour=hour, minute=minute))
        if target < now + timedelta(hours=min_offset_hours):
            target = target + timedelta(days=1)
        return target

    # ─── slot ───────────────────────────────────────────────────────────

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
