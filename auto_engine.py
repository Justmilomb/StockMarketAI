from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from ai_service import AiService
from broker_service import BrokerService
from intraday_data import is_intraday_supported
from risk_manager import RiskManager
from terminal.state import AppState
from types_shared import ConsensusResult

logger = logging.getLogger(__name__)

ConfigDict = Dict[str, Any]


@dataclass
class AutoEngine:
    """
    Automation engine that converts AI signals into orders when in
    full_auto_limited mode, with portfolio-level risk management.
    """

    config: ConfigDict
    state: AppState
    ai_service: AiService
    broker_service: BrokerService
    _risk_manager: RiskManager | None = None

    def _select_intent(self, ticker: str) -> str:
        """Decide whether to use daily or intraday strategy for a ticker.

        Intraday is dormant for now — always returns "daily".
        When activated, this will check intraday eligibility and signal strength.
        """
        # Intraday trading is dormant — uncomment below when ready
        # if not is_intraday_supported(ticker):
        #     return "daily"
        # # High short-term volatility + strong signal → intraday opportunity
        # vol = self.state.live_data.get(ticker, {}).get("volatility", 0)
        # if vol > 0.03:  # >3% intraday move
        #     return "intraday"
        return "daily"

    def _get_risk_manager(self) -> RiskManager:
        if self._risk_manager is None:
            risk_cfg = self.config.get("risk", {})
            self._risk_manager = RiskManager(risk_cfg)
        return self._risk_manager

    def step(self) -> None:
        """Run a single automation step with risk-managed position sizing.

        Uses cached signals from state (populated by the pipeline in
        refresh_data) rather than calling get_latest_signals() again,
        which would redundantly re-run the expensive AI pipeline.
        """
        if self.state.mode != "full_auto_limited":
            return

        signals_df = self.state.signals
        if signals_df is None or (hasattr(signals_df, 'empty') and signals_df.empty):
            return

        # Skip protected tickers — user has locked these from trading
        # Case-insensitive: config may have mixed-case T212 suffixes
        protected = self.state.protected_tickers
        if protected:
            protected_upper = {t.upper() for t in protected}
            signals_df = signals_df[~signals_df["ticker"].str.upper().isin(protected_upper)].copy()
            if signals_df.empty:
                return

        # Check daily loss limit before generating any orders
        upnl = self.state.unrealised_pnl
        max_loss = self.state.capital * self.state.max_daily_loss
        if upnl < -max_loss:
            logger.warning(
                "Daily loss limit hit ($%.2f). Skipping orders.", upnl
            )
            return

        # Build consensus lookup from state
        consensus: Dict[str, ConsensusResult] = {}
        for ticker, cons_data in self.state.consensus_data.items():
            if isinstance(cons_data, ConsensusResult):
                consensus[ticker] = cons_data

        # Gather latest features if available from ai_service
        features_data = getattr(self.ai_service, "_last_features_df", None)

        rm = self._get_risk_manager()
        orders = rm.generate_risk_enhanced_orders(
            signals_df=signals_df,
            consensus=consensus,
            features_data=features_data,
            positions=self.state.positions,
            account=self.state.account_info,
            prices=self.state.live_data,
            initial_capital=self.state.capital,
        )

        if not orders:
            return

        results = self.broker_service.submit_orders(orders)
        self.state.recent_orders.extend(results)
