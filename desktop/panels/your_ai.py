"""Your blank advisor — visible personality readout for the terminal.

Shows the user who their install's advisor *is*: its generated name,
archetype, risk tolerance, initial traits, learned rules, and most
recent lessons. Also surfaces the paper-vs-live memory contract so
users know what carries across modes and what doesn't.

Branding: this panel is the *only* place the user meets their advisor
as a character, so the copy deliberately says "your blank advisor" —
never "AI", "agent", or the underlying model name.

Reads ``data/trader_personality.json`` directly on a 5s timer —
cheap, no coupling to the agent runner, and picks up edits the
supervisor makes between iterations without needing a signal wire-up.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop import tokens as T

logger = logging.getLogger(__name__)


class YourAIPanel(QGroupBox):
    """Personality + learned-knowledge readout for the blank advisor."""

    def __init__(self, state: Any) -> None:
        super().__init__("YOUR BLANK ADVISOR")
        self._state = state

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(8, 18, 8, 8)
        self._body_layout.setSpacing(10)

        # Identity (name + archetype + risk)
        self._name_label = QLabel("—")
        self._name_label.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_MONO};"
            f" font-size: 16px; font-weight: 600; letter-spacing: 1px;"
        )
        self._body_layout.addWidget(self._name_label)

        self._archetype_label = QLabel("—")
        self._archetype_label.setStyleSheet(
            f"color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px; letter-spacing: 2px;"
        )
        self._archetype_label.setWordWrap(True)
        self._body_layout.addWidget(self._archetype_label)

        self._risk_label = QLabel("—")
        self._risk_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px;"
        )
        self._risk_label.setWordWrap(True)
        self._body_layout.addWidget(self._risk_label)

        self._traits_label = QLabel("—")
        self._traits_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px;"
        )
        self._traits_label.setWordWrap(True)
        self._body_layout.addWidget(self._traits_label)

        self._body_layout.addWidget(_hairline())

        # Stats line
        self._stats_label = QLabel("—")
        self._stats_label.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px;"
        )
        self._body_layout.addWidget(self._stats_label)

        self._body_layout.addWidget(_hairline())

        # Rules section
        rules_header = QLabel("LEARNED RULES")
        rules_header.setStyleSheet(_section_header_style())
        self._body_layout.addWidget(rules_header)

        self._rules_container = QVBoxLayout()
        self._rules_container.setContentsMargins(0, 0, 0, 0)
        self._rules_container.setSpacing(4)
        rules_host = QWidget()
        rules_host.setLayout(self._rules_container)
        self._body_layout.addWidget(rules_host)

        self._body_layout.addWidget(_hairline())

        # Lessons section
        lessons_header = QLabel("RECENT LESSONS")
        lessons_header.setStyleSheet(_section_header_style())
        self._body_layout.addWidget(lessons_header)

        self._lessons_container = QVBoxLayout()
        self._lessons_container.setContentsMargins(0, 0, 0, 0)
        self._lessons_container.setSpacing(4)
        lessons_host = QWidget()
        lessons_host.setLayout(self._lessons_container)
        self._body_layout.addWidget(lessons_host)

        self._body_layout.addWidget(_hairline())

        # Memory-separation contract footer
        footer = QLabel(
            "your blank advisor learns with you. lessons from paper mode "
            "carry into live trading, but trades don't. it's the same "
            "advisor in both modes."
        )
        footer.setWordWrap(True)
        footer.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; font-style: italic;"
        )
        self._body_layout.addWidget(footer)

        self._body_layout.addStretch(1)

        scroll.setWidget(body)

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.addWidget(scroll)

        # Reload the JSON periodically. The file is tiny (KBs) and only
        # changes between agent iterations / chat-worker runs, so 5s
        # is plenty to feel live without spinning the disk.
        self._tick = QTimer(self)
        self._tick.setInterval(5000)
        self._tick.timeout.connect(self.refresh_view)
        self._tick.start()

        # Immediate first paint; don't wait 5s for the user to see content.
        self.refresh_view()

    # ── refresh ──────────────────────────────────────────────────────

    def refresh_view(self, state: Any | None = None) -> None:
        if state is not None:
            self._state = state
        payload = _load_personality_json(self._state)
        self._apply(payload)

    def _apply(self, payload: Optional[Dict[str, Any]]) -> None:
        if not payload:
            self._name_label.setText("NO ADVISOR PROFILE YET")
            self._archetype_label.setText("waiting for first run")
            self._risk_label.setText("")
            self._traits_label.setText("")
            self._stats_label.setText("")
            _clear_layout(self._rules_container)
            _clear_layout(self._lessons_container)
            return

        seed = payload.get("seed") or {}
        name = str(seed.get("name") or "Trader")
        archetype = str(seed.get("archetype") or "discretionary trader")
        risk = str(seed.get("risk_tolerance") or "balanced")
        traits = seed.get("initial_traits") or []

        self._name_label.setText(name.upper())
        self._archetype_label.setText(archetype.upper())
        self._risk_label.setText(f"risk: {risk}")
        if isinstance(traits, list) and traits:
            self._traits_label.setText("traits: " + ", ".join(str(t) for t in traits))
        else:
            self._traits_label.setText("traits: —")

        stats = payload.get("stats") or {}
        reflected = int(stats.get("total_trades_reflected_on") or 0)
        wins = int(stats.get("wins") or 0)
        losses = int(stats.get("losses") or 0)
        win_rate_txt = ""
        total_wl = wins + losses
        if total_wl > 0:
            win_rate_txt = f" · {100.0 * wins / total_wl:.0f}% win"
        self._stats_label.setText(
            f"{reflected} trades reflected on · {wins}W / {losses}L{win_rate_txt}"
        )

        self._render_rules(list(payload.get("rules") or []))
        self._render_lessons(list(payload.get("lessons") or [])[-5:])

    def _render_rules(self, rules: List[Dict[str, Any]]) -> None:
        _clear_layout(self._rules_container)
        if not rules:
            self._rules_container.addWidget(_empty_line(
                "(none yet — your advisor earns rules by watching its own trades.)",
            ))
            return
        # Newest first so the most recent learning is prominent.
        for entry in reversed(rules[-12:]):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            conf = str(entry.get("confidence") or "experimental")
            conf_label = QLabel(f"[{conf}]")
            conf_label.setStyleSheet(_confidence_style(conf))
            row.addWidget(conf_label, 0, Qt.AlignTop)

            rule_label = QLabel(str(entry.get("rule") or ""))
            rule_label.setWordWrap(True)
            rule_label.setStyleSheet(
                f"color: {T.FG_0}; font-family: {T.FONT_MONO};"
                f" font-size: 11px;"
            )
            row.addWidget(rule_label, 1)

            host = QWidget()
            host.setLayout(row)
            self._rules_container.addWidget(host)

    def _render_lessons(self, lessons: List[Dict[str, Any]]) -> None:
        _clear_layout(self._lessons_container)
        if not lessons:
            self._lessons_container.addWidget(_empty_line(
                "(none yet — lessons record after closed trades.)",
            ))
            return
        # Newest first.
        for entry in reversed(lessons):
            text = str(entry.get("lesson") or "").strip()
            if not text:
                continue
            tags = entry.get("tags") or []
            tag_suffix = ""
            if isinstance(tags, list) and tags:
                tag_suffix = "  " + " ".join(f"#{t}" for t in tags)
            label = QLabel(f"• {text}{tag_suffix}")
            label.setWordWrap(True)
            label.setStyleSheet(
                f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
                f" font-size: 11px;"
            )
            self._lessons_container.addWidget(label)


# ── helpers ──────────────────────────────────────────────────────────

def _load_personality_json(state: Any) -> Optional[Dict[str, Any]]:
    """Read the JSON file straight from disk. No coupling to the runner."""
    path = _resolve_personality_path(state)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover — corrupt file guard
        logger.debug("your_ai: failed to read personality file: %s", e)
        return None


def _resolve_personality_path(state: Any) -> Optional[Path]:
    """Derive the personality JSON path from the running config.

    Falls back to the default ``data/trader_personality.json`` when the
    app state hasn't loaded a config yet — matches what the agent runner
    does on the same key.
    """
    config = getattr(state, "config", None) or {}
    try:
        agent_cfg = config.get("agent", {}) if isinstance(config, dict) else {}
    except Exception:
        agent_cfg = {}
    raw = str(agent_cfg.get("trader_personality_path") or "data/trader_personality.json")
    return Path(raw)


def _hairline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setStyleSheet(f"color: {T.BORDER_1_HEX}; background: {T.BORDER_1_HEX};")
    line.setFixedHeight(1)
    return line


def _section_header_style() -> str:
    return (
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px;"
    )


def _confidence_style(confidence: str) -> str:
    c = confidence.lower()
    if c in ("high", "confirmed", "strong"):
        colour = T.ACCENT_HEX
    elif c in ("medium", "moderate"):
        colour = T.FG_1_HEX
    else:
        colour = T.FG_2_HEX
    return (
        f"color: {colour}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 1px;"
    )


def _empty_line(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 11px; font-style: italic;"
    )
    return label


def _clear_layout(layout: Any) -> None:
    """Remove and delete every child widget of ``layout``."""
    while True:
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
            continue
        sub = item.layout()
        if sub is not None:
            _clear_layout(sub)
