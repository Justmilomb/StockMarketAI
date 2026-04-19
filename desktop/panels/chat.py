"""Chat panel — AI conversation with QTextEdit + QLineEdit.

Uses the website palette: plain white body on black, green accent for
the "you" label, a subtle dim-white label on agent replies. Tables
render with hairline white-alpha borders, no coloured grade tags.
"""
from __future__ import annotations
from typing import Any
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QLineEdit, QTextEdit, QVBoxLayout

from desktop import tokens as T


_GRADE_COLORS = {
    "GREEN":  T.ACCENT_HEX,
    "RED":    T.ALERT,
    "ORANGE": T.WARN,
    "AMBER":  T.WARN,
}


def _markdown_to_html(text: str) -> str:
    """Convert basic markdown to HTML for AI responses."""
    import re
    lines = text.split("\n")
    html_lines: list[str] = []
    in_table = False

    border = T.BORDER_0_HEX

    for line in lines:
        stripped = line.strip()

        if re.match(r'^\|[\s\-:]+\|', stripped):
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                html_lines.append(
                    f'<table style="color:{T.FG_0};border-collapse:collapse;'
                    f'width:100%;margin:8px 0;font-family:{T.FONT_MONO};'
                    f'font-size:12px;">'
                )
                in_table = True
            row_html = ""
            for cell in cells:
                cell = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', cell)
                for grade, color in _GRADE_COLORS.items():
                    if grade in cell.upper():
                        cell = re.sub(
                            rf'({grade})',
                            rf'<span style="color:{color};">\1</span>',
                            cell, flags=re.IGNORECASE,
                        )
                row_html += (
                    f'<td style="padding:4px 8px;'
                    f'border-bottom:1px solid {border};">{cell}</td>'
                )
            html_lines.append(f"<tr>{row_html}</tr>")
            continue

        if in_table:
            html_lines.append("</table>")
            in_table = False

        if stripped.startswith("## "):
            html_lines.append(
                f'<p style="color:{T.FG_0};font-weight:400;'
                f'letter-spacing:-0.01em;margin:12px 0 4px;font-size:15px;">'
                f'{stripped[3:]}</p>'
            )
            continue
        if stripped.startswith("# "):
            html_lines.append(
                f'<p style="color:{T.FG_0};font-weight:400;'
                f'letter-spacing:-0.02em;margin:14px 0 6px;font-size:18px;">'
                f'{stripped[2:]}</p>'
            )
            continue

        stripped = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', stripped)

        for grade, color in _GRADE_COLORS.items():
            stripped = re.sub(
                rf'\b({grade})\b',
                rf'<span style="color:{color};">\1</span>',
                stripped, flags=re.IGNORECASE,
            )

        if stripped == "---":
            html_lines.append(f'<hr style="border:0;border-top:1px solid {border};margin:12px 0;">')
            continue

        if stripped:
            html_lines.append(
                f'<p style="color:{T.FG_1_HEX};margin:4px 0;line-height:1.7;">{stripped}</p>'
            )

    if in_table:
        html_lines.append("</table>")

    return "\n".join(html_lines)


class ChatPanel(QGroupBox):
    message_submitted = Signal(str)

    def __init__(self, state: Any) -> None:
        super().__init__("CHAT")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 20, 6, 6)
        layout.setSpacing(8)

        self._messages = QTextEdit()
        self._messages.setReadOnly(True)
        self._messages.setStyleSheet(
            f"QTextEdit {{ background: {T.BG_0}; border: 1px solid {T.BORDER_0};"
            f" padding: 14px; font-family: {T.FONT_SANS}; font-size: 13px;"
            f" color: {T.FG_1_HEX}; }}"
        )
        layout.addWidget(self._messages, 1)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message…")
        self._input.returnPressed.connect(self._on_submit)
        self._input.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {T.FG_0};"
            f" border: none; border-top: 1px solid {T.BORDER_1};"
            f" padding: 12px 4px 10px 4px; font-family: {T.FONT_SANS};"
            f" font-size: 14px; }}"
            f"QLineEdit:focus {{ border-top-color: {T.ACCENT}; }}"
        )
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
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            if role != "user":
                text = _markdown_to_html(text)
            if role == "user":
                html_parts.append(
                    f'<div style="margin:10px 0 6px;">'
                    f'<span style="color:{T.ACCENT_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;letter-spacing:2px;">YOU</span></div>'
                    f'<p style="color:{T.FG_0};margin:0 0 10px;line-height:1.7;">{text}</p>'
                )
            else:
                html_parts.append(
                    f'<div style="margin:10px 0 6px;">'
                    f'<span style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;letter-spacing:2px;">BLANK</span></div>'
                    f'<div style="margin:0 0 10px;padding-left:2px;'
                    f'border-left:1px solid {T.BORDER_0_HEX};padding:0 0 0 12px;">{text}</div>'
                )
        if html_parts:
            self._messages.setHtml("".join(html_parts))
        else:
            self._messages.setHtml(
                f'<p style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                f'font-size:11px;letter-spacing:2px;">NO MESSAGES YET</p>'
            )
        sb = self._messages.verticalScrollBar()
        sb.setValue(sb.maximum())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()
