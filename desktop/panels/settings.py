"""Settings / status panel — account info + live agent cockpit.

Phase 6 rewrite: the old panel surfaced regime, strategy profile,
and model-count — all dead data since Phase 3 killed the ML
pipeline. The new panel is a compact agent + account readout:

* agent status (running / offline) and paper-vs-live mode
* cadence (reads fresh from config each refresh)
* seconds since last iteration
* tool calls in the current/last iteration
* account balance / invested / total / unrealised PnL

Start/stop/kill buttons live on the AgentLogPanel — this one is a
pure readout so docking it into the sidebar doesn't double up on
control surface.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout


class SettingsPanel(QGroupBox):
    """Account metrics + agent status readout."""

    def __init__(self, state: Any) -> None:
        super().__init__("STATUS")
        self._labels: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 6)
        layout.setSpacing(2)

        fields: list[tuple[str, str]] = [
            ("agent", "Agent"),
            ("mode", "Mode"),
            ("cadence", "Cadence"),
            ("last_iter", "Last iter"),
            ("tool_calls", "Tool calls"),
            ("balance", "Balance"),
            ("invested", "Invested"),
            ("total", "Total"),
            ("upnl", "Unrealised"),
        ]
        for key, label_text in fields:
            lbl = QLabel(f"{label_text}: --")
            lbl.setStyleSheet("font-size: 11px;")
            layout.addWidget(lbl)
            self._labels[key] = lbl

        layout.addStretch()
        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        # Agent live/offline + colour.
        running = bool(getattr(state, "agent_running", False))
        if running:
            self._labels["agent"].setText("Agent: running")
            self._labels["agent"].setStyleSheet(
                "color: #00ff00; font-size: 11px; font-weight: bold;",
            )
        else:
            self._labels["agent"].setText("Agent: offline")
            self._labels["agent"].setStyleSheet(
                "color: #ff8c00; font-size: 11px; font-weight: bold;",
            )

        # Paper vs live mode.
        paper = bool(getattr(state, "agent_paper_mode", True))
        if paper:
            self._labels["mode"].setText("Mode: PAPER")
            self._labels["mode"].setStyleSheet(
                "color: #ffd700; font-size: 11px; font-weight: bold;",
            )
        else:
            self._labels["mode"].setText("Mode: LIVE")
            self._labels["mode"].setStyleSheet(
                "color: #ff0000; font-size: 11px; font-weight: bold;",
            )

        # Cadence — read from most recent agent section loaded at boot.
        # The panel doesn't reach back into config.json every refresh;
        # changes take effect on the next iteration via runner.
        cadence = _extract_cadence(state)
        self._labels["cadence"].setText(f"Cadence: {cadence}s")

        # Seconds since last iteration.
        last_ts = getattr(state, "last_iteration_ts", None)
        if isinstance(last_ts, datetime):
            delta = (datetime.now() - last_ts).total_seconds()
            self._labels["last_iter"].setText(f"Last iter: {int(delta)}s ago")
        else:
            self._labels["last_iter"].setText("Last iter: --")

        # Tool calls in the current/last iteration.
        recent = getattr(state, "recent_tool_calls", None) or []
        self._labels["tool_calls"].setText(f"Tool calls: {len(recent)}")

        # Account.
        acct = getattr(state, "account_info", None) or {}
        self._labels["balance"].setText(
            f"Balance: {_fmt_money(acct.get('free', 0))}"
        )
        self._labels["invested"].setText(
            f"Invested: {_fmt_money(acct.get('invested', 0))}"
        )
        self._labels["total"].setText(
            f"Total: {_fmt_money(acct.get('total', 0))}"
        )
        upnl = getattr(state, "unrealised_pnl", 0.0) or 0.0
        colour = "#00ff00" if upnl >= 0 else "#ff0000"
        self._labels["upnl"].setText(f"Unrealised: {_fmt_money(upnl)}")
        self._labels["upnl"].setStyleSheet(f"color: {colour}; font-size: 11px;")


def _extract_cadence(state: Any) -> int:
    """Best-effort read of the agent cadence from wherever state stashes it.

    The runner reads config.json fresh every iteration, so the state
    field is only a UI readout. Falls back to 90s if unset.
    """
    val = getattr(state, "agent_cadence_seconds", None)
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    return 90


def _fmt_money(val: Any) -> str:
    try:
        return f"£{float(val):,.2f}"
    except (TypeError, ValueError):
        return "£0.00"
