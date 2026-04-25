"""Account settings dialog.

Lighter than the full dashboard: identity header, a compact analytics
summary (no payment figures), Trading 212 credential status, notification
toggles, a button to reset the onboarding walkthroughs, and the build
version. A link-style button jumps into the full Account Dashboard for
users who wandered here looking for payment info.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import __version__ as APP_VERSION
from desktop import tokens as T
from desktop.auth import api_call
from desktop.auth_state import auth_state
from desktop.avatars import render_avatar
from desktop.dialogs._base import BaseDialog
from desktop.onboarding_state import has_t212_credentials
from desktop.widgets.primitives.button import apply_variant


class _AnalyticsFetcher(QObject):
    done = Signal(dict)

    def run(self) -> None:
        self.done.emit(api_call("/api/me/analytics"))


class AccountSettingsDialog(BaseDialog):
    """Account settings — preferences + the at-a-glance analytics
    summary. Payment info lives in the full Account Dashboard."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            kicker="ACCOUNT",
            title="Settings",
            parent=parent,
        )
        self.setMinimumSize(620, 560)

        self._thread: Optional[QThread] = None
        self._fetcher: Optional[_AnalyticsFetcher] = None

        body = self.body_layout()
        body.addWidget(self._build_identity_row())
        body.addWidget(self._divider())
        body.addWidget(self._build_analytics_summary())
        body.addWidget(self._divider())
        body.addWidget(self._build_broker_row())
        body.addWidget(self._divider())
        body.addWidget(self._build_notifications())
        body.addWidget(self._divider())
        body.addWidget(self._build_maintenance_row())
        body.addStretch(1)
        body.addWidget(self._build_footer_meta())

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        body.addWidget(self._status)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.accept)
        self.add_footer_button(
            "OPEN DASHBOARD", variant="primary", slot=self._open_full_dashboard,
        )

        self._start_fetch()

    # ── Layout builders ────────────────────────────────────────────────

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {T.BORDER_0};")
        return line

    def _build_identity_row(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 6, 0, 14)
        row.setSpacing(16)

        state = auth_state()
        self._avatar_label = QLabel()
        self._avatar_label.setFixedSize(48, 48)
        self._avatar_label.setPixmap(
            render_avatar(state.avatar_id or 0, size=48)
        )
        row.addWidget(self._avatar_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._name_label = QLabel(state.name or "(no name)")
        self._name_label.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 16px; font-weight: 500;"
        )
        text_col.addWidget(self._name_label)

        self._email_label = QLabel(state.email or "")
        self._email_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px; letter-spacing: 1px;"
        )
        text_col.addWidget(self._email_label)
        row.addLayout(text_col, 1)
        return host

    def _build_analytics_summary(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(10)

        kicker = QLabel("ANALYTICS")
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)

        self._stat_labels: Dict[str, QLabel] = {}
        cells = [
            ("TOTAL TRADES", "total_trades"),
            ("WIN RATE", "win_rate"),
            ("TOTAL P/L", "pnl_all"),
            ("7D P/L", "pnl_7d"),
            ("30D P/L", "pnl_30d"),
            ("OPEN POSITIONS", "open_positions"),
        ]
        for idx, (label, key) in enumerate(cells):
            r, c = divmod(idx, 3)
            grid.addWidget(self._stat_cell(label, key), r, c)
        col.addLayout(grid)
        return host

    def _stat_cell(self, label: str, key: str) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)

        kicker = QLabel(label)
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        value = QLabel("—")
        value.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 15px; font-weight: 500;"
        )
        col.addWidget(value)
        self._stat_labels[key] = value
        return host

    def _build_broker_row(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(6)

        kicker = QLabel("TRADING 212 CONNECTION")
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        row = QHBoxLayout()
        row.setSpacing(12)

        has_keys = has_t212_credentials()
        status = QLabel("CONNECTED" if has_keys else "NOT CONNECTED")
        status.setStyleSheet(
            f"color: {T.ACCENT_HEX if has_keys else T.ALERT};"
            f" font-family: {T.FONT_MONO}; font-size: 12px;"
            f" letter-spacing: 2px;"
        )
        row.addWidget(status)
        row.addStretch(1)

        note = QLabel(
            "Manage keys in the live-mode onboarding. Paper mode "
            "doesn't need them."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 11px;"
        )
        col.addLayout(row)
        col.addWidget(note)
        return host

    def _build_notifications(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(8)

        kicker = QLabel("NOTIFICATIONS")
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        self._notify_trades = QCheckBox("Notify me when a trade fills")
        self._notify_trades.setStyleSheet(_checkbox_qss())
        self._notify_trades.setCursor(Qt.PointingHandCursor)
        self._notify_trades.setChecked(True)
        col.addWidget(self._notify_trades)

        self._notify_payment = QCheckBox(
            "Remind me the day before the monthly charge"
        )
        self._notify_payment.setStyleSheet(_checkbox_qss())
        self._notify_payment.setCursor(Qt.PointingHandCursor)
        self._notify_payment.setChecked(True)
        col.addWidget(self._notify_payment)

        self._notify_updates = QCheckBox("Notify me when an app update is ready")
        self._notify_updates.setStyleSheet(_checkbox_qss())
        self._notify_updates.setCursor(Qt.PointingHandCursor)
        self._notify_updates.setChecked(True)
        col.addWidget(self._notify_updates)

        tip = QLabel(
            "These preferences live on your machine — we don't send push "
            "notifications across the network yet."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 11px; padding-top: 4px;"
        )
        col.addWidget(tip)
        return host

    def _build_maintenance_row(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(6)

        kicker = QLabel("MAINTENANCE")
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        row = QHBoxLayout()
        row.setSpacing(10)

        reset_btn = QPushButton("RESET ONBOARDING")
        apply_variant(reset_btn, "ghost")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.setFixedHeight(30)
        reset_btn.clicked.connect(self._on_reset_onboarding)
        row.addWidget(reset_btn)

        row.addStretch(1)
        col.addLayout(row)

        tip = QLabel(
            "Clears the 'don't show again' flags so the paper and live "
            "walkthroughs re-appear next time you switch modes."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 11px;"
        )
        col.addWidget(tip)
        return host

    def _build_footer_meta(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 8, 0, 0)

        version_label = QLabel(f"BLANK  v{APP_VERSION}")
        version_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        row.addWidget(version_label)
        row.addStretch(1)
        return host

    # ── Fetch + populate ───────────────────────────────────────────────

    def _start_fetch(self) -> None:
        if self._thread is not None:
            return
        self._status.setText("LOADING ANALYTICS…")

        self._thread = QThread(self)
        self._fetcher = _AnalyticsFetcher()
        self._fetcher.moveToThread(self._thread)
        self._thread.started.connect(self._fetcher.run)
        self._fetcher.done.connect(self._on_fetched)
        self._fetcher.done.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_thread)
        self._thread.start()

    def _clear_thread(self) -> None:
        self._thread = None
        self._fetcher = None

    def _on_fetched(self, result: Dict[str, Any]) -> None:
        if not result.get("ok"):
            self._status.setText(
                f"server offline ({result.get('reason', 'unknown')})".upper()
            )
            return
        self._status.setText("")
        data = result.get("data") or {}
        for key, widget in self._stat_labels.items():
            widget.setText(_format_stat(key, data.get(key)))

    # ── Actions ────────────────────────────────────────────────────────

    def _on_reset_onboarding(self) -> None:
        from pathlib import Path

        from desktop.paths import user_data_dir

        try:
            state_path = user_data_dir() / "onboarding_state.json"
        except Exception:
            state_path = Path.home() / ".blank" / "onboarding_state.json"
        try:
            state_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            self._status.setText("COULDN'T CLEAR STATE FILE")
            return
        self._status.setText("ONBOARDING RESET — RELAUNCH WHEN READY")

    def _open_full_dashboard(self) -> None:
        self.accept()
        parent = self.parent()
        if parent is None:
            return
        handler = getattr(parent, "_open_account_dashboard", None)
        if callable(handler):
            handler()

    def run(self) -> None:
        _show = getattr(self, "exec")
        _show()


# ── Helpers ────────────────────────────────────────────────────────────

def _kicker_qss() -> str:
    return (
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px;"
    )


def _checkbox_qss() -> str:
    return (
        f"QCheckBox {{ color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
        f" font-size: 12px; spacing: 10px; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px;"
        f" border: 1px solid {T.BORDER_1}; background: transparent; }}"
        f"QCheckBox::indicator:hover {{ border-color: {T.FG_1_HEX}; }}"
        f"QCheckBox::indicator:checked {{ background: {T.ACCENT_HEX};"
        f" border-color: {T.ACCENT_HEX}; }}"
    )


def _format_stat(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key == "total_trades":
        return f"{int(value)}"
    if key == "win_rate":
        return f"{float(value):.1f}%"
    if key == "open_positions":
        return f"{int(value)}"
    if key in ("pnl_all", "pnl_7d", "pnl_30d"):
        v = float(value)
        sign = "+" if v > 0 else ""
        return f"{sign}£{v:,.2f}"
    if key == "last_snapshot_at":
        if not value:
            return "never"
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return "—"
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return str(value)
