"""First-run setup wizard — checks prerequisites and guides configuration."""
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
)

SETUP_MARKER = Path.home() / ".blank" / "setup_complete"

# Subprocess flags — hide console window on Windows
_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW


def _check_claude_cli() -> bool:
    """Return True if the claude CLI is on PATH and responds."""
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


# ── Shared styles ────────────────────────────────────────────────────────

_DIALOG_STYLE = "QDialog { background-color: #000000; border: 1px solid #444444; }"
_TITLE_STYLE = (
    "color: #ffd700; font-size: 28px; font-weight: bold; "
    "font-family: Consolas, monospace; border: none; letter-spacing: 4px;"
)
_SUBTITLE_STYLE = (
    "color: #ff8c00; font-size: 11px; "
    "font-family: Consolas, monospace; border: none; letter-spacing: 2px;"
)
_CHECK_OK = "color: #00ff00; font-size: 13px; font-family: Consolas, monospace; border: none;"
_CHECK_FAIL = "color: #ff4444; font-size: 13px; font-family: Consolas, monospace; border: none;"
_TEXT_DIM = "color: #555555; font-size: 11px; font-family: Consolas, monospace; border: none;"

_BTN_STYLE = (
    "QPushButton {{ "
    "  background-color: #1a1a1a; color: {color}; "
    "  border: 1px solid #444444; "
    "  font-size: 13px; font-weight: bold; "
    "  font-family: Consolas, monospace; "
    "  padding: 10px; "
    "}} "
    "QPushButton:hover {{ background-color: #2a2a2a; border-color: {color}; }} "
    "QPushButton:pressed {{ background-color: #333333; }}"
)

_BTN_SUBTLE = (
    "QPushButton { background-color: transparent; color: #444444; "
    "  border: none; font-size: 11px; padding: 4px; "
    "  font-family: Consolas, monospace; } "
    "QPushButton:hover { color: #888888; }"
)

_INPUT_STYLE = (
    "QLineEdit { "
    "  background-color: #0a0a0a; color: #ffffff; "
    "  border: 1px solid #444444; padding: 8px; "
    "  font-size: 13px; font-family: Consolas, monospace; "
    "} "
    "QLineEdit:focus { border-color: #ff8c00; }"
)


