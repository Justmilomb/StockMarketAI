"""First-run setup wizard — checks prerequisites and guides configuration."""
from __future__ import annotations

import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
from desktop.widgets.primitives.button import apply_variant


SETUP_MARKER = Path.home() / ".blank" / "setup_complete"

_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def _check_ai_engine() -> bool:
    try:
        from core.agent.paths import engine_available
        if engine_available():
            return True
    except Exception:
        pass
    try:
        subprocess.run(
            ["blank-ai", "--version"],
            capture_output=True, text=True, timeout=10,
            **_SUBPROCESS_FLAGS,
        )
        return True
    except Exception:
        return False


def _check_env_file() -> bool:
    return Path(".env").exists()


def _section_kicker(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 3px;"
    )
    return lbl


def _body_text(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
        f" font-size: 12px; line-height: 1.5;"
    )
    return lbl


def _field_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding-top: 4px;"
    )
    return lbl


class SetupWizard(QDialog):
    """First-run setup wizard on the terminal-dark palette."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedSize(560, 560)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0};"
            f" border: 1px solid {T.BORDER_1}; }}"
        )

        self._engine_ok = False
        self._env_ok = False

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 28)
        root.setSpacing(0)

        kicker = QLabel("FIRST-RUN SETUP")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 4px;"
        )
        root.addWidget(kicker)
        root.addSpacing(8)

        title = QLabel("blank")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 40px; font-weight: 500;"
            f" letter-spacing: -0.03em;"
        )
        root.addWidget(title)
        root.addSpacing(20)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {T.BORDER_0};")
        root.addWidget(rule)
        root.addSpacing(18)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._build_check_page()
        self._build_engine_page()
        self._build_env_page()
        self._build_done_page()

        self._run_checks()

    def _check_row(self, label_text: str) -> tuple[QWidget, QLabel]:
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        state = QLabel("…")
        state.setFixedWidth(36)
        state.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        name = QLabel(label_text)
        name.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 13px;"
        )
        h.addWidget(state)
        h.addWidget(name, 1)
        return row, state

    def _set_check_state(self, label: QLabel, ok: bool) -> None:
        label.setText("OK" if ok else "MISSING")
        colour = T.ACCENT_HEX if ok else T.ALERT
        label.setStyleSheet(
            f"color: {colour}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px; font-weight: 600;"
        )

    def _build_check_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(_section_kicker("CHECKING PREREQUISITES"))
        layout.addSpacing(8)

        engine_row, self._lbl_engine = self._check_row("advisor engine")
        layout.addWidget(engine_row)

        fp_row, self._lbl_feedparser = self._check_row("feedparser (news)")
        layout.addWidget(fp_row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        skip = QPushButton("SKIP")
        apply_variant(skip, "ghost")
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(self._finish)
        btn_row.addWidget(skip)

        recheck = QPushButton("RE-CHECK")
        recheck.setCursor(Qt.PointingHandCursor)
        recheck.clicked.connect(self._run_checks)
        btn_row.addWidget(recheck)

        cont = QPushButton("CONTINUE")
        apply_variant(cont, "primary")
        cont.setCursor(Qt.PointingHandCursor)
        cont.clicked.connect(self._on_check_continue)
        btn_row.addWidget(cont)

        layout.addLayout(btn_row)
        self._stack.addWidget(page)

    def _build_engine_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(_section_kicker("ADVISOR ENGINE SETUP"))
        layout.addSpacing(8)

        layout.addWidget(_body_text(
            "blank uses a local advisor engine to power signals, news sentiment, "
            "and the chat assistant. The engine ships with the installer. "
            "If this check is failing, the install may be corrupted.\n\n"
            "Try RE-CHECK. If it still fails, see help.blank.app/setup "
            "or reinstall.\n\n"
            "You can skip to use blank without advisor features (charts and broker "
            "still work)."
        ))

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        open_btn = QPushButton("OPEN HELP")
        apply_variant(open_btn, "ghost")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(
            lambda: webbrowser.open("https://help.blank.app/setup"),
        )
        btn_row.addWidget(open_btn)

        btn_row.addStretch(1)

        skip = QPushButton("SKIP (NO ADVISOR)")
        apply_variant(skip, "ghost")
        skip.setCursor(Qt.PointingHandCursor)
        skip.clicked.connect(self._on_engine_skip)
        btn_row.addWidget(skip)

        recheck = QPushButton("RE-CHECK")
        recheck.setCursor(Qt.PointingHandCursor)
        recheck.clicked.connect(self._recheck_engine)
        btn_row.addWidget(recheck)

        layout.addLayout(btn_row)
        self._stack.addWidget(page)

    def _build_env_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(_section_kicker("BROKER KEYS (OPTIONAL)"))
        layout.addSpacing(8)
        layout.addWidget(_body_text(
            "To trade live on Trading 212, paste your API key and secret below. "
            "Leave blank for paper mode — no real trades.\n\n"
            "You can find your key in Trading 212 → Settings → API section."
        ))

        layout.addSpacing(4)
        layout.addWidget(_field_label("T212 API KEY"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("paste key here")
        self._api_key_input.setStyleSheet(self._input_style())
        layout.addWidget(self._api_key_input)

        layout.addWidget(_field_label("T212 SECRET"))
        self._secret_key_input = QLineEdit()
        self._secret_key_input.setPlaceholderText("paste secret here")
        self._secret_key_input.setEchoMode(QLineEdit.Password)
        self._secret_key_input.setStyleSheet(self._input_style())
        layout.addWidget(self._secret_key_input)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)

        paper = QPushButton("USE PAPER")
        apply_variant(paper, "ghost")
        paper.setCursor(Qt.PointingHandCursor)
        paper.clicked.connect(self._go_done)
        btn_row.addWidget(paper)

        save = QPushButton("SAVE KEYS")
        apply_variant(save, "primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save_env)
        btn_row.addWidget(save)

        layout.addLayout(btn_row)
        self._stack.addWidget(page)

    @staticmethod
    def _input_style() -> str:
        return (
            f"QLineEdit {{ background: transparent; color: {T.FG_0};"
            f" border: none; border-bottom: 1px solid {T.BORDER_1};"
            f" padding: 8px 2px; font-family: {T.FONT_SANS}; font-size: 13px; }}"
            f"QLineEdit:focus {{ border-bottom-color: {T.ACCENT_HEX}; }}"
        )

    def _build_done_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(_section_kicker("READY"))
        layout.addSpacing(6)

        title = QLabel("Setup complete.")
        title.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 22px; font-weight: 500;"
            f" letter-spacing: -0.01em;"
        )
        layout.addWidget(title)

        layout.addSpacing(8)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS};"
            f" font-size: 12px; line-height: 1.7;"
        )
        layout.addWidget(self._summary)

        layout.addStretch()

        launch = QPushButton("LAUNCH BLANK")
        apply_variant(launch, "primary")
        launch.setCursor(Qt.PointingHandCursor)
        launch.clicked.connect(self._finish)
        layout.addWidget(launch)

        self._stack.addWidget(page)

    def _run_checks(self) -> None:
        self._engine_ok = _check_ai_engine()
        self._env_ok = _check_env_file()
        try:
            import feedparser  # noqa: F401
            fp_ok = True
        except ImportError:
            fp_ok = False
        self._set_check_state(self._lbl_engine, self._engine_ok)
        self._set_check_state(self._lbl_feedparser, fp_ok)

    def _on_check_continue(self) -> None:
        self._stack.setCurrentIndex(1 if not self._engine_ok else 2)

    def _recheck_engine(self) -> None:
        self._engine_ok = _check_ai_engine()
        if self._engine_ok:
            self._stack.setCurrentIndex(2)

    def _on_engine_skip(self) -> None:
        self._stack.setCurrentIndex(2)

    def _save_env(self) -> None:
        api_key = self._api_key_input.text().strip()
        secret_key = self._secret_key_input.text().strip()
        lines = []
        if api_key:
            lines.append(f"T212_API_KEY={api_key}")
        if secret_key:
            lines.append(f"T212_SECRET_KEY={secret_key}")
        if lines:
            Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self._env_ok = True
        self._go_done()

    def _go_done(self) -> None:
        engine_line = (
            f"<span style='color:{T.ACCENT_HEX};'>READY</span>"
            if self._engine_ok
            else f"<span style='color:{T.WARN};'>SKIPPED</span>"
        )
        env_line = (
            f"<span style='color:{T.ACCENT_HEX};'>CONFIGURED</span>"
            if self._env_ok
            else f"<span style='color:{T.FG_1_HEX};'>PAPER MODE</span>"
        )
        self._summary.setText(
            f"advisor engine &mdash; {engine_line}<br>"
            f"Broker keys &mdash; {env_line}"
        )
        self._stack.setCurrentIndex(3)

    def _finish(self) -> None:
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.write_text("1", encoding="utf-8")
        self.accept()

    @staticmethod
    def should_show() -> bool:
        return not SETUP_MARKER.exists()

    def run(self) -> bool:
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
