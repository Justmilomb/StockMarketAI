"""Chat panel — AI conversation with QTextEdit + QLineEdit."""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QLineEdit, QTextEdit, QVBoxLayout


_GRADE_COLORS = {"GREEN": "#00ff00", "RED": "#ff0000", "ORANGE": "#ff8c00", "AMBER": "#ffd700"}


def _markdown_to_html(text: str) -> str:
    """Convert basic markdown to HTML for AI responses."""
    import re
    lines = text.split("\n")
    html_lines: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Table separator row (|---|---|)
        if re.match(r'^\|[\s\-:]+\|', stripped):
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                html_lines.append('<table style="color:#cccccc;border-collapse:collapse;width:100%;margin:4px 0;">')
                in_table = True
            row_html = ""
            for cell in cells:
                cell = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', cell)
                # Colour grade keywords
                for grade, color in _GRADE_COLORS.items():
                    if grade in cell.upper():
                        cell = re.sub(
                            rf'({grade})',
                            rf'<span style="color:{color};font-weight:bold;">\1</span>',
                            cell, flags=re.IGNORECASE,
                        )
                row_html += f'<td style="padding:2px 6px;border-bottom:1px solid #333;">{cell}</td>'
            html_lines.append(f"<tr>{row_html}</tr>")
            continue

        if in_table:
            html_lines.append("</table>")
            in_table = False

        # Headers
        if stripped.startswith("## "):
            html_lines.append(f'<p style="color:#ff8c00;font-weight:bold;margin:6px 0 2px;">{stripped[3:]}</p>')
            continue
        if stripped.startswith("# "):
            html_lines.append(f'<p style="color:#ffd700;font-weight:bold;font-size:13px;margin:6px 0 2px;">{stripped[2:]}</p>')
            continue

        # Bold
        stripped = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', stripped)

        # Colour keywords in any line
        for grade, color in _GRADE_COLORS.items():
            stripped = re.sub(
                rf'\b({grade})\b',
                rf'<span style="color:{color};font-weight:bold;">\1</span>',
                stripped, flags=re.IGNORECASE,
            )

        # Horizontal rule
        if stripped == "---":
            html_lines.append('<hr style="border-color:#333;">')
            continue

        # Normal paragraph
        if stripped:
            html_lines.append(f'<p style="color:#cccccc;margin:2px 0;">{stripped}</p>')

    if in_table:
        html_lines.append("</table>")

    return "\n".join(html_lines)


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
            if role != "user":
                text = _markdown_to_html(text)
            if role == "user":
                html_parts.append(f'<p><span style="color:#00bfff;font-weight:bold;">YOU:</span> {text}</p>')
            else:
                html_parts.append(f'<p><span style="color:#ffb000;font-weight:bold;">AI:</span></p>{text}')
        self._messages.setHtml("".join(html_parts) if html_parts else '<p style="color:#888888;">No messages yet.</p>')
        # Scroll to bottom
        sb = self._messages.verticalScrollBar()
        sb.setValue(sb.maximum())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()