class SetupWizard(QDialog):
    """Multi-page first-run setup wizard matching the Blank terminal aesthetic."""

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Blank — Setup")
        self.setFixedSize(480, 520)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(_DIALOG_STYLE)

        self._claude_ok = False
        self._env_ok = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(0)

        # Title (always visible)
        title = QLabel("BLANK")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(_TITLE_STYLE)
        root.addWidget(title)

        subtitle = QLabel("FIRST-RUN SETUP")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(_SUBTITLE_STYLE)
        root.addWidget(subtitle)

        root.addSpacing(16)

        # Stacked pages
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

        self._build_check_page()
        self._build_claude_page()
        self._build_env_page()
        self._build_done_page()

        # Run checks immediately
        self._run_checks()

    # ── Page builders ────────────────────────────────────────────────

    def _build_check_page(self) -> None:
        """Page 0: prerequisite checklist."""
        from PySide6.QtWidgets import QWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QLabel("CHECKING PREREQUISITES")
        header.setStyleSheet(_SUBTITLE_STYLE)
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        layout.addSpacing(12)

        self._lbl_claude = QLabel("[ -- ] Claude CLI")
        self._lbl_claude.setStyleSheet(_CHECK_OK)
        layout.addWidget(self._lbl_claude)

        self._lbl_env = QLabel("[ -- ] Environment file (.env)")
        self._lbl_env.setStyleSheet(_CHECK_OK)
        layout.addWidget(self._lbl_env)

        self._lbl_feedparser = QLabel("[ -- ] feedparser (news)")
        self._lbl_feedparser.setStyleSheet(_CHECK_OK)
        layout.addWidget(self._lbl_feedparser)

        layout.addStretch()

        btn_row = QHBoxLayout()
        recheck = QPushButton("RE-CHECK")
        recheck.setStyleSheet(_BTN_STYLE.format(color="#ffd700"))
        recheck.clicked.connect(self._run_checks)
        btn_row.addWidget(recheck)

        cont = QPushButton("CONTINUE")
        cont.setStyleSheet(_BTN_STYLE.format(color="#00ff00"))
        cont.clicked.connect(self._on_check_continue)
        btn_row.addWidget(cont)

        layout.addLayout(btn_row)

        skip = QPushButton("SKIP SETUP")
        skip.setStyleSheet(_BTN_SUBTLE)
        skip.clicked.connect(self._finish)
        layout.addWidget(skip)

        self._stack.addWidget(page)

    def _build_claude_page(self) -> None:
        """Page 1: Claude CLI install guidance."""
        from PySide6.QtWidgets import QWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QLabel("CLAUDE CLI REQUIRED")
        header.setStyleSheet(
            "color: #ff8c00; font-size: 14px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none;",
        )
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        layout.addSpacing(8)

        info = QLabel(
            "AI features (signals, news sentiment, chat) require\n"
            "the Claude CLI to be installed and authenticated.\n\n"
            "STEP 1: Install Node.js from nodejs.org (if needed)\n"
            "STEP 2: Open a terminal and run:\n"
            "           npm install -g @anthropic-ai/claude-code\n"
            "STEP 3: Run: claude login\n"
            "STEP 4: Follow the browser prompt to sign in\n"
            "STEP 5: Come back here and click RE-CHECK\n\n"
            "Uses YOUR existing Claude subscription.\n"
            "No additional API keys needed.",
        )
        info.setStyleSheet(
            "color: #888888; font-size: 12px; "
            "font-family: Consolas, monospace; border: none;",
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addSpacing(8)

        open_btn = QPushButton("OPEN INSTALL PAGE")
        open_btn.setStyleSheet(_BTN_STYLE.format(color="#00bfff"))
        open_btn.clicked.connect(
            lambda: webbrowser.open("https://docs.anthropic.com/en/docs/claude-cli"),
        )
        layout.addWidget(open_btn)

        layout.addStretch()

        btn_row = QHBoxLayout()
        recheck = QPushButton("RE-CHECK")
        recheck.setStyleSheet(_BTN_STYLE.format(color="#ffd700"))
        recheck.clicked.connect(self._recheck_claude)
        btn_row.addWidget(recheck)

        skip = QPushButton("SKIP (DISABLE AI)")
        skip.setStyleSheet(_BTN_STYLE.format(color="#888888"))
        skip.clicked.connect(self._on_claude_skip)
        btn_row.addWidget(skip)

        layout.addLayout(btn_row)

        self._stack.addWidget(page)

    def _build_env_page(self) -> None:
        """Page 2: broker API key entry (optional)."""
        from PySide6.QtWidgets import QWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QLabel("BROKER API KEYS (OPTIONAL)")
        header.setStyleSheet(
            "color: #ff8c00; font-size: 14px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none;",
        )
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        layout.addSpacing(8)

        info = QLabel(
            "HOW TO GET YOUR TRADING 212 API KEY:\n\n"
            "1. Open Trading 212 (app or web)\n"
            "2. Go to Settings (gear icon)\n"
            "3. Scroll to the 'API' section\n"
            "4. Click 'Generate API Key'\n"
            "5. Copy the key and paste below\n\n"
            "Leave blank for paper mode (no real trades).\n"
            "You can always add keys later.",
        )
        info.setStyleSheet(
            "color: #888888; font-size: 12px; "
            "font-family: Consolas, monospace; border: none;",
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addSpacing(8)

        lbl1 = QLabel("T212 API KEY")
        lbl1.setStyleSheet(_TEXT_DIM)
        layout.addWidget(lbl1)
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("paste key here")
        self._api_key_input.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self._api_key_input)

        layout.addSpacing(4)

        lbl2 = QLabel("T212 SECRET KEY")
        lbl2.setStyleSheet(_TEXT_DIM)
        layout.addWidget(lbl2)
        self._secret_key_input = QLineEdit()
        self._secret_key_input.setPlaceholderText("paste secret here")
        self._secret_key_input.setEchoMode(QLineEdit.Password)
        self._secret_key_input.setStyleSheet(_INPUT_STYLE)
        layout.addWidget(self._secret_key_input)

        layout.addStretch()

        btn_row = QHBoxLayout()
        paper = QPushButton("USE PAPER MODE")
        paper.setStyleSheet(_BTN_STYLE.format(color="#ffd700"))
        paper.clicked.connect(self._go_done)
        btn_row.addWidget(paper)

        save = QPushButton("SAVE KEYS")
        save.setStyleSheet(_BTN_STYLE.format(color="#00ff00"))
        save.clicked.connect(self._save_env)
        btn_row.addWidget(save)

        layout.addLayout(btn_row)

        self._stack.addWidget(page)

    def _build_done_page(self) -> None:
        """Page 3: summary and launch."""
        from PySide6.QtWidgets import QWidget

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QLabel("SETUP COMPLETE")
        header.setStyleSheet(
            "color: #00ff00; font-size: 18px; font-weight: bold; "
            "font-family: Consolas, monospace; border: none;",
        )
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        layout.addSpacing(12)

        self._summary = QLabel("")
        self._summary.setStyleSheet(
            "color: #888888; font-size: 12px; "
            "font-family: Consolas, monospace; border: none;",
        )
        self._summary.setWordWrap(True)
        self._summary.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._summary)

        layout.addStretch()

        launch = QPushButton("LAUNCH BLANK")
        launch.setStyleSheet(_BTN_STYLE.format(color="#00ff00"))
        launch.clicked.connect(self._finish)
        layout.addWidget(launch)

        self._stack.addWidget(page)

    # ── Logic ────────────────────────────────────────────────────────

    def _run_checks(self) -> None:
        """Run all prerequisite checks and update labels."""
        self._claude_ok = _check_claude_cli()
        self._env_ok = _check_env_file()

        try:
            import feedparser  # noqa: F401
            fp_ok = True
        except ImportError:
            fp_ok = False

        self._lbl_claude.setText(f"[ {'OK' if self._claude_ok else 'MISSING'} ] Claude CLI")
        self._lbl_claude.setStyleSheet(_CHECK_OK if self._claude_ok else _CHECK_FAIL)

        self._lbl_env.setText(f"[ {'OK' if self._env_ok else 'MISSING'} ] Environment file (.env)")
        self._lbl_env.setStyleSheet(_CHECK_OK if self._env_ok else _CHECK_FAIL)

        self._lbl_feedparser.setText(f"[ {'OK' if fp_ok else 'MISSING'} ] feedparser (news)")
        self._lbl_feedparser.setStyleSheet(_CHECK_OK if fp_ok else _CHECK_FAIL)

    def _on_check_continue(self) -> None:
        """Navigate forward from the check page."""
        if not self._claude_ok:
            self._stack.setCurrentIndex(1)  # Claude setup page
        elif not self._env_ok:
            self._stack.setCurrentIndex(2)  # Env page
        else:
            self._go_done()

    def _recheck_claude(self) -> None:
        """Re-check Claude CLI from the Claude page."""
        self._claude_ok = _check_claude_cli()
        if self._claude_ok:
            # Move to next issue or done
            if not self._env_ok:
                self._stack.setCurrentIndex(2)
            else:
                self._go_done()

    def _on_claude_skip(self) -> None:
        """User chose to skip Claude CLI setup."""
        if not self._env_ok:
            self._stack.setCurrentIndex(2)
        else:
            self._go_done()

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
        parts.append(f"Claude CLI: {'READY' if self._claude_ok else 'SKIPPED (AI disabled)'}")
        parts.append(f"Broker keys: {'CONFIGURED' if self._env_ok else 'PAPER MODE'}")
        self._summary.setText("\n".join(parts))
        self._stack.setCurrentIndex(3)

    def _finish(self) -> None:
        """Mark setup as complete and close."""
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.write_text("1", encoding="utf-8")
        self.accept()

    # ── Public API ───────────────────────────────────────────────────

    @staticmethod
    def should_show() -> bool:
        """Return True if setup wizard has not been completed yet."""
        return not SETUP_MARKER.exists()

    def run(self) -> bool:
        """Show the wizard. Returns True if completed, False if cancelled."""
        _show_modal = getattr(self, "exec")
        return _show_modal() == QDialog.Accepted
