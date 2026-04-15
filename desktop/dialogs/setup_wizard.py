"""First-run setup wizard -- checks prerequisites and guides configuration."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop.design import (
    APP_NAME_UPPER,
    BASE_QSS,
    BG,
    BORDER,
    BORDER_HOVER,
    GLOW,
    GLOW_BORDER,
    RED,
    SECONDARY_BTN_QSS,
    SURFACE,
    TEXT,
    TEXT_DIM,
    TEXT_MID,
    FONT_FAMILY,
)

SETUP_MARKER = Path.home() / ".blank" / "setup_complete"

# Subprocess flags -- hide console window on Windows
_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def _check_ai_engine() -> bool:
    """Return True if an AI engine is available to the app.

    Prefers the installer-bundled engine (``{app}/engine/``). Falls
    back to a system ``claude`` on PATH so dev installs without a
    built engine dir still pass the check. The wizard never asks the
    user to install anything — if both are missing it's a corrupted
    install, not a step the user can fix by typing.
    """
    try:
        from core.agent.paths import engine_available
        if engine_available():
            return True
    except Exception:
        pass

    try:
        subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=10,
            **_SUBPROCESS_FLAGS,
        )
        return True
    except Exception:
        return False


def _check_env_file() -> bool:
    """Return True if a .env file exists next to the running process."""
    return Path(".env").exists()


class SetupWizard(QDialog):
    """Multi-page first-run setup wizard matching the blank website aesthetic."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blank")
        self.setFixedSize(480, 520)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(BASE_QSS + f"""
            QDialog {{ border: 1px solid {BORDER}; }}
        """)

        self._engine_ok = False
        self._env_ok = False

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        # Title
        title = QLabel(APP_NAME_UPPER)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            color: {TEXT}; font-size: 36px; font-weight: 700;
            font-family: {FONT_FAMILY}; letter-spacing: -1px;
        """)
        root.addWidget(title)

        root.addSpacing(4)

        subtitle = QLabel("FIRST-RUN SETUP")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 3px;
        """)
        root.addWidget(subtitle)

        root.addSpacing(20)

        # Stacked pages
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._build_check_page()
        self._build_engine_page()
        self._build_env_page()
        self._build_done_page()

        # Run checks immediately
        self._run_checks()

    # -- Helpers ----------------------------------------------------------

    def _check_label_style(self, ok: bool) -> str:
        colour = GLOW if ok else RED
        return f"""
            color: {colour}; font-size: 13px; font-weight: 400;
            font-family: {FONT_FAMILY}; letter-spacing: 1px;
        """

    def _section_header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 12px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 2px;
        """)
        return lbl

    def _body_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 12px; font-weight: 300;
            font-family: {FONT_FAMILY}; line-height: 1.5;
        """)
        return lbl

    def _dim_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            color: {TEXT_DIM}; font-size: 11px; font-weight: 300;
            font-family: {FONT_FAMILY}; letter-spacing: 1px;
        """)
        return lbl

    # -- Page builders ----------------------------------------------------

    def _build_check_page(self) -> None:
        """Page 0: prerequisite checklist."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._section_header("CHECKING PREREQUISITES"))
        layout.addSpacing(12)

        self._lbl_engine = QLabel("[ -- ] AI engine")
        self._lbl_engine.setStyleSheet(self._check_label_style(True))
        layout.addWidget(self._lbl_engine)

        self._lbl_feedparser = QLabel("[ -- ] feedparser (news)")
        self._lbl_feedparser.setStyleSheet(self._check_label_style(True))
        layout.addWidget(self._lbl_feedparser)

        layout.addStretch()

        btn_row = QHBoxLayout()

        recheck = QPushButton("RE-CHECK")
        recheck.setCursor(Qt.PointingHandCursor)
        recheck.setStyleSheet(SECONDARY_BTN_QSS)
        recheck.clicked.connect(self._run_checks)
        btn_row.addWidget(recheck)

        cont = QPushButton("CONTINUE")
        cont.setCursor(Qt.PointingHandCursor)
        cont.clicked.connect(self._on_check_continue)
        btn_row.addWidget(cont)

        layout.addLayout(btn_row)

        layout.addSpacing(4)

        skip = QPushButton("SKIP SETUP")
        skip.setCursor(Qt.PointingHandCursor)
        skip.setStyleSheet(f"""
            QPushButton {{
                color: {TEXT_DIM}; border: none;
                font-size: 11px; font-weight: 300;
                font-family: {FONT_FAMILY}; letter-spacing: 1px;
                padding: 4px;
            }}
            QPushButton:hover {{ color: {TEXT_MID}; }}
        """)
        skip.clicked.connect(self._finish)
        layout.addWidget(skip)

        self._stack.addWidget(page)

    def _build_engine_page(self) -> None:
        """Page 1: AI engine setup guidance."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._section_header("AI ENGINE SETUP"))
        layout.addSpacing(8)

        info = self._body_label(
            "blank uses a local AI engine to power signals,\n"
            "news sentiment, and the chat assistant.\n\n"
            "The AI engine ships with the installer -- it should\n"
            "already be ready. If this check is failing, your\n"
            "install may be corrupted.\n\n"
            "Try clicking RE-CHECK once. If it still fails,\n"
            "see help.blank.app/setup or reinstall blank.\n\n"
            "You can SKIP to use blank without AI features\n"
            "(charts and broker still work).",
        )
        layout.addWidget(info)

        layout.addSpacing(8)

        open_btn = QPushButton("OPEN HELP PAGE")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(
            lambda: webbrowser.open("https://help.blank.app/setup"),
        )
        layout.addWidget(open_btn)

        layout.addStretch()

        btn_row = QHBoxLayout()

        recheck = QPushButton("RE-CHECK")
        recheck.setCursor(Qt.PointingHandCursor)
        recheck.setStyleSheet(SECONDARY_BTN_QSS)
        recheck.clicked.connect(self._recheck_engine)
        btn_row.addWidget(recheck)

        skip = QPushButton("SKIP (DISABLE AI)")
        skip.setCursor(Qt.PointingHandCursor)
        skip.setStyleSheet(SECONDARY_BTN_QSS)
        skip.clicked.connect(self._on_engine_skip)
        btn_row.addWidget(skip)

        layout.addLayout(btn_row)

        self._stack.addWidget(page)

    def _build_env_page(self) -> None:
        """Page 2: broker API key entry (optional)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._section_header("BROKER API KEYS (OPTIONAL)"))
        layout.addSpacing(8)

        info = self._body_label(
            "HOW TO GET YOUR TRADING 212 API KEY:\n\n"
            "1. Open Trading 212 (app or web)\n"
            "2. Go to Settings (gear icon)\n"
            "3. Scroll to the 'API' section\n"
            "4. Click 'Generate API Key'\n"
            "5. Copy the key and paste below\n\n"
            "Leave blank for paper mode (no real trades).\n"
            "You can always add keys later.",
        )
        layout.addWidget(info)

        layout.addSpacing(8)

        layout.addWidget(self._dim_label("T212 API KEY"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("paste key here")
        layout.addWidget(self._api_key_input)

        layout.addSpacing(4)

        layout.addWidget(self._dim_label("T212 SECRET KEY"))
        self._secret_key_input = QLineEdit()
        self._secret_key_input.setPlaceholderText("paste secret here")
        self._secret_key_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._secret_key_input)

        layout.addStretch()

        btn_row = QHBoxLayout()

        paper = QPushButton("USE PAPER MODE")
        paper.setCursor(Qt.PointingHandCursor)
        paper.setStyleSheet(SECONDARY_BTN_QSS)
        paper.clicked.connect(self._go_done)
        btn_row.addWidget(paper)

        save = QPushButton("SAVE KEYS")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save_env)
        btn_row.addWidget(save)

        layout.addLayout(btn_row)

        self._stack.addWidget(page)

    def _build_done_page(self) -> None:
        """Page 3: summary and launch."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        done_lbl = QLabel("SETUP COMPLETE")
        done_lbl.setAlignment(Qt.AlignCenter)
        done_lbl.setStyleSheet(f"""
            color: {GLOW}; font-size: 18px; font-weight: 400;
            font-family: {FONT_FAMILY}; letter-spacing: 2px;
        """)
        layout.addWidget(done_lbl)

        layout.addSpacing(16)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setAlignment(Qt.AlignCenter)
        self._summary.setStyleSheet(f"""
            color: {TEXT_MID}; font-size: 12px; font-weight: 300;
            font-family: {FONT_FAMILY};
        """)
        layout.addWidget(self._summary)

        layout.addStretch()

        launch = QPushButton("launch blank")
        launch.setCursor(Qt.PointingHandCursor)
        launch.clicked.connect(self._finish)
        layout.addWidget(launch)

        self._stack.addWidget(page)

    # -- Logic ------------------------------------------------------------

    def _run_checks(self) -> None:
        """Run all prerequisite checks and update labels."""
        self._engine_ok = _check_ai_engine()
        self._env_ok = _check_env_file()

        try:
            import feedparser  # noqa: F401
            fp_ok = True
        except ImportError:
            fp_ok = False

        self._lbl_engine.setText(f"[ {'OK' if self._engine_ok else 'MISSING'} ] AI engine")
        self._lbl_engine.setStyleSheet(self._check_label_style(self._engine_ok))

        self._lbl_feedparser.setText(f"[ {'OK' if fp_ok else 'MISSING'} ] feedparser (news)")
        self._lbl_feedparser.setStyleSheet(self._check_label_style(fp_ok))

    def _on_check_continue(self) -> None:
        """Navigate forward from the check page."""
        if not self._engine_ok:
            self._stack.setCurrentIndex(1)  # AI engine setup page
        else:
            self._stack.setCurrentIndex(2)  # Broker keys page

    def _recheck_engine(self) -> None:
        """Re-check the AI engine from the engine page."""
        self._engine_ok = _check_ai_engine()
        if self._engine_ok:
            self._stack.setCurrentIndex(2)  # Broker keys page

    def _on_engine_skip(self) -> None:
        """User chose to skip AI engine setup."""
        self._stack.setCurrentIndex(2)  # Broker keys page

    def _save_env(self) -> None:
        """Write .env file with broker keys."""
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
        """Show the done page with summary."""
        parts = []
        parts.append(f"AI engine: {'READY' if self._engine_ok else 'SKIPPED (AI disabled)'}")
        parts.append(f"Broker keys: {'CONFIGURED' if self._env_ok else 'PAPER MODE'}")
        self._summary.setText("\n".join(parts))
        self._stack.setCurrentIndex(3)

    def _finish(self) -> None:
        """Mark setup as complete and close."""
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.write_text("1", encoding="utf-8")
        self.accept()

    # -- Public API -------------------------------------------------------

    @staticmethod
    def should_show() -> bool:
        """Return True if setup wizard has not been completed yet."""
        return not SETUP_MARKER.exists()

    def run(self) -> bool:
        """Show the wizard. Returns True if completed, False if cancelled."""
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
