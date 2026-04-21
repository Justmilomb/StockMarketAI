"""Agent activity panel — live feed of agent iterations and tool calls.

Owns the start / stop / kill buttons and the rolling log streamed from
``AgentRunner``. The panel is *dumb*: all lifecycle decisions live on
``MainWindow``, which owns the runner. The panel just:

* shows status from ``state.agent_running``,
* renders the tail from ``state.agent_journal_tail``,
* emits ``start_requested`` / ``stop_requested`` / ``kill_requested``
  when the user clicks the buttons.

Paper vs live is **not** shown here — the only paper-mode tell anywhere
in the app is the watermark painted over the chart. Everything else
looks identical in both modes.
"""
from __future__ import annotations

import html
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from desktop import tokens as T
from desktop.auth_state import auth_state
from desktop.widgets.primitives.button import apply_variant


# Assessor grade tags emitted by core/agent/runner.py as the leading
# token of a log line.
_REV_COLOURS = {
    "[rev:ok]": T.ACCENT_HEX,
    "[rev:warn]": T.WARN,
    "[rev:err]": T.ALERT,
}


class AgentLogPanel(QGroupBox):
    """Live tail of agent iterations + tool calls with lifecycle controls."""

    start_requested = Signal()
    stop_requested = Signal()
    kill_requested = Signal()

    def __init__(self, state: Any) -> None:
        super().__init__("AGENT")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 18, 4, 4)
        layout.setSpacing(6)

        control_row = QHBoxLayout()
        control_row.setSpacing(6)

        self._status_label = QLabel("AGENT OFFLINE")
        self._status_label.setStyleSheet(self._status_style(False))
        control_row.addWidget(self._status_label, 1)

        self._start_btn = QPushButton("START")
        apply_variant(self._start_btn, "primary")
        self._start_btn.setFixedWidth(72)
        self._start_btn.clicked.connect(self.start_requested.emit)
        control_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("STOP")
        apply_variant(self._stop_btn, "secondary")
        self._stop_btn.setFixedWidth(72)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._stop_btn.setEnabled(False)
        control_row.addWidget(self._stop_btn)

        self._kill_btn = QPushButton("KILL")
        apply_variant(self._kill_btn, "danger")
        self._kill_btn.setFixedWidth(60)
        self._kill_btn.clicked.connect(self.kill_requested.emit)
        self._kill_btn.setEnabled(False)
        control_row.addWidget(self._kill_btn)

        layout.addLayout(control_row)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            f"QTextEdit {{ background: {T.BG_0}; border: 1px solid {T.BORDER_0};"
            f" padding: 10px; font-family: {T.FONT_MONO}; font-size: 11px;"
            f" color: {T.FG_1_HEX}; }}"
        )
        self._log_view.document().setMaximumBlockCount(1000)
        layout.addWidget(self._log_view, 1)

        # Flip button state instantly when the user signs in / out.
        auth_state().changed.connect(lambda: self.refresh_view(state))
        self.refresh_view(state)

    @staticmethod
    def _status_style(running: bool) -> str:
        colour = T.ACCENT_HEX if running else T.FG_1_HEX
        return (
            f"color: {colour}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
            f" padding: 4px 6px;"
        )

    def _append_styled(self, line: str) -> None:
        text = str(line)
        colour = T.FG_1_HEX
        for tag, hex_colour in _REV_COLOURS.items():
            if text.startswith(tag):
                colour = hex_colour
                break
        escaped = html.escape(text)
        self._log_view.append(
            f'<span style="color:{colour};white-space:pre-wrap;">{escaped}</span>'
        )

    def append_line(self, line: str) -> None:
        self._append_styled(line)
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def refresh_view(self, state: Any) -> None:
        running = bool(getattr(state, "agent_running", False))
        signed_in = auth_state().is_signed_in
        if not signed_in:
            self._status_label.setText("SIGN IN TO USE THE AGENT")
        else:
            self._status_label.setText("AGENT RUNNING" if running else "AGENT OFFLINE")
        self._status_label.setStyleSheet(self._status_style(running and signed_in))
        # Start is only actionable when signed in AND not already running.
        self._start_btn.setEnabled(signed_in and not running)
        self._stop_btn.setEnabled(running)
        self._kill_btn.setEnabled(running)

        tail = getattr(state, "agent_journal_tail", None) or []
        if tail:
            self._log_view.clear()
            for line in tail:
                self._append_styled(line)
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        elif not self._log_view.toPlainText():
            if signed_in:
                self._log_view.setPlainText(
                    "Agent is offline. Click START or use Agent → Start Agent.\n"
                )
            else:
                self._log_view.setPlainText(
                    "Sign in to start your agent.\n"
                )
