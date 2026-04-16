"""Agent activity panel — live feed of agent iterations and tool calls.

Phase 4 turns this into a real cockpit for the AI agent loop. The
panel owns the start/stop/kill buttons, the paper-mode indicator, and
the rolling log of tool calls + reasons that the ``AgentRunner``
streams back via Qt signals.

The panel is *dumb*: all lifecycle decisions live on ``MainWindow``,
which owns the runner. The panel just:

* shows status from ``state.agent_running``,
* renders the tail from ``state.agent_journal_tail``,
* emits ``start_requested`` / ``stop_requested`` / ``kill_requested``
  when the user clicks the buttons.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class AgentLogPanel(QGroupBox):
    """Live tail of agent iterations + tool calls with lifecycle controls."""

    start_requested = Signal()
    stop_requested = Signal()
    kill_requested = Signal()

    def __init__(self, state: Any) -> None:
        super().__init__("AGENT")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 16, 2, 2)
        layout.setSpacing(2)

        # Control row — status + buttons + paper indicator.
        control_row = QHBoxLayout()
        control_row.setSpacing(4)

        self._status_label = QLabel("agent offline")
        self._status_label.setStyleSheet(
            "color: #ff8c00; font-weight: bold; padding: 2px 6px;",
        )
        control_row.addWidget(self._status_label, 1)

        self._start_btn = QPushButton("Start")
        self._start_btn.setFixedWidth(60)
        self._start_btn.clicked.connect(self.start_requested.emit)
        control_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedWidth(60)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._stop_btn.setEnabled(False)
        control_row.addWidget(self._stop_btn)

        self._kill_btn = QPushButton("Kill")
        self._kill_btn.setFixedWidth(50)
        self._kill_btn.clicked.connect(self.kill_requested.emit)
        self._kill_btn.setEnabled(False)
        self._kill_btn.setStyleSheet(
            "QPushButton { color: #ff4040; font-weight: bold; }",
        )
        control_row.addWidget(self._kill_btn)

        self._paper_label = QLabel("PAPER")
        self._paper_label.setStyleSheet(
            "color: #ffd700; font-weight: bold; padding: 2px 6px;",
        )
        control_row.addWidget(self._paper_label)

        layout.addLayout(control_row)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setStyleSheet(
            "background-color: #000000; color: #00ff00; "
            "font-family: Consolas, monospace; font-size: 11px; "
            "border: 1px solid #333333;",
        )
        self._log_view.setMaximumBlockCount(1000)
        layout.addWidget(self._log_view, 1)

        self.refresh_view(state)

    def append_line(self, line: str) -> None:
        """Append a single log line without re-rendering the whole tail."""
        self._log_view.appendPlainText(line)
        sb = self._log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def refresh_view(self, state: Any) -> None:
        """Update status light + log tail from ``state``."""
        running = bool(getattr(state, "agent_running", False))
        if running:
            self._status_label.setText("agent running")
            self._status_label.setStyleSheet(
                "color: #00ff00; font-weight: bold; padding: 2px 6px;",
            )
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._kill_btn.setEnabled(True)
        else:
            self._status_label.setText("agent offline")
            self._status_label.setStyleSheet(
                "color: #ff8c00; font-weight: bold; padding: 2px 6px;",
            )
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._kill_btn.setEnabled(False)

        # Paper-mode indicator reads from state if present, else defaults
        # to True (belt-and-braces: the runner forces paper by default).
        paper_mode = bool(getattr(state, "agent_paper_mode", True))
        if paper_mode:
            self._paper_label.setText("PAPER")
            self._paper_label.setStyleSheet(
                "color: #ffd700; font-weight: bold; padding: 2px 6px;",
            )
        else:
            self._paper_label.setText("LIVE")
            self._paper_label.setStyleSheet(
                "color: #ff0000; font-weight: bold; padding: 2px 6px;",
            )

        tail = getattr(state, "agent_journal_tail", None) or []
        if tail:
            self._log_view.setPlainText("\n".join(str(line) for line in tail))
            sb = self._log_view.verticalScrollBar()
            sb.setValue(sb.maximum())
        elif not self._log_view.toPlainText():
            self._log_view.setPlainText(
                "Agent is offline. Click Start or use Agent → Start Agent.\n"
            )
