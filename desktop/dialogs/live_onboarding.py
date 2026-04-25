"""Live-mode onboarding — mandatory T212 key setup walkthrough.

Three steps, stacked in a ``QStackedWidget``:

1. **Welcome** — one screen on what live mode does, what the risks are,
   and what we're about to ask for.
2. **T212 key setup** — inline instructions for where to find the key,
   two input fields, a TEST KEY button, and a CONTINUE button that is
   only enabled after a successful validation call. Skipped entirely if
   ``T212_API_KEY`` + ``T212_SECRET_KEY`` are already present.
3. **Ready** — confirmation + "Don't show again" checkbox + CTA.

The T212 step is mandatory: there is no SKIP affordance. The user can
CANCEL the dialog, which rejects the onboarding — the caller in
``desktop.main`` interprets that as "drop back to paper mode or quit".

Validation hits ``/api/v0/equity/account/cash`` through
:func:`desktop.onboarding_state.validate_t212_credentials`.
"""
from __future__ import annotations

import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T
from desktop.onboarding_state import (
    has_t212_credentials,
    mark_live_done,
    save_t212_credentials,
    validate_t212_credentials,
)
from desktop.widgets.primitives.button import apply_variant


_T212_HELP_URL = "https://helpcentre.trading212.com/hc/en-us/articles/14584770928157"


# ─── Off-thread key validation ───────────────────────────────────────

class _ValidatorThread(QThread):
    """Runs the T212 validation HTTP call off the UI thread."""

    finished_ok = Signal(str)
    finished_fail = Signal(str)

    def __init__(self, api_key: str, secret_key: str) -> None:
        super().__init__()
        self._api_key = api_key
        self._secret_key = secret_key

    def run(self) -> None:
        ok, message = validate_t212_credentials(self._api_key, self._secret_key)
        if ok:
            self.finished_ok.emit(message)
        else:
            self.finished_fail.emit(message)


# ─── Main dialog ─────────────────────────────────────────────────────

