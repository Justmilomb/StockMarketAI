"""Trade simulator — realistic portfolio execution for backtesting.

Tracks positions, cash, stop-loss/take-profit triggers, slippage,
commissions, and daily equity snapshots.  No lookahead bias — only
uses data available up to the current simulation day.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backtesting.types import (
    BacktestConfig,
    DailySnapshot,
    Position,
    TradeRecord,
)

logger = logging.getLogger(__name__)


class TradeSimulator:
    """Simulates a portfolio with realistic trade execution."""

    def __init__(
        self,
        config: BacktestConfig,
        per_ticker_overrides: Dict[str, Dict[str, float]] | None = None,
    ) -> None:
        self._config = config
        self._per_ticker_overrides: Dict[str, Dict[str, float]] = per_ticker_overrides or {}
        self._cash: float = config.initial_capital
        self._positions: Dict[str, Position] = {}
        self._trades: List[TradeRecord] = []
        self._snapshots: List[DailySnapshot] = []
        self._peak_equity: float = config.initial_capital
        self._prev_equity: float = config.initial_capital

    @property
    def trades(self) -> List[TradeRecord]:
        return list(self._trades)

    @property
    def snapshots(self) -> List[DailySnapshot]:
        return list(self._snapshots)

    @property
    def equity(self) -> float:
        return self._cash + sum(
            p.entry_price * p.quantity for p in self._positions.values()
        )

    # ------------------------------------------------------------------
    # Public API — called once per simulated trading day
    # ------------------------------------------------------------------

    def process_day(
        self,
        current_date: date,
        prices: Dict[str, Dict[str, float]],
        signals: Dict[str, float],
        atr_values: Dict[str, float],
    ) -> None:
        """Process one trading day.

        Args:
            current_date: The simulation date
            prices:       {ticker: {"open": f, "high": f, "low": f, "close": f}}
            signals:      {ticker: prob_up} — probabilities for today
            atr_values:   {ticker: ATR} — for stop/take-profit calculation
        """
        # 1. Check stops and take-profits on open positions
        self._check_stops(current_date, prices)

        # 2. Process sell signals
        self._process_sells(current_date, prices, signals)

        # 3. Process buy signals
        self._process_buys(current_date, prices, signals, atr_values)

        # 4. Mark-to-market and record daily snapshot
        self._record_snapshot(current_date, prices)

    def close_all_positions(self, current_date: date, prices: Dict[str, Dict[str, float]]) -> None:
        """Force-close all positions at end of fold."""
        for ticker in list(self._positions.keys()):
            price_data = prices.get(ticker)
            if price_data is None:
                continue
            close_price = price_data["close"]
            self._close_position(ticker, current_date, close_price, "end_of_fold")

    # ------------------------------------------------------------------
    # Internal execution logic
    # ------------------------------------------------------------------

    def _check_stops(
        self,
        current_date: date,
        prices: Dict[str, Dict[str, float]],
    ) -> None:
        """Check intraday stop-loss and take-profit triggers."""
        if not self._config.use_stops:
            return

        for ticker in list(self._positions.keys()):
            pos = self._positions[ticker]
            price_data = prices.get(ticker)
            if price_data is None:
                continue

            low = price_data["low"]
            high = price_data["high"]

            # Stop-loss hit (intraday low breaches stop)
            if low <= pos.stop_loss:
                fill_price = pos.stop_loss  # Assume fill at stop level
                self._close_position(ticker, current_date, fill_price, "stop_loss")
                continue

            # Take-profit hit (intraday high breaches target)
            if high >= pos.take_profit:
                fill_price = pos.take_profit
                self._close_position(ticker, current_date, fill_price, "take_profit")

    def _process_sells(
        self,
        current_date: date,
        prices: Dict[str, Dict[str, float]],
        signals: Dict[str, float],
    ) -> None:
        """Sell positions where signal drops below threshold."""
        for ticker in list(self._positions.keys()):
            if ticker not in signals:
                continue
            overrides = self._per_ticker_overrides.get(ticker, {})
            threshold = overrides.get("threshold_sell", self._config.threshold_sell)
            if signals[ticker] > threshold:
                continue  # Signal still okay — hold

            price_data = prices.get(ticker)
            if price_data is None:
                continue

            # Sell at close with slippage
            fill_price = price_data["close"] * (1.0 - self._config.slippage_pct)
            self._close_position(ticker, current_date, fill_price, "signal")

    def _process_buys(
        self,
        current_date: date,
        prices: Dict[str, Dict[str, float]],
        signals: Dict[str, float],
        atr_values: Dict[str, float],
    ) -> None:
        """Open new positions for strong buy signals."""
        global_max_pos = self._config.max_positions

        if len(self._positions) >= global_max_pos:
            return

        # Rank tickers by signal strength (highest probability first)
        # Use per-ticker buy threshold when available
        buy_candidates = []
        for ticker, prob in signals.items():
            if ticker in self._positions or ticker not in prices:
                continue
            overrides = self._per_ticker_overrides.get(ticker, {})
            threshold = overrides.get("threshold_buy", self._config.threshold_buy)
            if prob >= threshold:
                buy_candidates.append((ticker, prob))
        buy_candidates.sort(key=lambda x: x[1], reverse=True)

        slots = global_max_pos - len(self._positions)
        for ticker, prob in buy_candidates[:slots]:
            overrides = self._per_ticker_overrides.get(ticker, {})

            # Per-ticker max_positions cap (global cap still applies)
            per_ticker_max = int(overrides.get("max_positions", global_max_pos))
            effective_max = min(global_max_pos, per_ticker_max)
            if len(self._positions) >= effective_max:
                break

            price_data = prices[ticker]
            close_price = price_data["close"]

            # Position sizing: fraction of equity (per-ticker override or config)
            size_fraction = overrides.get(
                "position_size_fraction", self._config.position_size_fraction,
            )
            equity = self._cash + sum(
                prices.get(t, {}).get("close", p.entry_price) * p.quantity
                for t, p in self._positions.items()
            )
            position_value = equity * size_fraction
            if position_value > self._cash:
                position_value = self._cash * 0.95  # Leave 5% cash buffer

            if position_value < 1.0:
                continue  # Not enough cash

            # Fill at close with slippage
            fill_price = close_price * (1.0 + self._config.slippage_pct)
            quantity = position_value / fill_price

            # Stop-loss and take-profit from ATR (per-ticker overrides)
            atr = atr_values.get(ticker, close_price * 0.02)
            atr_stop_mult = overrides.get(
                "atr_stop_multiplier", self._config.atr_stop_multiplier,
            )
            atr_profit_mult = overrides.get(
                "atr_profit_multiplier", self._config.atr_profit_multiplier,
            )
            stop_loss = fill_price - (atr * atr_stop_mult)
            take_profit = fill_price + (atr * atr_profit_mult)

            # Execute
            cost = fill_price * quantity + self._config.commission_per_trade
            if cost > self._cash:
                continue

            strategy_profile = str(overrides.get("strategy_profile", ""))

            self._cash -= cost
            self._positions[ticker] = Position(
                ticker=ticker,
                entry_date=current_date,
                entry_price=fill_price,
                quantity=quantity,
                stop_loss=stop_loss,
                take_profit=take_profit,
                signal_prob=prob,
                strategy_profile=strategy_profile,
            )

    def _close_position(
        self,
        ticker: str,
        exit_date: date,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        """Close a position and record the trade."""
        pos = self._positions.pop(ticker, None)
        if pos is None:
            return

        proceeds = exit_price * pos.quantity - self._config.commission_per_trade
        self._cash += proceeds

        pnl = (exit_price - pos.entry_price) * pos.quantity
        pnl_pct = (exit_price / pos.entry_price - 1.0) * 100.0
        hold_days = (exit_date - pos.entry_date).days

        self._trades.append(TradeRecord(
            ticker=ticker,
            entry_date=pos.entry_date,
            exit_date=exit_date,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_days=max(hold_days, 1),
            exit_reason=exit_reason,
            signal_prob=pos.signal_prob,
            strategy_profile=pos.strategy_profile,
        ))

    def _record_snapshot(
        self,
        current_date: date,
        prices: Dict[str, Dict[str, float]],
    ) -> None:
        """Record end-of-day portfolio snapshot."""
        # Mark positions to market
        position_value = sum(
            prices.get(t, {}).get("close", p.entry_price) * p.quantity
            for t, p in self._positions.items()
        )
        current_equity = self._cash + position_value

        # Track peak for drawdown
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        drawdown = (self._peak_equity - current_equity) / self._peak_equity if self._peak_equity > 0 else 0.0
        daily_return = (current_equity / self._prev_equity - 1.0) if self._prev_equity > 0 else 0.0

        self._snapshots.append(DailySnapshot(
            date=current_date,
            equity=current_equity,
            cash=self._cash,
            n_positions=len(self._positions),
            daily_return=daily_return,
            drawdown=drawdown,
        ))

        self._prev_equity = current_equity
