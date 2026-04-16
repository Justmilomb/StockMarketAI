"""Information panel — news sentiment, headlines, and research findings."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, List

from PySide6.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout


class NewsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("INFORMATION")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 16, 4, 4)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        layout.addWidget(self._text)
        self._news_available = self._check_dependencies()
        self._ai_available = True
        self.refresh_view(state)

    def _check_dependencies(self) -> bool:
        """Check if feedparser is installed."""
        try:
            import feedparser  # noqa: F401
            return True
        except ImportError:
            return False

    def set_ai_available(self, available: bool) -> None:
        """Update whether the AI backend is reachable."""
        self._ai_available = available

    def refresh_view(self, state: Any) -> None:
        sentiment = state.news_sentiment or {}
        market_news: List[dict] = list(getattr(state, "market_news", []) or [])

        if not self._news_available:
            self._text.setHtml(
                '<p style="color:#ff0000; font-weight:bold;">NEWS UNAVAILABLE</p>'
                '<p style="color:#888888;">feedparser not installed.</p>'
                '<p style="color:#555555;">Run: pip install feedparser</p>'
            )
            return

        if not sentiment and not market_news:
            if not self._ai_available:
                self._text.setHtml(
                    '<p style="color:#ff5555; font-weight:bold;">AI UNAVAILABLE</p>'
                    '<p style="color:#888888;">AI engine is offline -- news '
                    'sentiment is disabled.</p>'
                    '<p style="color:#555555;">See the setup wizard or '
                    'help.blank.app/setup.</p>'
                )
            else:
                self._text.setHtml(
                    '<p style="color:#ffb000;">Waiting for news data...</p>'
                    '<p style="color:#555555;">Scraper runner fills this within '
                    'a minute of startup. Press N to force a sentiment refresh.</p>'
                )
            return

        html_parts: List[str] = []

        if sentiment:
            html_parts.append(
                '<p style="color:#ff8c00;font-weight:bold;">WATCHLIST SENTIMENT</p>'
            )
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
                    f'<p><span style="color:#00bfff;font-weight:bold;">{escape(str(ticker))}</span> '
                    f'<span style="color:{color};">[{score:+.2f}]</span></p>'
                )
                if summary:
                    html_parts.append(
                        f'<p style="color:#aaaaaa;margin-left:8px;">{escape(str(summary))}</p>'
                    )
                for h in headlines[:3]:
                    title = h if isinstance(h, str) else h.get("title", "")
                    html_parts.append(
                        f'<p style="color:#888888;margin-left:12px;">- {escape(str(title))}</p>'
                    )

        if market_news:
            # Smaller appendix when we also have per-ticker sentiment,
            # full-width primary view when we don't.
            appendix = bool(sentiment)
            header_size = "10px" if appendix else "11px"
            limit = 8 if appendix else 15
            html_parts.append(
                f'<p style="color:#ff8c00;font-weight:bold;font-size:{header_size};'
                f'margin-top:8px;">MARKET NEWS</p>'
            )
            for item in market_news[:limit]:
                src = str(item.get("source", "")).upper()
                title = str(item.get("title", "")).strip()
                if not title:
                    continue
                title_display = title[:140] + ("…" if len(title) > 140 else "")
                rel = _relative_time(item.get("ts") or item.get("fetched_at"))
                html_parts.append(
                    f'<p style="color:#888888;margin-left:4px;">'
                    f'<span style="color:#00bfff;">[{escape(src)}]</span> '
                    f'<span style="color:#666666;">{escape(rel)}</span> '
                    f'<span style="color:#cccccc;">{escape(title_display)}</span>'
                    f'</p>'
                )

        self._text.setHtml("".join(html_parts))


def _relative_time(ts: Any) -> str:
    """Return a short relative-time label like '12m' / '3h' / '2d'.

    The scraper_items table stores timestamps as ISO strings (either the
    RSS-parsed ``ts`` or SQLite's ``fetched_at`` default). We parse
    loosely and fall back to an empty string on anything weird — the
    caller renders the label alongside the title, so an empty string
    just means "no timestamp" rather than breaking the layout.
    """
    if not ts:
        return ""
    s = str(ts).strip()
    if not s:
        return ""
    try:
        # Accept both "2026-04-15T10:03:00+00:00" and "2026-04-15 10:03:00"
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - parsed
    secs = int(delta.total_seconds())
    if secs < 0:
        return "now"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"