class LiveOnboardingDialog(QDialog):
    """Mandatory walkthrough shown before a live-mode session starts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank — live mode")
        self.setFixedSize(640, 620)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )

        self._t212_skipped = has_t212_credentials()
        self._key_validated = self._t212_skipped
        self._validator: Optional[_ValidatorThread] = None
        self._dont_show_cb = QCheckBox("Don't show this again")
        self._dont_show_cb.setStyleSheet(_checkbox_qss())
        self._dont_show_cb.setCursor(Qt.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 24)
        root.setSpacing(0)

        kicker = QLabel("LIVE MODE SETUP")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.ALERT}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 4px;"
        )
        root.addWidget(kicker)

        root.addSpacing(6)

        self._step_indicator = QLabel("")
        self._step_indicator.setAlignment(Qt.AlignCenter)
        self._step_indicator.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px;"
        )
        root.addWidget(self._step_indicator)

        root.addSpacing(14)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)

        root.addSpacing(18)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._build_welcome_page()
        self._build_key_page()
        self._build_ready_page()

        self._total_steps = 2 if self._t212_skipped else 3
        self._set_step_indicator(1)

    # ─── Page builders ───────────────────────────────────────────────

    def _build_welcome_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Real money. Real orders. Read this first.")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em;"
        )
        layout.addWidget(title)

        bullets = [
            ("YOUR BROKER",
             "Live mode places real orders on your Trading 212 account. "
             "You need a Trading 212 API key — we'll set that up next."),
            ("YOU ARE IN CONTROL",
             "Your advisor only trades while you have START pressed. "
             "Press STOP at any time and it stops immediately."),
            ("KEEP A WATCH",
             "Your advisor's judgement is imperfect. Don't leave it "
             "running unattended with more money than you're willing "
             "to lose."),
        ]
        for label, text in bullets:
            layout.addWidget(_bullet_row(label, text))

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        cancel = QPushButton("CANCEL")
        apply_variant(cancel, "ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)

        button_row.addStretch(1)

        cont = QPushButton("CONTINUE")
        apply_variant(cont, "primary")
        cont.setCursor(Qt.PointingHandCursor)
        cont.setFixedHeight(34)
        cont.clicked.connect(self._advance_from_welcome)
        button_row.addWidget(cont)

        layout.addLayout(button_row)
        self._stack.addWidget(page)

    def _build_key_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = QLabel("Paste your Trading 212 API key.")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 20px; font-weight: 500;"
            f" letter-spacing: -0.01em;"
        )
        layout.addWidget(title)

        steps_label = QLabel("HOW TO GET YOUR KEY")
        steps_label.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px; padding-top: 4px;"
        )
        layout.addWidget(steps_label)

        instructions = QLabel(
            "1. Open Trading 212 on desktop or mobile.\n"
            "2. Go to Settings → API (Developer).\n"
            "3. Tap \"Generate new key\". Tick the scopes you want the "
            "advisor to have — at minimum: metadata, portfolio, and orders.\n"
            "4. Copy the key pair Trading 212 shows you and paste it below."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px; line-height: 1.6;"
        )
        layout.addWidget(instructions)

        help_row = QHBoxLayout()
        help_link = QPushButton("OPEN T212 HELP")
        apply_variant(help_link, "ghost")
        help_link.setCursor(Qt.PointingHandCursor)
        help_link.setFixedHeight(28)
        help_link.clicked.connect(lambda: webbrowser.open(_T212_HELP_URL))
        help_row.addWidget(help_link)
        help_row.addStretch(1)
        layout.addLayout(help_row)

        layout.addSpacing(6)

        layout.addWidget(_field_label("T212 API KEY"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("paste key here")
        self._api_key_input.setStyleSheet(_input_qss())
        self._api_key_input.textChanged.connect(self._on_key_edited)
        layout.addWidget(self._api_key_input)

        layout.addWidget(_field_label("T212 SECRET"))
        self._secret_key_input = QLineEdit()
        self._secret_key_input.setPlaceholderText("paste secret here")
        self._secret_key_input.setEchoMode(QLineEdit.Password)
        self._secret_key_input.setStyleSheet(_input_qss())
        self._secret_key_input.textChanged.connect(self._on_key_edited)
        layout.addWidget(self._secret_key_input)

        self._key_status = QLabel("")
        self._key_status.setWordWrap(True)
        self._key_status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 1px; padding-top: 8px;"
        )
        layout.addWidget(self._key_status)

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        cancel = QPushButton("CANCEL")
        apply_variant(cancel, "ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setFixedHeight(34)
        cancel.clicked.connect(self.reject)
        button_row.addWidget(cancel)

        button_row.addStretch(1)

        self._test_btn = QPushButton("TEST KEY")
        apply_variant(self._test_btn, "secondary")
        self._test_btn.setCursor(Qt.PointingHandCursor)
        self._test_btn.setFixedHeight(34)
        self._test_btn.clicked.connect(self._start_validation)
        button_row.addWidget(self._test_btn)

        self._continue_btn = QPushButton("CONTINUE")
        apply_variant(self._continue_btn, "primary")
        self._continue_btn.setCursor(Qt.PointingHandCursor)
        self._continue_btn.setFixedHeight(34)
        self._continue_btn.setEnabled(False)
        self._continue_btn.clicked.connect(self._advance_from_key_page)
        button_row.addWidget(self._continue_btn)

        layout.addLayout(button_row)
        self._stack.addWidget(page)

    def _build_ready_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("You're set up for live trading.")
        title.setWordWrap(True)
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em;"
        )
        layout.addWidget(title)

        blurb = QLabel(
            "Click START in the AGENT panel when you want your advisor "
            "to start looking for trades. It will respect the position "
            "and drawdown limits in your config. Press STOP to halt it "
            "immediately."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 13px; line-height: 1.55;"
        )
        layout.addWidget(blurb)

        reminder = QLabel(
            "You can switch back to PAPER mode at any time from the "
            "app's mode menu — nothing on this setup locks you into live."
        )
        reminder.setWordWrap(True)
        reminder.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px; line-height: 1.5;"
        )
        layout.addWidget(reminder)

        layout.addStretch(1)

        check_row = QHBoxLayout()
        check_row.addWidget(self._dont_show_cb)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)

        finish = QPushButton("START LIVE TRADING")
        apply_variant(finish, "primary")
        finish.setCursor(Qt.PointingHandCursor)
        finish.setFixedHeight(36)
        finish.clicked.connect(self._finish)
        button_row.addWidget(finish)

        layout.addLayout(button_row)
        self._stack.addWidget(page)

    # ─── Navigation ──────────────────────────────────────────────────

    def _advance_from_welcome(self) -> None:
        if self._t212_skipped:
            self._stack.setCurrentIndex(2)
            self._set_step_indicator(2)
        else:
            self._stack.setCurrentIndex(1)
            self._set_step_indicator(2)

    def _advance_from_key_page(self) -> None:
        if not self._key_validated:
            return
        save_t212_credentials(
            self._api_key_input.text(),
            self._secret_key_input.text(),
        )
        self._stack.setCurrentIndex(2)
        self._set_step_indicator(3)

    def _finish(self) -> None:
        mark_live_done(self._dont_show_cb.isChecked())
        self.accept()

    def _set_step_indicator(self, step: int) -> None:
        self._step_indicator.setText(f"STEP {step} OF {self._total_steps}")

    # ─── Key validation ──────────────────────────────────────────────

    def _on_key_edited(self) -> None:
        self._key_validated = False
        self._continue_btn.setEnabled(False)
        self._set_key_status("", tone="dim")

    def _start_validation(self) -> None:
        api = self._api_key_input.text().strip()
        secret = self._secret_key_input.text().strip()
        if not api or not secret:
            self._set_key_status(
                "Enter both the API key and the secret before testing.",
                tone="warn",
            )
            return
        self._test_btn.setEnabled(False)
        self._continue_btn.setEnabled(False)
        self._set_key_status("Checking key with Trading 212…", tone="dim")

        self._validator = _ValidatorThread(api, secret)
        self._validator.finished_ok.connect(self._on_validation_ok)
        self._validator.finished_fail.connect(self._on_validation_fail)
        self._validator.finished.connect(self._on_validator_finished)
        self._validator.start()

    def _on_validation_ok(self, message: str) -> None:
        self._key_validated = True
        self._continue_btn.setEnabled(True)
        self._set_key_status(message, tone="ok")

    def _on_validation_fail(self, message: str) -> None:
        self._key_validated = False
        self._continue_btn.setEnabled(False)
        self._set_key_status(message, tone="error")

    def _on_validator_finished(self) -> None:
        self._test_btn.setEnabled(True)
        if self._validator is not None:
            self._validator.deleteLater()
            self._validator = None

    def _set_key_status(self, message: str, *, tone: str) -> None:
        palette = {
            "dim": T.FG_2_HEX,
            "ok": T.ACCENT_HEX,
            "error": T.ALERT,
            "warn": T.WARN,
        }
        colour = palette.get(tone, T.FG_2_HEX)
        self._key_status.setStyleSheet(
            f"color: {colour}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 1px; padding-top: 8px;"
        )
        self._key_status.setText(message)

    # ─── Lifecycle ───────────────────────────────────────────────────

    def run(self) -> bool:
        """Show the dialog modally. Returns True on completion, False if cancelled."""
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted


# ─── Helpers ─────────────────────────────────────────────────────────

def _bullet_row(label: str, text: str) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)

    kicker = QLabel(label)
    kicker.setFixedWidth(130)
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


def _field_label(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet(
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding-top: 4px;"
    )
    return label


def _input_qss() -> str:
    return (
        f"QLineEdit {{ background: transparent; color: {T.FG_0};"
        f" border: none; border-bottom: 1px solid {T.BORDER_1};"
        f" padding: 8px 2px; font-family: {T.FONT_SANS}; font-size: 13px; }}"
        f"QLineEdit:focus {{ border-bottom-color: {T.ACCENT_HEX}; }}"
    )


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
