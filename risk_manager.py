from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from types_shared import ConsensusResult, RiskAssessment

logger = logging.getLogger(__name__)

# Default configuration for risk management parameters.
_DEFAULT_CONFIG: Dict[str, float | int] = {
    "kelly_fraction_cap": 0.25,
    "max_position_pct": 0.15,
    "atr_stop_multiplier": 2.0,
    "atr_profit_multiplier": 3.0,
    "drawdown_threshold": 0.10,
    "drawdown_size_reduction": 0.5,
    "min_position_dollars": 50.0,
    "max_open_positions": 10,
    "cash_buffer_pct": 0.05,
}


class RiskManager:
    """Portfolio-level risk management — the 'risk desk'.

    Handles position sizing (Kelly + volatility), stop/take-profit
    placement via ATR, drawdown protection, and portfolio-level
    concentration checks.
    """

    def __init__(self, config: Dict[str, float | int] | None = None) -> None:
        merged = dict(_DEFAULT_CONFIG)
        if config:
            merged.update(config)

        self._kelly_fraction_cap: float = float(merged["kelly_fraction_cap"])
        self._max_position_pct: float = float(merged["max_position_pct"])
        self._atr_stop_multiplier: float = float(merged["atr_stop_multiplier"])
        self._atr_profit_multiplier: float = float(merged["atr_profit_multiplier"])
        self._drawdown_threshold: float = float(merged["drawdown_threshold"])
        self._drawdown_size_reduction: float = float(merged["drawdown_size_reduction"])
        self._min_position_dollars: float = float(merged["min_position_dollars"])
        self._max_open_positions: int = int(merged["max_open_positions"])
        self._cash_buffer_pct: float = float(merged["cash_buffer_pct"])

    # ------------------------------------------------------------------
    # Core sizing helpers
    # ------------------------------------------------------------------

    def kelly_criterion(
        self, probability: float, win_loss_ratio: float = 1.5
    ) -> float:
        """Compute Kelly fraction for optimal bet sizing.

        Formula: f = (p * (b + 1) - 1) / b
        where p = win probability, b = win/loss ratio.

        The result is capped at *kelly_fraction_cap* and floored at 0.
        """
        if win_loss_ratio <= 0:
            return 0.0
        kelly = (probability * (win_loss_ratio + 1) - 1) / win_loss_ratio
        kelly = max(kelly, 0.0)
        kelly = min(kelly, self._kelly_fraction_cap)
        return kelly

    def volatility_adjusted_size(
        self,
        capital: float,
        atr: float,
        price: float,
        risk_pct: float = 0.02,
    ) -> float:
        """Compute dollar position size so that 1 ATR move equals *risk_pct* of capital.

        Shares = (capital * risk_pct) / atr
        Dollar value = shares * price
        """
        if atr <= 0 or price <= 0:
            return 0.0
        shares = (capital * risk_pct) / atr
        return shares * price

    # ------------------------------------------------------------------
    # Stop-loss / take-profit
    # ------------------------------------------------------------------

    def compute_stop_loss(
        self, entry_price: float, atr: float, side: str = "BUY"
    ) -> float:
        """ATR-based stop-loss level."""
        offset = atr * self._atr_stop_multiplier
        if side.upper() == "BUY":
            return round(entry_price - offset, 4)
        return round(entry_price + offset, 4)

    def compute_take_profit(
        self, entry_price: float, atr: float, side: str = "BUY"
    ) -> float:
        """ATR-based take-profit level."""
        offset = atr * self._atr_profit_multiplier
        if side.upper() == "BUY":
            return round(entry_price + offset, 4)
        return round(entry_price - offset, 4)

    # ------------------------------------------------------------------
    # Portfolio-level checks
    # ------------------------------------------------------------------

    def check_portfolio_risk(
        self,
        positions: List[Dict[str, Any]],
        account: Dict[str, Any],
        new_ticker: str,
        new_size_dollars: float,
    ) -> tuple[bool, str]:
        """Validate that a proposed position passes portfolio-level rules.

        Returns (allowed, reason).
        """
        total_capital: float = float(account.get("total", 0.0))
        if total_capital <= 0:
            return False, "Account total capital is zero or negative"

        # Check 1 — single-position concentration limit
        if new_size_dollars / total_capital > self._max_position_pct:
            return (
                False,
                f"{new_ticker}: position size {new_size_dollars:.0f} exceeds "
                f"{self._max_position_pct:.0%} of capital ({total_capital:.0f})",
            )

        # Check 2 — cash buffer: total invested must not exceed (1 - buffer) of capital
        total_invested: float = sum(
            float(p.get("currentValue", p.get("quantity", 0) * p.get("price", 0)))
            for p in positions
        )
        max_investable = total_capital * (1.0 - self._cash_buffer_pct)
        if total_invested + new_size_dollars > max_investable:
            return (
                False,
                f"Adding {new_size_dollars:.0f} would exceed "
                f"{1.0 - self._cash_buffer_pct:.0%} invested limit "
                f"(current: {total_invested:.0f}, max: {max_investable:.0f})",
            )

        # Check 3 — maximum open positions
        # Count unique tickers already held (exclude the new ticker in case of
        # top-ups, which are allowed under the concentration cap).
        held_tickers = {str(p.get("ticker", "")) for p in positions}
        open_count = len(held_tickers - {new_ticker})
        if open_count >= self._max_open_positions:
            return (
                False,
                f"Already at {open_count} open positions "
                f"(max {self._max_open_positions})",
            )

        return True, "OK"

    def check_drawdown_protection(
        self, account: Dict[str, Any], initial_capital: float
    ) -> float:
        """Return a size multiplier based on drawdown from peak capital.

        If the portfolio has drawn down beyond *drawdown_threshold* from
        *initial_capital*, return *drawdown_size_reduction* (e.g. 0.5 to
        halve position sizes).  Otherwise return 1.0 (no reduction).
        """
        current_total = float(account.get("total", initial_capital))
        if initial_capital <= 0:
            return 1.0
        drawdown = (initial_capital - current_total) / initial_capital
        if drawdown > self._drawdown_threshold:
            logger.warning(
                "Drawdown protection active: %.1f%% drawdown exceeds %.1f%% threshold — "
                "reducing position sizes by %.0f%%",
                drawdown * 100,
                self._drawdown_threshold * 100,
                (1.0 - self._drawdown_size_reduction) * 100,
            )
            return self._drawdown_size_reduction
        return 1.0

    # ------------------------------------------------------------------
    # Main position assessment
    # ------------------------------------------------------------------

    def assess_position(
        self,
        ticker: str,
        probability: float,
        confidence: float,
        price: float,
        atr: float,
        positions: List[Dict[str, Any]],
        account: Dict[str, Any],
        consensus: ConsensusResult | None = None,
    ) -> RiskAssessment:
        """Full position-sizing pipeline for a single proposed trade.

        Flow:
        1. Kelly fraction from probability
        2. Cap at kelly_fraction_cap
        3. Volatility-adjusted size from ATR
        4. Take minimum of (kelly_size, vol_size, max_position_cap)
        5. Apply drawdown multiplier
        6. Consensus disagreement penalty (if provided)
        7. Floor at min_position_dollars (or 0 if below)
        8. Compute share count
        """
        total_capital = float(account.get("total", 0.0))
        if total_capital <= 0 or price <= 0 or atr <= 0:
            return RiskAssessment(
                ticker=ticker,
                position_size_dollars=0.0,
                position_size_shares=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                kelly_fraction=0.0,
                risk_score=1.0,
                reason="Invalid inputs (capital, price, or ATR <= 0)",
            )

        # Step 1+2: Kelly fraction (already capped internally)
        kelly_f = self.kelly_criterion(probability)

        # Kelly-based dollar size
        kelly_size = kelly_f * total_capital

        # Step 3: Volatility-adjusted size
        vol_size = self.volatility_adjusted_size(total_capital, atr, price)

        # Step 4: Maximum position by concentration cap
        max_cap_size = self._max_position_pct * total_capital

        # Take the most conservative of the three sizing methods
        size_dollars = min(kelly_size, vol_size, max_cap_size)

        # Step 5: Drawdown protection multiplier
        dd_multiplier = self.check_drawdown_protection(account, total_capital)
        size_dollars *= dd_multiplier

        # Step 6: Consensus disagreement penalty
        if consensus is not None:
            disagreement_penalty = 1.0 - consensus.disagreement * 0.5
            disagreement_penalty = max(disagreement_penalty, 0.1)
            size_dollars *= disagreement_penalty

        # Step 7: Floor at minimum or zero
        if size_dollars < self._min_position_dollars:
            size_dollars = 0.0

        # Step 8: Shares from dollar size
        shares = math.floor(size_dollars / price) if size_dollars > 0 else 0.0

        # Recompute exact dollar exposure from whole shares
        position_dollars = shares * price

        # Stop-loss and take-profit
        stop_loss = self.compute_stop_loss(price, atr, side="BUY")
        take_profit = self.compute_take_profit(price, atr, side="BUY")

        # Risk score: 0 = low risk, 1 = high risk.  Blend of inverse
        # confidence and ATR-relative-to-price (higher vol = higher risk).
        atr_risk = min(atr / price, 1.0)
        risk_score = round(0.5 * (1.0 - confidence) + 0.5 * atr_risk, 4)

        reason_parts: List[str] = [
            f"kelly={kelly_f:.3f}",
            f"vol_size=${vol_size:.0f}",
            f"cap_limit=${max_cap_size:.0f}",
        ]
        if dd_multiplier < 1.0:
            reason_parts.append(f"dd_mult={dd_multiplier:.2f}")
        if consensus is not None:
            reason_parts.append(f"disagree={consensus.disagreement:.2f}")

        return RiskAssessment(
            ticker=ticker,
            position_size_dollars=round(position_dollars, 2),
            position_size_shares=float(shares),
            stop_loss=stop_loss,
            take_profit=take_profit,
            kelly_fraction=round(kelly_f, 4),
            risk_score=risk_score,
            reason=", ".join(reason_parts),
        )

    # ------------------------------------------------------------------
    # Order generation
    # ------------------------------------------------------------------

    def generate_risk_enhanced_orders(
        self,
        signals_df: pd.DataFrame,
        consensus: Dict[str, ConsensusResult],
        features_data: pd.DataFrame | None,
        positions: List[Dict[str, Any]],
        account: Dict[str, Any],
        prices: Dict[str, Dict[str, float]],
        initial_capital: float = 100_000.0,
    ) -> List[Dict[str, Any]]:
        """Generate sized orders from signal decisions, replacing naive qty=1 logic.

        For BUY signals: full risk assessment + portfolio checks, with ATR-based
        stops and targets.
        For SELL signals: liquidate the entire held position.

        Returns a list of order dicts suitable for broker submission.
        """
        orders: List[Dict[str, Any]] = []

        # Build a quick lookup of held tickers → position details
        held_map: Dict[str, Dict[str, Any]] = {}
        for pos in positions:
            t = str(pos.get("ticker", ""))
            if t:
                held_map[t] = pos

        for _, row in signals_df.iterrows():
            ticker: str = str(row.get("ticker", ""))
            signal: str = str(row.get("signal", "hold")).lower()

            if signal == "hold" or not ticker:
                continue

            # ----- SELL -----
            if signal == "sell":
                held = held_map.get(ticker)
                if held is None:
                    continue
                qty = float(held.get("quantity", 0))
                if qty <= 0:
                    continue
                orders.append(
                    {
                        "ticker": ticker,
                        "side": "SELL",
                        "quantity": qty,
                        "order_type": "MARKET",
                    }
                )
                continue

            # ----- BUY -----
            if signal != "buy":
                continue

            # Resolve current price
            price_info = prices.get(ticker, {})
            price = float(
                price_info.get("ask", price_info.get("last", price_info.get("price", 0)))
            )
            if price <= 0:
                logger.debug("Skipping %s: no valid price available", ticker)
                continue

            # Resolve ATR — prefer atr_14d from advanced features, fall back
            # to vol_5d from basic features, finally estimate from price.
            atr = self._resolve_atr(ticker, features_data, price)

            probability = float(row.get("prob_up", 0.5))
            cons = consensus.get(ticker)
            confidence = cons.confidence if cons else 0.5

            # Full position assessment
            assessment = self.assess_position(
                ticker=ticker,
                probability=probability,
                confidence=confidence,
                price=price,
                atr=atr,
                positions=positions,
                account=account,
                consensus=cons,
            )

            if assessment.position_size_shares <= 0:
                logger.info(
                    "Risk manager: skipping %s — sized to 0 (%s)",
                    ticker,
                    assessment.reason,
                )
                continue

            # Portfolio-level guard
            allowed, reason = self.check_portfolio_risk(
                positions=positions,
                account=account,
                new_ticker=ticker,
                new_size_dollars=assessment.position_size_dollars,
            )
            if not allowed:
                logger.info("Risk manager: blocked %s — %s", ticker, reason)
                continue

            orders.append(
                {
                    "ticker": ticker,
                    "side": "BUY",
                    "quantity": assessment.position_size_shares,
                    "order_type": "MARKET",
                    "stop_loss": assessment.stop_loss,
                    "take_profit": assessment.take_profit,
                }
            )

        return orders

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_atr(
        ticker: str,
        features_data: pd.DataFrame | None,
        price: float,
    ) -> float:
        """Extract ATR for *ticker* from feature data, with fallbacks.

        Priority:
        1. ``atr_14d`` column (from features_advanced)
        2. ``vol_5d`` column (5-day high-low range, rough proxy)
        3. 2% of price as a last-resort estimate
        """
        if features_data is not None and not features_data.empty:
            # features_data may be indexed by ticker or have a ticker column
            row = _extract_ticker_row(features_data, ticker)
            if row is not None:
                if "atr_14d" in row.index:
                    val = float(row["atr_14d"])
                    if not np.isnan(val) and val > 0:
                        return val
                if "vol_5d" in row.index:
                    val = float(row["vol_5d"])
                    if not np.isnan(val) and val > 0:
                        return val

        # Fallback: 2% of price
        return price * 0.02


def _extract_ticker_row(
    df: pd.DataFrame, ticker: str
) -> pd.Series | None:
    """Try to pull a single row for *ticker* from a features DataFrame.

    Handles both ticker-indexed DataFrames and those with a ``ticker``
    column.
    """
    # Case 1: ticker is in the index
    if ticker in df.index:
        row = df.loc[ticker]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        return row

    # Case 2: ticker column exists
    if "ticker" in df.columns:
        subset = df[df["ticker"] == ticker]
        if not subset.empty:
            return subset.iloc[-1]

    return None
