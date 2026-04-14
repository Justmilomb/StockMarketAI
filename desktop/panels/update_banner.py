"""Top-of-window banner announcing an available update.

Invisible by default. The ``MainWindow`` owns an instance of this
widget wedged into the first row of its central layout; the
``UpdateService`` signal ``update_available`` triggers ``show_update``,
which flips it visible and populates it with the manifest contents.

Two states:
    *available* — user hasn't scheduled anything. Buttons: install now,
                  schedule, skip version, dismiss.
    *scheduled* — user already picked a time. Shows the countdown and
                  offers: install now, cancel schedule.

Release notes are collapsed by default and expand inline when the user
clicks "what's new" — we don't want to eat vertical space for users who
just want to dismiss the banner.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.design import (
    BG,
    BORDER,
    FONT_FAMILY,
    GLOW,
    GLOW_BORDER,
    GLOW_DIM,
    GLOW_MID,
    RED,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
)


_BANNER_QSS = f"""
QFrame#UpdateBanner {{
    background: {SURFACE};
    border: 1px solid {GLOW_BORDER};
    border-radius: 0;
}}
QFrame#UpdateBanner QLabel {{
    background: transparent;
    color: {TEXT_MID};
    font-family: {FONT_FAMILY};
    font-size: 12px;
}}
QFrame#UpdateBanner QLabel#HeadlineLabel {{
    color: {GLOW};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}
