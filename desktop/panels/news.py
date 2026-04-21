"""Information panel — news sentiment, market news, and research findings.

Three stacked sections share one QTextEdit, rendered as hairline-bordered
HTML blocks on the terminal-dark palette:

1. **WATCHLIST SENTIMENT** — per-ticker aggregate mood + representative
   headlines.
2. **AGENT RESEARCH** — latest findings from the research swarm.
3. **MARKET NEWS** — raw scraper cache with per-item sentiment badges.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, List, Optional

from PySide6.QtWidgets import QGroupBox, QTextEdit, QVBoxLayout

from desktop import tokens as T


_TYPE_COLOURS: dict[str, str] = {
    "alert": T.ALERT,
    "opportunity": T.ACCENT_HEX,
    "risk": T.WARN,
    "insight": T.FG_1_HEX,
}


def _kicker(text: str, *, top: int = 0) -> str:
    return (
        f'<p style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
        f'font-size:10px;letter-spacing:2px;margin:{top}px 0 6px;">'
        f'{escape(text)}</p>'
    )


def _sentiment_colour(score: float, *, threshold: float = 0.1) -> str:
    if score > threshold:
        return T.ACCENT_HEX
    if score < -threshold:
        return T.ALERT
    return T.FG_2_HEX


class NewsPanel(QGroupBox):
    def __init__(self, state: Any) -> None:
        super().__init__("INFORMATION")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 18, 4, 4)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            f"QTextEdit {{ background: {T.BG_0}; border: 1px solid {T.BORDER_0};"
            f" padding: 10px; font-family: {T.FONT_SANS}; font-size: 12px;"
            f" color: {T.FG_1_HEX}; }}"
        )
        layout.addWidget(self._text)
        self._news_available = self._check_dependencies()
        self.refresh_view(state)

    def _check_dependencies(self) -> bool:
        try:
            import feedparser  # noqa: F401
            return True
        except ImportError:
            return False

    def refresh_view(self, state: Any) -> None:
        sentiment = state.news_sentiment or {}
        market_news: List[dict] = list(getattr(state, "market_news", []) or [])
        findings: List[dict] = list(getattr(state, "research_findings", []) or [])

        if not self._news_available:
            self._text.setHtml(
                f'<p style="color:{T.ALERT};font-family:{T.FONT_MONO};'
                f'font-size:10px;letter-spacing:2px;">NEWS UNAVAILABLE</p>'
                f'<p style="color:{T.FG_1_HEX};margin:4px 0;">'
                f'feedparser is not installed.</p>'
                f'<p style="color:{T.FG_1_HEX};margin:4px 0;">'
                f'Run: pip install feedparser</p>'
            )
            return

        if not sentiment and not market_news and not findings:
            self._text.setHtml(
                f'<p style="color:{T.WARN};font-family:{T.FONT_MONO};'
                f'font-size:10px;letter-spacing:2px;">WAITING FOR DATA</p>'
                f'<p style="color:{T.FG_1_HEX};margin:4px 0;">'
                f'Scraper runner fills this within a minute of startup.</p>'
            )
            return

        parts: List[str] = []

        if sentiment:
            parts.append(_kicker("WATCHLIST SENTIMENT"))
            for ticker, data in list(sentiment.items())[:10]:
                if isinstance(data, dict):
                    score = data.get("sentiment_score", 0)
                    summary = data.get("summary", "")
                    headlines = data.get("headlines", [])
                else:
                    score = 0
                    summary = str(data)
                    headlines = []

                try:
                    score_f = float(score)
                except (TypeError, ValueError):
                    score_f = 0.0
                colour = _sentiment_colour(score_f)
                parts.append(
                    f'<p style="margin:6px 0 2px;">'
                    f'<span style="color:{T.FG_0};font-weight:600;">'
                    f'{escape(str(ticker))}</span> '
                    f'<span style="color:{colour};font-family:{T.FONT_MONO};'
                    f'font-size:11px;">{score_f:+.2f}</span>'
                    f'</p>'
                )
                if summary:
                    parts.append(
                        f'<p style="color:{T.FG_1_HEX};margin:0 0 0 8px;'
                        f'line-height:1.5;">{escape(str(summary))}</p>'
                    )
                for h in headlines[:3]:
                    title = h if isinstance(h, str) else h.get("title", "")
                    parts.append(
                        f'<p style="color:{T.FG_1_HEX};margin:2px 0 2px 14px;'
                        f'line-height:1.4;">— {escape(str(title))}</p>'
                    )

        swarm_status = getattr(state, "swarm_status", None) or {}
        swarm_running = bool(swarm_status.get("running"))

        if findings or swarm_running:
            parts.append(_kicker("AGENT RESEARCH", top=14))

        if not findings and swarm_running:
            active = int(swarm_status.get("active_workers", 0) or 0)
            ran = int(swarm_status.get("total_tasks_run", 0) or 0)
            parts.append(
                f'<p style="color:{T.FG_1_HEX};margin:0 0 0 4px;">'
                f'Swarm running — {active} workers, {ran} tasks. '
                f'Findings land here as workers report in.</p>'
            )

        if findings:
            for f in findings[:8]:
                role = str(f.get("role", ""))[:14]
                ticker = str(f.get("ticker") or "MKT")[:8]
                try:
                    conf = int(f.get("confidence_pct", 0) or 0)
                except (TypeError, ValueError):
                    conf = 0
                headline = str(f.get("headline", "")).strip()
                if not headline:
                    continue
                finding_type = str(f.get("finding_type", "")).lower()
                head_display = headline[:120] + ("…" if len(headline) > 120 else "")
                conf_colour = (
                    T.ACCENT_HEX if conf >= 75
                    else T.WARN if conf >= 55
                    else T.FG_2_HEX
                )
                type_colour = _TYPE_COLOURS.get(finding_type, T.FG_2_HEX)
                rel = _relative_time(f.get("created_at"))
                parts.append(
                    f'<p style="margin:4px 0 4px 4px;line-height:1.5;">'
                    f'<span style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;letter-spacing:1px;">'
                    f'{escape(role.upper())}</span> '
                    f'<span style="color:{T.FG_0};font-weight:600;">'
                    f'{escape(ticker)}</span> '
                    f'<span style="color:{conf_colour};font-family:{T.FONT_MONO};'
                    f'font-size:10px;">{conf}%</span> '
                    f'<span style="color:{type_colour};font-family:{T.FONT_MONO};'
                    f'font-size:10px;letter-spacing:1px;">'
                    f'{escape((finding_type or "—").upper())}</span> '
                    f'<span style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;">{escape(rel)}</span> '
                    f'<span style="color:{T.FG_1_HEX};">'
                    f'{escape(head_display)}</span>'
                    f'</p>'
                )

        if market_news:
            appendix = bool(sentiment or findings)
            limit = 8 if appendix else 15
            parts.append(_kicker("MARKET NEWS", top=14))
            for item in market_news[:limit]:
                src = str(item.get("source", "")).upper()
                title = str(item.get("title", "")).strip()
                if not title:
                    continue
                title_display = title[:140] + ("…" if len(title) > 140 else "")
                rel = _relative_time(item.get("ts") or item.get("fetched_at"))
                badge_html = _sentiment_badge(
                    item.get("sentiment_score"),
                    item.get("sentiment_label"),
                )
                parts.append(
                    f'<p style="margin:3px 0 3px 4px;line-height:1.5;">'
                    f'<span style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;letter-spacing:1px;">'
                    f'{escape(src)}</span> '
                    f'{badge_html}'
                    f'<span style="color:{T.FG_2_HEX};font-family:{T.FONT_MONO};'
                    f'font-size:10px;">{escape(rel)}</span> '
                    f'<span style="color:{T.FG_1_HEX};">'
                    f'{escape(title_display)}</span>'
                    f'</p>'
                )

        self._text.setHtml("".join(parts))


def _sentiment_badge(score: Any, label: Optional[str]) -> str:
    if score is None:
        return ""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    colour = _sentiment_colour(s)
    return (
        f'<span style="color:{colour};font-family:{T.FONT_MONO};'
        f'font-size:10px;">{s:+.2f}</span> '
    )


def _relative_time(ts: Any) -> str:
    if not ts:
        return ""
    s = str(ts).strip()
    if not s:
        return ""
    try:
        parsed = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    secs = int((now - parsed).total_seconds())
    if secs < 0:
        return "now"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"
