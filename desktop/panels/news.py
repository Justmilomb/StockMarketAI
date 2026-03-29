"""News panel — sentiment summaries and headlines."""
from __future__ import annotations
from typing import Any
from PySide6.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout

class NewsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("NEWS")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 16, 4, 4)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)
        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        sentiment = state.news_sentiment or {}
        if not sentiment:
            self._text.setHtml('<p style="color:#888888;">No news data yet.</p>')
            return

        html_parts = []
        for ticker, data in list(sentiment.items())[:10]:
            if isinstance(data, dict):
                score = data.get("sentiment_score", 0)
                summary = data.get("summary", "")
                headlines = data.get("headlines", [])
            else:
                score = 0
                summary = str(data)
                headlines = []

            color = "#00ff00" if score > 0.1 else "#ff0000" if score < -0.1 else "#ffb000"
            html_parts.append(
                f'<p><span style="color:#00bfff;font-weight:bold;">{ticker}</span> '
                f'<span style="color:{color};">[{score:+.2f}]</span></p>'
            )
            if summary:
                html_parts.append(f'<p style="color:#aaaaaa;margin-left:8px;">{summary}</p>')
            for h in headlines[:3]:
                title = h if isinstance(h, str) else h.get("title", "")
                html_parts.append(
                    f'<p style="color:#888888;margin-left:12px;">- {title}</p>'
                )

        self._text.setHtml("".join(html_parts))
