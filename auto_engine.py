from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from ai_service import AiService
from broker_service import BrokerService
from terminal.state import AppState


ConfigDict = Dict[str, Any]


@dataclass
class AutoEngine:
    """
    Automation engine that converts AI signals into orders when in
    full_auto_limited mode, respecting basic risk limits.
    """

    config: ConfigDict
    state: AppState
    ai_service: AiService
    broker_service: BrokerService

    def step(self) -> None:
        """Run a single automation step."""
        if self.state.mode != "full_auto_limited":
            return

        signals_df, _meta = self.ai_service.get_latest_signals()
        self.state.signals = signals_df

        orders: List[Dict[str, Any]] = []

        # BUY signals
        buy_signals = signals_df[signals_df["signal"] == "buy"]
        for _, row in buy_signals.iterrows():
            orders.append({
                "ticker": row["ticker"],
                "side": "BUY",
                "quantity": 1.0,
                "order_type": "market",
            })

        # SELL signals
        sell_signals = signals_df[signals_df["signal"] == "sell"]
        for _, row in sell_signals.iterrows():
            orders.append({
                "ticker": row["ticker"],
                "side": "SELL",
                "quantity": 1.0,
                "order_type": "market",
            })

        if not orders:
            return

        # Check daily loss limit
        upnl = self.state.unrealised_pnl
        max_loss = self.state.capital * self.state.max_daily_loss
        if upnl < -max_loss:
            print(f"[auto_engine] Daily loss limit hit (${upnl:.2f}). Skipping orders.")
            return

        results = self.broker_service.submit_orders(orders)
        self.state.recent_orders.extend(results)