QFrame#UpdateBanner QLabel#StatusLabel {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 300;
}}
QFrame#UpdateBanner QPushButton {{
    background: transparent;
    color: {GLOW};
    border: 1px solid {GLOW_BORDER};
    border-radius: 0;
    padding: 6px 14px;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 0.8px;
    min-height: 16px;
}}
QFrame#UpdateBanner QPushButton:hover {{
    background: {GLOW};
    color: {BG};
}}
QFrame#UpdateBanner QPushButton#NotesToggle {{
    color: {TEXT_MID};
    border-color: {BORDER};
}}
QFrame#UpdateBanner QPushButton#NotesToggle:hover {{
    color: {TEXT};
    background: transparent;
    border-color: {GLOW_BORDER};
}}
QFrame#UpdateBanner QPushButton#DismissBtn {{
    color: {TEXT_DIM};
    border-color: {BORDER};
    min-width: 24px;
    padding: 6px 10px;
}}
QFrame#UpdateBanner QPushButton#DismissBtn:hover {{
    color: {RED};
    background: transparent;
    border-color: {RED};
}}
QFrame#UpdateBanner QPushButton#SkipBtn {{
    color: {TEXT_MID};
    border-color: {BORDER};
}}
QFrame#UpdateBanner QPushButton#SkipBtn:hover {{
    color: {TEXT};
    background: transparent;
    border-color: {BORDER};
}}
QFrame#UpdateBanner QTextEdit#NotesView {{
    background: {BG};
    color: {TEXT_MID};
    border: 1px solid {BORDER};
    border-radius: 0;
    font-family: {FONT_FAMILY};
    font-size: 11px;
    padding: 8px;
    selection-background-color: {GLOW_MID};
}}
QFrame#UpdateBanner QProgressBar {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 0;
    text-align: center;
    color: {TEXT_DIM};
    font-family: {FONT_FAMILY};
    font-size: 10px;
    max-height: 4px;
}}
QFrame#UpdateBanner QProgressBar::chunk {{
    background: {GLOW};
}}
"""


class UpdateBanner(QFrame):
    """Top-of-window banner for update notifications.

    All user actions are emitted as signals — the banner never decides
    whether to install or schedule; that's the service's job.
    """

    install_now_clicked = Signal(dict)
    schedule_clicked = Signal(dict)
    skip_clicked = Signal(str)
    cancel_schedule_clicked = Signal()
    dismiss_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("UpdateBanner")
        self.setStyleSheet(_BANNER_QSS)
        self.setVisible(False)

        self._manifest: Optional[dict[str, Any]] = None
        self._pending: Optional[dict[str, Any]] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        # Top row — headline + buttons
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 0, 0, 0)

        self._headline = QLabel("")
        self._headline.setObjectName("HeadlineLabel")
        self._headline.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self._headline, 1)

        self._notes_toggle = QPushButton("WHAT'S NEW")
        self._notes_toggle.setObjectName("NotesToggle")
        self._notes_toggle.setCursor(Qt.PointingHandCursor)
        self._notes_toggle.clicked.connect(self._toggle_notes)
        row.addWidget(self._notes_toggle)

        self._install_btn = QPushButton("INSTALL NOW")
        self._install_btn.setCursor(Qt.PointingHandCursor)
        self._install_btn.clicked.connect(self._on_install_clicked)
        row.addWidget(self._install_btn)

        self._schedule_btn = QPushButton("SCHEDULE")
        self._schedule_btn.setCursor(Qt.PointingHandCursor)
        self._schedule_btn.clicked.connect(self._on_schedule_clicked)
        row.addWidget(self._schedule_btn)

        self._skip_btn = QPushButton("SKIP")
        self._skip_btn.setObjectName("SkipBtn")
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        self._skip_btn.clicked.connect(self._on_skip_clicked)
        row.addWidget(self._skip_btn)

        self._cancel_schedule_btn = QPushButton("CANCEL SCHEDULE")
        self._cancel_schedule_btn.setObjectName("SkipBtn")
        self._cancel_schedule_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_schedule_btn.clicked.connect(self.cancel_schedule_clicked.emit)
        self._cancel_schedule_btn.setVisible(False)
        row.addWidget(self._cancel_schedule_btn)

        self._dismiss_btn = QPushButton("×")
        self._dismiss_btn.setObjectName("DismissBtn")
        self._dismiss_btn.setCursor(Qt.PointingHandCursor)
        self._dismiss_btn.clicked.connect(self._on_dismiss_clicked)
        row.addWidget(self._dismiss_btn)

        outer.addLayout(row)

        # Status row (hidden unless downloading or error)
        self._status_label = QLabel("")
        self._status_label.setObjectName("StatusLabel")
        self._status_label.setVisible(False)
        outer.addWidget(self._status_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        outer.addWidget(self._progress)

        # Collapsible release notes
        self._notes_view = QTextEdit()
        self._notes_view.setObjectName("NotesView")
        self._notes_view.setReadOnly(True)
        self._notes_view.setVisible(False)
        self._notes_view.setMaximumHeight(140)
        outer.addWidget(self._notes_view)

        # Live tick for the scheduled countdown
        self._tick = QTimer(self)
        self._tick.setInterval(30_000)  # every 30s
        self._tick.timeout.connect(self._refresh_scheduled_headline)

    # ─── public API ─────────────────────────────────────────────────────

    def show_update(self, manifest: dict[str, Any]) -> None:
        """Show the available-update state with the given manifest."""
        self._manifest = dict(manifest)
        self._pending = None
        self._tick.stop()

        self._set_available_state()
        self._headline.setText(self._available_headline(manifest))
        self._notes_view.setPlainText(str(manifest.get("notes") or "No release notes."))
        self._notes_view.setVisible(False)
        self._notes_toggle.setText("WHAT'S NEW")
        self._status_label.setVisible(False)
        self._progress.setVisible(False)
        self.setVisible(True)

    def show_scheduled(self, pending: dict[str, Any]) -> None:
        """Show the "install scheduled for X" state."""
        self._pending = dict(pending)
        # Keep the manifest around so "install now" still works.
        self._manifest = {
            "version": pending.get("version", ""),
            "download_url": pending.get("download_url", ""),
            "sha256": pending.get("sha256", ""),
            "notes": pending.get("notes", ""),
            "mandatory": pending.get("mandatory", False),
        }

        self._set_scheduled_state()
        self._refresh_scheduled_headline()
        self._notes_view.setPlainText(str(pending.get("notes") or "No release notes."))
        self._notes_view.setVisible(False)
        self._notes_toggle.setText("WHAT'S NEW")
        self._status_label.setVisible(False)
        self._progress.setVisible(False)
        self.setVisible(True)
        self._tick.start()

    def hide_banner(self) -> None:
        self._tick.stop()
        self._manifest = None
        self._pending = None
        self.setVisible(False)

    def set_downloading(self, percent: int) -> None:
        if not self.isVisible():
            return
        self._status_label.setText(f"downloading — {percent}%")
        self._status_label.setVisible(True)
        self._progress.setVisible(True)
        self._progress.setValue(max(0, min(100, percent)))
        self._install_btn.setEnabled(False)
        self._schedule_btn.setEnabled(False)

    def set_error(self, message: str) -> None:
        self._status_label.setText(f"error — {message}")
        self._status_label.setStyleSheet(f"color: {RED};")
        self._status_label.setVisible(True)
        self._progress.setVisible(False)
        self._install_btn.setEnabled(True)
        self._schedule_btn.setEnabled(True)

    def set_installing(self) -> None:
        self._status_label.setText("launching installer — blank will restart shortly")
        self._status_label.setStyleSheet(f"color: {GLOW};")
        self._status_label.setVisible(True)
        self._progress.setVisible(False)
        self._install_btn.setEnabled(False)
        self._schedule_btn.setEnabled(False)
        self._skip_btn.setEnabled(False)
        self._cancel_schedule_btn.setEnabled(False)

    # ─── internal state switching ───────────────────────────────────────

    def _set_available_state(self) -> None:
        self._install_btn.setEnabled(True)
        self._install_btn.setVisible(True)
        self._schedule_btn.setEnabled(True)
        self._schedule_btn.setVisible(True)
        self._skip_btn.setVisible(True)
        self._cancel_schedule_btn.setVisible(False)
        self._dismiss_btn.setVisible(True)
        self._status_label.setStyleSheet(f"color: {TEXT_DIM};")

    def _set_scheduled_state(self) -> None:
        self._install_btn.setEnabled(True)
        self._install_btn.setVisible(True)
        self._schedule_btn.setVisible(False)
        self._skip_btn.setVisible(False)
        self._cancel_schedule_btn.setVisible(True)
        self._cancel_schedule_btn.setEnabled(True)
        self._dismiss_btn.setVisible(False)
        self._status_label.setStyleSheet(f"color: {TEXT_DIM};")

    # ─── slot handlers ──────────────────────────────────────────────────

    def _toggle_notes(self) -> None:
        showing = not self._notes_view.isVisible()
        self._notes_view.setVisible(showing)
        self._notes_toggle.setText("HIDE NOTES" if showing else "WHAT'S NEW")

    def _on_install_clicked(self) -> None:
        if self._manifest is not None:
            self.install_now_clicked.emit(self._manifest)

    def _on_schedule_clicked(self) -> None:
        if self._manifest is not None:
            self.schedule_clicked.emit(self._manifest)

    def _on_skip_clicked(self) -> None:
        if self._manifest is not None:
            version = str(self._manifest.get("version") or "")
            if version:
                self.skip_clicked.emit(version)
        self.hide_banner()

    def _on_dismiss_clicked(self) -> None:
        self.dismiss_clicked.emit()
        self.hide_banner()

    # ─── helpers ────────────────────────────────────────────────────────

    def _available_headline(self, manifest: dict[str, Any]) -> str:
        version = str(manifest.get("version") or "")
        mandatory = bool(manifest.get("mandatory", False))
        prefix = "▲ blank"
        suffix = " (REQUIRED)" if mandatory else " AVAILABLE"
        return f"{prefix} {version}{suffix}"

    def _refresh_scheduled_headline(self) -> None:
        if self._pending is None:
            return
        version = str(self._pending.get("version") or "")
        scheduled_iso = str(self._pending.get("scheduled_at") or "")
        when_text = self._format_schedule(scheduled_iso)
        self._headline.setText(f"⏱ blank {version} SCHEDULED — {when_text}")

    @staticmethod
    def _format_schedule(scheduled_iso: str) -> str:
        if not scheduled_iso:
            return "time unknown"
        try:
            dt = datetime.fromisoformat(scheduled_iso)
        except ValueError:
            return scheduled_iso
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()
        now = datetime.now(local.tzinfo)
        delta = local - now
        mins = int(delta.total_seconds() // 60)
        if mins < 0:
            return "firing now"
        if mins < 60:
            return f"in {mins} min ({local.strftime('%H:%M')})"
        hrs = mins // 60
        if hrs < 24:
            return f"in {hrs}h ({local.strftime('%H:%M')})"
        days = hrs // 24
        return f"in {days}d ({local.strftime('%a %H:%M')})"
