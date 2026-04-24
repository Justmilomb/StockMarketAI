"""Account dashboard dialog.

In-app panel opened from the profile dropdown. Renders the signed-in
user's identity, trading analytics (total trades, win rate, P/L over
several windows, best/worst trade, open positions) and the weekly
performance-fee payment summary.

Data is fetched from the server's ``/api/me/dashboard`` endpoint in a
background thread so the UI never blocks — an offline server just means
the panel stays in its loading state with a "couldn't reach server"
status line; nothing crashes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.auth import api_call
from desktop.auth_state import auth_state
from desktop.avatars import render_avatar
from desktop.dialogs._base import BaseDialog
from desktop.widgets.primitives.button import apply_variant


class _DashboardFetcher(QObject):
    done = Signal(dict)

    def run(self) -> None:
        self.done.emit(api_call("/api/me/dashboard"))


class AccountDashboardDialog(BaseDialog):
    """Signed-in user's account dashboard — analytics + payment."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(
            kicker="ACCOUNT",
            title="Dashboard",
            parent=parent,
        )
        self.setMinimumSize(680, 600)

        self._thread: Optional[QThread] = None
        self._fetcher: Optional[_DashboardFetcher] = None
        self._window_buttons: Dict[str, QPushButton] = {}
        self._active_window = "pnl_all"
        self._analytics: Dict[str, Any] = {}

        body = self.body_layout()
        body.addWidget(self._build_identity_row())
        body.addWidget(self._divider())
        body.addWidget(self._build_pnl_section())
        body.addWidget(self._divider())
        body.addWidget(self._build_stats_grid())
        body.addWidget(self._divider())
        body.addWidget(self._build_payment_section())
        body.addStretch(1)

        self._status = QLabel("loading…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        body.addWidget(self._status)

        self.add_footer_button("CLOSE", variant="ghost", slot=self.accept)
        self._refresh_btn = self.add_footer_button(
            "REFRESH", variant="primary", slot=self._start_fetch,
        )

        self._start_fetch()

    # ── Scaffolding ────────────────────────────────────────────────────

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
        self._avatar_label.setFixedSize(64, 64)
        self._avatar_label.setPixmap(
            render_avatar(state.avatar_id or 0, size=64)
        )
        row.addWidget(self._avatar_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._name_label = QLabel(state.name or "(no name)")
        self._name_label.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 18px; font-weight: 500;"
        )
        text_col.addWidget(self._name_label)

        self._email_label = QLabel(state.email or "")
        self._email_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px; letter-spacing: 1px;"
        )
        text_col.addWidget(self._email_label)

        self._account_status_label = QLabel("STATUS —")
        self._account_status_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px; padding-top: 4px;"
        )
        text_col.addWidget(self._account_status_label)

        row.addLayout(text_col, 1)
        return host

    def _build_pnl_section(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(10)

        kicker = QLabel("PROFIT / LOSS")
        kicker.setStyleSheet(_kicker_qss())
        col.addWidget(kicker)

        self._pnl_value = QLabel("—")
        self._pnl_value.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 28px; font-weight: 500;"
        )
        col.addWidget(self._pnl_value)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(4)
        for label, key in (
            ("TODAY", "pnl_today"),
            ("7D", "pnl_7d"),
            ("30D", "pnl_30d"),
            ("ALL", "pnl_all"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(26)
            btn.setStyleSheet(_toggle_qss())
            btn.clicked.connect(lambda _=False, k=key: self._set_pnl_window(k))
            toggle_row.addWidget(btn)
            self._window_buttons[key] = btn
        toggle_row.addStretch(1)
        col.addLayout(toggle_row)

        self._window_buttons["pnl_all"].setChecked(True)
        return host

    def _build_stats_grid(self) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 12, 0, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(14)

        self._stat_labels: Dict[str, QLabel] = {}
        cells = [
            ("TOTAL TRADES", "total_trades"),
            ("WIN RATE", "win_rate"),
            ("OPEN POSITIONS", "open_positions"),
            ("BEST TRADE", "best_trade"),
            ("WORST TRADE", "worst_trade"),
            ("LAST SNAPSHOT", "last_snapshot_at"),
        ]
        for idx, (label, key) in enumerate(cells):
            r, c = divmod(idx, 3)
            grid.addWidget(self._stat_cell(label, key), r, c)
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
        value.setWordWrap(True)
        col.addWidget(value)
        self._stat_labels[key] = value
        return host

    def _build_payment_section(self) -> QWidget:
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 12, 0, 4)
        col.setSpacing(10)

        self._payment_kicker = QLabel("PERFORMANCE FEE")
        self._payment_kicker.setStyleSheet(_kicker_qss())
        col.addWidget(self._payment_kicker)

        amt_row = QHBoxLayout()
        amt_row.setSpacing(18)

        amount_col = QVBoxLayout()
        amount_col.setSpacing(2)
        al = QLabel("DUE THIS WEEK")
        al.setStyleSheet(_field_qss())
        amount_col.addWidget(al)
        self._amount_due = QLabel("£0.00")
        self._amount_due.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
        )
        amount_col.addWidget(self._amount_due)
        amt_row.addLayout(amount_col)

        date_col = QVBoxLayout()
        date_col.setSpacing(2)
        dl = QLabel("NEXT CHARGE")
        dl.setStyleSheet(_field_qss())
        date_col.addWidget(dl)
        self._next_payment = QLabel("—")
        self._next_payment.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 15px;"
        )
        date_col.addWidget(self._next_payment)
        amt_row.addLayout(date_col)

        card_col = QVBoxLayout()
        card_col.setSpacing(2)
        cl = QLabel("CARD ON FILE")
        cl.setStyleSheet(_field_qss())
        card_col.addWidget(cl)
        self._card_label = QLabel("—")
        self._card_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 12px; letter-spacing: 2px;"
        )
        card_col.addWidget(self._card_label)
        amt_row.addLayout(card_col)

        amt_row.addStretch(1)

        self._pay_now_btn = QPushButton("PAY NOW")
        apply_variant(self._pay_now_btn, "primary")
        self._pay_now_btn.setCursor(Qt.PointingHandCursor)
        self._pay_now_btn.setFixedHeight(32)
        self._pay_now_btn.setEnabled(False)
        self._pay_now_btn.setToolTip(
            "automatic — your card is charged every Monday at 09:00 UTC"
        )
        amt_row.addWidget(self._pay_now_btn)

        col.addLayout(amt_row)

        note = QLabel(
            "Charged automatically every Monday at 09:00 UTC. If a week "
            "ends at a loss, nothing is charged."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 11px;"
        )
        col.addWidget(note)
        return host

    # ── Fetch + populate ───────────────────────────────────────────────

    def _start_fetch(self) -> None:
        if self._thread is not None:
            return
        self._status.setText("LOADING…")
        self._refresh_btn.setEnabled(False)

        self._thread = QThread(self)
        self._fetcher = _DashboardFetcher()
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
        self._refresh_btn.setEnabled(True)
        if not result.get("ok"):
            self._status.setText(
                f"couldn't reach server ({result.get('reason', 'unknown')})".upper()
            )
            return
        data = result.get("data") or {}
        self._apply_payload(data)
        self._status.setText("")

    def _apply_payload(self, data: Dict[str, Any]) -> None:
        user = data.get("user") or {}
        analytics = data.get("analytics") or {}
        payment = data.get("payment") or {}

        name = user.get("full_name") or user.get("name") or "(no name)"
        self._name_label.setText(name)
        self._email_label.setText(user.get("email") or "")
        avatar_id = int(user.get("avatar_id") or 0)
        self._avatar_label.setPixmap(render_avatar(avatar_id, size=64))
        status = (user.get("status") or "").upper() or "—"
        self._account_status_label.setText(f"STATUS {status}")

        self._analytics = analytics
        self._render_window()

        for key, widget in self._stat_labels.items():
            widget.setText(_format_stat(key, analytics.get(key)))

        currency = payment.get("currency") or "GBP"
        symbol = _currency_symbol(currency)
        amount = float(payment.get("amount_due") or 0.0)
        self._amount_due.setText(f"{symbol}{amount:,.2f}")
        self._next_payment.setText(_format_next_payment(payment.get("next_payment_at")))
        last4 = payment.get("card_last4") or ""
        if last4:
            self._card_label.setText(f"•••• {last4}")
        else:
            self._card_label.setText("not set")

        # Plan-aware kicker — server tells us the rate that applies this
        # week, including the tier discount on Starter when profit clears
        # the threshold. Falls back to a plain label when the server is
        # offline / running an older build.
        rate = payment.get("fee_rate_pct")
        if rate is None:
            self._payment_kicker.setText("PERFORMANCE FEE")
        else:
            rate_str = f"{rate:g}".rstrip("0").rstrip(".") if isinstance(rate, float) else str(rate)
            self._payment_kicker.setText(
                f"PERFORMANCE FEE — {rate_str}% OF WEEKLY PROFIT"
            )

    def _set_pnl_window(self, key: str) -> None:
        self._active_window = key
        for k, btn in self._window_buttons.items():
            btn.setChecked(k == key)
        self._render_window()

    def _render_window(self) -> None:
        value = float(self._analytics.get(self._active_window) or 0.0)
        colour = T.ACCENT_HEX if value >= 0 else T.ALERT
        symbol = "£"
        sign = "+" if value > 0 else ""
        self._pnl_value.setText(f"{sign}{symbol}{value:,.2f}")
        self._pnl_value.setStyleSheet(
            f"color: {colour}; font-family: {T.FONT_SANS};"
            f" font-size: 28px; font-weight: 500;"
        )

    def run(self) -> None:
        _show = getattr(self, "exec")
        _show()


