"""Chat panel — AI conversation with QTextEdit + QLineEdit."""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QLineEdit, QTextEdit, QVBoxLayout


class ChatPanel(QGroupBox):
    message_submitted = Signal(str)

    def __init__(self, state: Any) -> None:
        super().__init__("CHAT")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 16, 4, 4)

        self._messages = QTextEdit()
        self._messages.setReadOnly(True)
        layout.addWidget(self._messages, 1)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message...")
        self._input.returnPressed.connect(self._on_submit)
        layout.addWidget(self._input)
        self.refresh_view(state)

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self.message_submitted.emit(text)

    def refresh_view(self, state: Any) -> None:
        history = state.chat_history[-20:] if state.chat_history else []
        html_parts = []
        for msg in history:
            role = msg.get("role", "user")
            text = msg.get("text", "")
            # Escape HTML in text
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if role == "user":
                html_parts.append(f'<p><span style="color:#00bfff;font-weight:bold;">YOU:</span> {text}</p>')
            else:
                html_parts.append(f'<p><span style="color:#ffb000;font-weight:bold;">AI:</span> {text}</p>')
        self._messages.setHtml("".join(html_parts) if html_parts else '<p style="color:#888888;">No messages yet.</p>')
        # Scroll to bottom
        sb = self._messages.verticalScrollBar()
        sb.setValue(sb.maximum())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()
