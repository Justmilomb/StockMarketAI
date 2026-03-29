"""BTC-based regime detection for crypto markets.

Instead of using SPY/VIX as the macro benchmark (as the stock regime
detector does), this module uses BTC price action to classify the crypto
market regime:

  - bull_run:       BTC trending up strongly   -> trending_up
  - bear_market:    BTC trending down           -> trending_down
  - high_volatility: BTC realised vol spike     -> high_volatility
  - accumulation:   low trend, range-bound      -> mean_reverting

Returns the existing ``RegimeState`` dataclass from ``types_shared``.
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

from types_shared import RegimeState, RegimeType

logger = logging.getLogger(__name__)


class CryptoRegimeDetector:
    """Crypto market regime detector based on BTC price behaviour."""

    def __init__(self, config: Dict[str, int | str | float] | None = None) -> None:
        cfg = config or {}
        self._lookback_days: int = int(cfg.get("lookback_days", 60))
        self._benchmark_pair: str = str(cfg.get("benchmark_ticker", "BTC/USDT"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        btc_data: pd.DataFrame | None = None,
        universe_data: Dict[str, pd.DataFrame] | None = None,
    ) -> RegimeState:
        """Run crypto regime detection and return the current state.

        Args:
            btc_data: BTC OHLCV DataFrame (columns: Open, High, Low, Close, Volume).
                If None, returns an unknown regime.
            universe_data: Optional dict of pair -> DataFrame for breadth calc.
        """
        if btc_data is None or btc_data.empty:
            logger.warning("BTC data unavailable -- returning unknown regime")
            return RegimeState(
                regime="unknown",
                confidence=0.0,
                vix_proxy=0.0,
                breadth=50.0,
                trend_strength=0.0,
            )

        vix_proxy = self._compute_realised_vol(btc_data)
        breadth = (
            self._compute_breadth(universe_data)
            if universe_data
            else 50.0
        )
        trend_strength = self._compute_trend_strength(btc_data)

        regime, confidence = self._classify_regime(vix_proxy, breadth, trend_strength)

        return RegimeState(
            regime=regime,
            confidence=confidence,
            vix_proxy=vix_proxy,
            breadth=breadth,
            trend_strength=trend_strength,
        )

    def get_model_weight_adjustments(
        self, regime: RegimeState,
    ) -> Dict[str, float]:
        """Return per-feature-group weight multipliers for the given regime.

        Includes the 'crypto' group which gets boosted in high vol.
        """
        weight_table: Dict[RegimeType, Dict[str, float]] = {
            "trending_up": {
                "trend": 1.3, "momentum": 1.3, "volatility": 0.7,
                "volume": 1.0, "crypto": 1.2,
            },
            "trending_down": {
                "trend": 1.3, "momentum": 1.1, "volatility": 0.9,
                "volume": 1.0, "crypto": 1.2,
            },
            "mean_reverting": {
                "trend": 0.7, "momentum": 0.8, "volatility": 1.3,
                "volume": 1.1, "crypto": 1.0,
            },
            "high_volatility": {
                "trend": 0.5, "momentum": 0.6, "volatility": 1.5,
                "volume": 1.2, "crypto": 1.4,
            },
            "unknown": {
                "trend": 1.0, "momentum": 1.0, "volatility": 1.0,
                "volume": 1.0, "crypto": 1.0,
            },
        }

        base = weight_table.get(regime.regime, weight_table["unknown"])
        return {**base, "multi_tf": 1.0, "price": 1.0}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_realised_vol(self, btc_data: pd.DataFrame) -> float:
        """Annualised 20-day realised volatility of BTC daily returns (%).

        Crypto trades 365 days/year, so annualisation uses sqrt(365).
        """
        if len(btc_data) < 21:
            return 0.0

        daily_returns = btc_data["Close"].pct_change().dropna()
        rolling_std = daily_returns.rolling(window=20).std()
        latest_std = rolling_std.iloc[-1]

        if pd.isna(latest_std):
            return 0.0

        # 365 trading days for crypto (24/7 market)
        annualised = float(latest_std) * np.sqrt(365) * 100.0
        return round(annualised, 2)

    def _compute_breadth(self, universe_data: Dict[str, pd.DataFrame]) -> float:
        """Percentage of crypto pairs whose close is above their 20-day MA.

        Uses a shorter 20-day window (vs 50 for stocks) because crypto
        trends develop and reverse faster.
        """
        if not universe_data:
            return 50.0

        above_count = 0
        valid_count = 0

        for _pair, df in universe_data.items():
            if df.empty or len(df) < 20 or "Close" not in df.columns:
                continue

            ma_20 = df["Close"].rolling(window=20).mean()
            latest_close = df["Close"].iloc[-1]
            latest_ma = ma_20.iloc[-1]

            if pd.isna(latest_close) or pd.isna(latest_ma):
                continue

            valid_count += 1
            if float(latest_close) > float(latest_ma):
                above_count += 1

        if valid_count == 0:
            return 50.0

        return round((above_count / valid_count) * 100.0, 2)

    def _compute_trend_strength(self, btc_data: pd.DataFrame) -> float:
        """Compute ADX(14) on BTC -- measures trend strength (0-100 scale).

        Mirrors the stock RegimeDetector implementation.
        """
        period = 14
        if len(btc_data) < period * 3:
            return 0.0

        high = btc_data["High"].values.astype(float)
        low = btc_data["Low"].values.astype(float)
        close = btc_data["Close"].values.astype(float)
        n = len(high)

        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)

        for i in range(1, n):
            h_diff = high[i] - high[i - 1]
            l_diff = low[i - 1] - low[i]
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            if h_diff > l_diff and h_diff > 0:
                plus_dm[i] = h_diff
            if l_diff > h_diff and l_diff > 0:
                minus_dm[i] = l_diff

        atr = np.zeros(n)
        smooth_plus_dm = np.zeros(n)
        smooth_minus_dm = np.zeros(n)

        atr[period] = np.sum(tr[1: period + 1])
        smooth_plus_dm[period] = np.sum(plus_dm[1: period + 1])
        smooth_minus_dm[period] = np.sum(minus_dm[1: period + 1])

        for i in range(period + 1, n):
            atr[i] = atr[i - 1] - (atr[i - 1] / period) + tr[i]
            smooth_plus_dm[i] = smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / period) + plus_dm[i]
            smooth_minus_dm[i] = smooth_minus_dm[i - 1] - (smooth_minus_dm[i - 1] / period) + minus_dm[i]

        plus_di = np.zeros(n)
        minus_di = np.zeros(n)
        dx = np.zeros(n)

        for i in range(period, n):
            if atr[i] != 0:
                plus_di[i] = (smooth_plus_dm[i] / atr[i]) * 100.0
                minus_di[i] = (smooth_minus_dm[i] / atr[i]) * 100.0
            di_sum = plus_di[i] + minus_di[i]
            if di_sum != 0:
                dx[i] = (abs(plus_di[i] - minus_di[i]) / di_sum) * 100.0

        adx = np.zeros(n)
        adx_start = period * 2
        if adx_start >= n:
            return 0.0

        adx[adx_start] = np.mean(dx[period: adx_start + 1])
        for i in range(adx_start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

        latest_adx = adx[-1]
        if np.isnan(latest_adx):
            return 0.0

        return round(float(latest_adx), 2)

    def _classify_regime(
        self,
        vix_proxy: float,
        breadth: float,
        trend_strength: float,
    ) -> tuple[RegimeType, float]:
        """Classify the crypto market regime.

        Thresholds are higher than stocks because crypto is inherently
        more volatile (typical BTC realised vol is 40-80% vs 15-25% for SPY).
        """
        # High volatility: BTC annualised vol above 80% is a stress signal
        if vix_proxy > 80:
            overshoot = min((vix_proxy - 80) / 40.0, 1.0)
            confidence = 0.5 + 0.5 * overshoot
            return "high_volatility", round(confidence, 3)

        # Bull run: strong trend + broad participation
        if trend_strength > 25 and breadth > 60:
            confidence = min(trend_strength / 100.0, 1.0)
            return "trending_up", round(confidence, 3)

        # Bear market: strong trend + weak breadth
        if trend_strength > 25 and breadth < 40:
            confidence = min(trend_strength / 100.0, 1.0)
            return "trending_down", round(confidence, 3)

        # Accumulation / range-bound
        confidence = max(1.0 - trend_strength / 100.0, 0.0)
        return "mean_reverting", round(confidence, 3)
