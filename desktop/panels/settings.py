"""Settings/metrics panel — account info, regime, model counts."""
from __future__ import annotations
from typing import Any
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

class SettingsPanel(QGroupBox):
    """Displays account metrics, regime, and model info."""

    def __init__(self, state: Any) -> None:
        super().__init__("SETTINGS")
        self._labels: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 16, 6, 6)
        layout.setSpacing(2)

        fields = [
            ("mode", "Mode"),
            ("regime", "Regime"),
            ("strategy", "Strategy"),
            ("models", "Models"),
            ("balance", "Balance"),
            ("invested", "Invested"),
            ("total", "Total"),
            ("upnl", "Unrealised"),
            ("max_loss", "Max Loss"),
        ]
        for key, label_text in fields:
            lbl = QLabel(f"{label_text}: --")
            lbl.setStyleSheet("font-size: 11px;")
            layout.addWidget(lbl)
            self._labels[key] = lbl

        layout.addStretch()
        self.refresh_view(state)

    def refresh_view(self, state: Any) -> None:
        mode_display = "AUTO" if state.mode == "full_auto_limited" else "ADVISOR"
        self._labels["mode"].setText(f"Mode: {mode_display}")

        regime_str = state.current_regime or "unknown"
        conf_str = f"{state.regime_confidence:.0%}" if state.regime_confidence else ""
        self._labels["regime"].setText(f"Regime: {regime_str} {conf_str}")

        # Strategy for current regime
        strat = state.regime_strategy_map.get(state.current_regime, "-")
        self._labels["strategy"].setText(f"Strategy: {strat}")

        self._labels["models"].setText(f"Models: {state.ensemble_model_count}")

        acct = state.account_info
        self._labels["balance"].setText(
            f"Balance: {_fmt_money(acct.get('free', 0))}"
        )
        self._labels["invested"].setText(
            f"Invested: {_fmt_money(acct.get('invested', 0))}"
        )
        self._labels["total"].setText(
            f"Total: {_fmt_money(acct.get('total', 0))}"
        )

        upnl = state.unrealised_pnl
        color = "#00ff00" if upnl >= 0 else "#ff0000"
        self._labels["upnl"].setText(f"Unrealised: {_fmt_money(upnl)}")
        self._labels["upnl"].setStyleSheet(f"color: {color}; font-size: 11px;")

        self._labels["max_loss"].setText(
            f"Max Loss: {state.max_daily_loss:.0%}"
        )


def _fmt_money(val: Any) -> str:
    try:
        return f"£{float(val):,.2f}"
    except (TypeError, ValueError):
        return "£0.00"
