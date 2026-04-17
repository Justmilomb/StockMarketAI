"""Information panel — news sentiment, market news, and research findings.

Three sections render top-down:

1. **WATCHLIST SENTIMENT** — per-ticker aggregate mood from the news
   agent, plus up to three representative headlines. Only rendered when
   the news agent has produced scored data for a ticker.
2. **AGENT RESEARCH** — latest findings submitted by the research swarm,
   one per iteration-cycle. Shows role, ticker (or ``MKT`` when the
   finding is market-wide / discovery), confidence, and the short
   headline. Colour-coded by the finding type / confidence.
3. **MARKET NEWS** — the raw scraper cache, with a VADER sentiment
   badge prepended to each row so the user can triage at a glance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, List, Optional

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
        self.refresh_view(state)

    def _check_dependencies(self) -> bool:
        """Check if feedparser is installed."""
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
                '<p style="color:#ff0000; font-weight:bold;">NEWS UNAVAILABLE</p>'
                '<p style="color:#888888;">feedparser not installed.</p>'
                '<p style="color:#555555;">Run: pip install feedparser</p>'
            )
            return

        # Scraper runner + agent research swarm fill these three sources.
        # Both spin up asynchronously at launch, so the empty-state wait
        # banner is the honest answer here; there is no "AI engine" to
        # be offline any more.
        if not sentiment and not market_news and not findings:
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

        swarm_status = getattr(state, "swarm_status", None) or {}
        swarm_running = bool(swarm_status.get("running"))

        if findings or swarm_running:
            html_parts.append(
                '<p style="color:#ff8c00;font-weight:bold;margin-top:8px;">'
                'AGENT RESEARCH</p>'
            )
        if not findings and swarm_running:
            active = int(swarm_status.get("active_workers", 0) or 0)
            ran = int(swarm_status.get("total_tasks_run", 0) or 0)
            html_parts.append(
                f'<p style="color:#888888;margin-left:4px;">'
                f'Swarm running — {active} active workers, {ran} tasks run. '
                f'Findings land here once workers complete.</p>'
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
                headline_display = headline[:120] + ("…" if len(headline) > 120 else "")
                conf_color = (
                    "#00ff00" if conf >= 75
                    else "#ffd700" if conf >= 55
                    else "#888888"
                )
                type_color = {
                    "alert": "#ff5555",
                    "opportunity": "#00ff00",
                    "risk": "#ff8c00",
                    "insight": "#00bfff",
                }.get(finding_type, "#aaaaaa")
                rel = _relative_time(f.get("created_at"))
                html_parts.append(
                    f'<p style="margin-left:4px;">'
                    f'<span style="color:#888888;">[{escape(role)}]</span> '
                    f'<span style="color:#00bfff;font-weight:bold;">{escape(ticker)}</span> '
                    f'<span style="color:{conf_color};">{conf}%</span> '
                    f'<span style="color:{type_color};">{escape(finding_type or "--")}</span> '
                    f'<span style="color:#666666;">{escape(rel)}</span> '
                    f'<span style="color:#cccccc;">{escape(headline_display)}</span>'
                    f'</p>'
                )

        if market_news:
            # Shrink the market-news section when other sections are also
            # showing so the overall panel doesn't scroll off the screen.
            appendix = bool(sentiment or findings)
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
                badge_html = _sentiment_badge(
                    item.get("sentiment_score"),
                    item.get("sentiment_label"),
                )
                html_parts.append(
                    f'<p style="color:#888888;margin-left:4px;">'
                    f'<span style="color:#00bfff;">[{escape(src)}]</span> '
                    f'{badge_html}'
                    f'<span style="color:#666666;">{escape(rel)}</span> '
                    f'<span style="color:#cccccc;">{escape(title_display)}</span>'
                    f'</p>'
                )

        self._text.setHtml("".join(html_parts))


def _sentiment_badge(score: Any, label: Optional[str]) -> str:
    """Return an inline HTML span for the sentiment badge or empty string."""
    if score is None:
        return ""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return ""
    # Colour matches the threshold logic in _sentiment.py.
    if s > 0.1:
        color = "#00ff00"
    elif s < -0.1:
        color = "#ff0000"
    else:
        color = "#888888"
    return f'<span style="color:{color};">[{s:+.2f}]</span> '


def _relative_time(ts: Any) -> str:
    """Return a short relative-time label like '12m' / '3h' / '2d'.

    The scraper_items and research_findings tables both store timestamps
    as ISO strings (either the RSS-parsed ``ts``, SQLite's ``fetched_at``
    default, or ``created_at``). Parses loosely and falls back to an
    empty string on anything weird — the caller renders the label
    alongside the title, so empty = "no timestamp" rather than broken.
    """
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
