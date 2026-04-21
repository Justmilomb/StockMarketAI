"""Settings / status panel — compact agent + account readout.

Renders a single column of key / value rows:

* agent status (running / offline)
* cadence
* next iteration countdown (or "RUNNING" mid-iteration)
* account balance / invested / total / unrealised PnL

Mode (paper vs live) is deliberately **not** shown — the only paper-mode
tell anywhere in the app is the watermark painted over the chart.

Start / stop / kill buttons live on the AgentLogPanel. This one is a
pure readout so docking it into the sidebar doesn't double up on
control surface.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QGroupBox, QLabel, QVBoxLayout

from desktop import tokens as T


_FIELDS: list[tuple[str, str]] = [
    ("agent", "AGENT"),
    ("cadence", "CADENCE"),
    ("next_iter", "NEXT ITER"),
    ("balance", "BALANCE"),
    ("invested", "INVESTED"),
    ("total", "TOTAL"),
    ("upnl", "UNREALISED"),
]


class SettingsPanel(QGroupBox):
    """Account metrics + agent status readout."""

    def __init__(self, state: Any) -> None:
        super().__init__("STATUS")
        self._state = state
        self._value_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 18, 6, 6)
        root.setSpacing(2)

        grid_host = QFrame()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        for row, (key, label_text) in enumerate(_FIELDS):
            label = QLabel(label_text)
            label.setStyleSheet(
                f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
                f" font-size: 10px; letter-spacing: 2px;"
            )
            value = QLabel("—")
            value.setStyleSheet(self._value_style())
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            self._value_labels[key] = value

        grid.setColumnStretch(1, 1)
        root.addWidget(grid_host)
        root.addStretch()

        # 1 Hz tick so the NEXT ITER countdown updates smoothly even when
        # nothing else in the app is refreshing. Cheap — single label
        # repaint on the GUI thread.
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self.refresh_view(state)

    @staticmethod
    def _value_style(color: str = T.FG_0, *, bold: bool = False) -> str:
        weight = "600" if bold else "400"
        return (
            f"color: {color}; font-family: {T.FONT_MONO};"
            f" font-size: 12px; font-weight: {weight};"
        )

    def _on_tick(self) -> None:
        self.refresh_view(self._state)

    def refresh_view(self, state: Any) -> None:
        self._state = state

        running = bool(getattr(state, "agent_running", False))
        agent_colour = T.ACCENT_HEX if running else T.FG_2_HEX
        self._value_labels["agent"].setText("RUNNING" if running else "OFFLINE")
        self._value_labels["agent"].setStyleSheet(
            self._value_style(agent_colour, bold=True)
        )

        cadence = _extract_cadence(state)
        self._value_labels["cadence"].setText(f"{cadence}s")
        self._value_labels["cadence"].setStyleSheet(self._value_style(T.FG_0))

        text, colour = _next_iter_readout(state, cadence)
        self._value_labels["next_iter"].setText(text)
        self._value_labels["next_iter"].setStyleSheet(
            self._value_style(colour, bold=text == "RUNNING")
        )

        acct = getattr(state, "account_info", None) or {}
        for key in ("balance", "invested", "total"):
            src_key = "free" if key == "balance" else key
            self._value_labels[key].setText(_fmt_money(acct.get(src_key, 0)))
            self._value_labels[key].setStyleSheet(self._value_style(T.FG_0))

        upnl = getattr(state, "unrealised_pnl", 0.0) or 0.0
        try:
            upnl_f = float(upnl)
        except (TypeError, ValueError):
            upnl_f = 0.0
        pnl_colour = (
            T.ACCENT_HEX if upnl_f > 0 else T.ALERT if upnl_f < 0 else T.FG_2_HEX
        )
        sign = "+" if upnl_f > 0 else ""
        self._value_labels["upnl"].setText(f"{sign}{_fmt_money(upnl_f)}")
        self._value_labels["upnl"].setStyleSheet(self._value_style(pnl_colour, bold=True))


def _extract_cadence(state: Any) -> int:
    val = getattr(state, "agent_cadence_seconds", None)
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    return 90


def _next_iter_readout(state: Any, cadence: int) -> tuple[str, str]:
    """Return ``(label, colour)`` for the NEXT ITER cell.

    * Agent off → ``"—"`` dim.
    * Mid-iteration → ``"RUNNING"`` in accent green.
    * Sleeping → a countdown like ``"42s"`` ticking toward the next wake.
    * Unknown (e.g. app just started and first iteration hasn't run) →
      show the cadence as a best-guess duration.
    """
    if not getattr(state, "agent_running", False):
        return "—", T.FG_2_HEX

    if getattr(state, "agent_iteration_active", False):
        return "RUNNING", T.ACCENT_HEX

    start = getattr(state, "agent_wait_start_ts", None)
    if isinstance(start, datetime) and cadence > 0:
        remaining = int(cadence - (datetime.now() - start).total_seconds())
        if remaining < 0:
            remaining = 0
        return f"{remaining}s", T.FG_1_HEX

    return f"{cadence}s", T.FG_1_HEX


def _fmt_money(val: Any) -> str:
    try:
        return f"£{float(val):,.2f}"
    except (TypeError, ValueError):
        return "£0.00"