# ── Formatters / style helpers ─────────────────────────────────────────

def _kicker_qss() -> str:
    return (
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px;"
    )


def _field_qss() -> str:
    return (
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 9px; letter-spacing: 2px;"
    )


def _toggle_qss() -> str:
    return (
        f"QPushButton {{ background: transparent;"
        f" border: 1px solid {T.BORDER_1}; color: {T.FG_1_HEX};"
        f" font-family: {T.FONT_MONO}; font-size: 10px;"
        f" letter-spacing: 2px; padding: 4px 12px; }}"
        f"QPushButton:hover {{ color: {T.FG_0}; border-color: {T.FG_1_HEX}; }}"
        f"QPushButton:checked {{ color: {T.ACCENT_HEX};"
        f" border-color: {T.ACCENT_HEX}; }}"
    )


def _currency_symbol(code: str) -> str:
    return {"GBP": "£", "USD": "$", "EUR": "€"}.get(code.upper(), "")


def _format_stat(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key == "total_trades":
        return f"{int(value)}"
    if key == "win_rate":
        return f"{float(value):.1f}%"
    if key == "open_positions":
        return f"{int(value)}"
    if key in ("best_trade", "worst_trade"):
        if not isinstance(value, dict):
            return "—"
        ticker = value.get("ticker") or "—"
        profit = float(value.get("profit") or 0.0)
        sign = "+" if profit > 0 else ""
        return f"{ticker}  {sign}£{profit:,.2f}"
    if key == "last_snapshot_at":
        return _format_timestamp(value)
    return str(value)


def _format_timestamp(raw: Any) -> str:
    if not raw:
        return "never"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _format_next_payment(raw: Any) -> str:
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return "—"
    return dt.strftime("%a %d %b %H:%M UTC")
