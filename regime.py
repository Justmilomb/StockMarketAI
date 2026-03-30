from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict

import numpy as np
import pandas as pd

from data_loader import fetch_ticker_data
from types_shared import RegimeState, RegimeType

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Market regime detector — classifies the current macro environment
    to inform feature weighting and strategy selection."""

    def __init__(self, config: Dict[str, int | str | float] | None = None) -> None:
        cfg = config or {}
        self._lookback_days: int = int(cfg.get("lookback_days", 60))
        self._spy_ticker: str = str(cfg.get("spy_ticker", "SPY"))
        self._regime_weight_adjustment: float = float(
            cfg.get("regime_weight_adjustment", 0.3)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self, universe_data: Dict[str, pd.DataFrame] | None = None
    ) -> RegimeState:
        """Run full regime detection pipeline and return the current state."""
        spy_data = self._fetch_spy_data()
        if spy_data.empty:
            logger.warning("SPY data unavailable — returning unknown regime")
            return RegimeState(
                regime="unknown",
                confidence=0.0,
                vix_proxy=0.0,
                breadth=50.0,
                trend_strength=0.0,
            )

        vix_proxy = self._compute_vix_proxy(spy_data)
        breadth = (
            self._compute_breadth(universe_data)
            if universe_data
            else 50.0  # neutral default when no universe supplied
        )
        trend_strength = self._compute_trend_strength(spy_data)

        regime, confidence = self._classify_regime(vix_proxy, breadth, trend_strength)

        return RegimeState(
            regime=regime,
            confidence=confidence,
            vix_proxy=vix_proxy,
            breadth=breadth,
            trend_strength=trend_strength,
        )

    def get_model_weight_adjustments(
        self, regime: RegimeState
    ) -> Dict[str, float]:
        """Return per-feature-group weight multipliers for the given regime."""
        weight_table: Dict[RegimeType, Dict[str, float]] = {
            "trending_up": {
                "trend": 1.3,
                "momentum": 1.2,
                "volatility": 0.8,
                "volume": 1.0,
            },
            "trending_down": {
                "trend": 1.3,
                "momentum": 1.2,
                "volatility": 0.8,
                "volume": 1.0,
            },
            "mean_reverting": {
                "trend": 0.7,
                "momentum": 0.8,
                "volatility": 1.3,
                "volume": 1.1,
            },
            "high_volatility": {
                "trend": 0.6,
                "momentum": 0.7,
                "volatility": 1.4,
                "volume": 1.2,
            },
            "unknown": {
                "trend": 1.0,
                "momentum": 1.0,
                "volatility": 1.0,
                "volume": 1.0,
            },
        }

        base = weight_table.get(regime.regime, weight_table["unknown"])

        # Multi-timeframe and price groups are always neutral
        result: Dict[str, float] = {**base, "multi_tf": 1.0, "price": 1.0}
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_spy_data(self) -> pd.DataFrame:
        """Fetch SPY history covering the lookback window plus ADX warm-up."""
        # ADX(14) needs ~40 extra bars to stabilise, plus the 20-day vol window
        buffer_days = 60
        calendar_days = int((self._lookback_days + buffer_days) * 1.5)

        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=calendar_days)

        try:
            df = fetch_ticker_data(
                ticker=self._spy_ticker,
                start_date=start_dt.strftime("%Y-%m-%d"),
                end_date=end_dt.strftime("%Y-%m-%d"),
                use_cache=True,
            )
            return df
        except Exception as exc:
            logger.error("Failed to fetch SPY data: %s", exc)
            return pd.DataFrame()

    def _compute_vix_proxy(self, spy_data: pd.DataFrame) -> float:
        """Annualised 20-day realised volatility of SPY daily returns (%)."""
        if len(spy_data) < 21:
            return 0.0

        daily_returns = pd.to_numeric(spy_data["Close"], errors="coerce").pct_change().dropna()
        rolling_std = daily_returns.rolling(window=20).std()
        latest_std = rolling_std.iloc[-1]

        if pd.isna(latest_std):
            return 0.0

        annualised = float(latest_std) * np.sqrt(252) * 100.0
        return round(annualised, 2)

    def _compute_breadth(self, universe_data: Dict[str, pd.DataFrame]) -> float:
        """Percentage of universe tickers whose latest close is above their 50-day MA."""
        if not universe_data:
            return 50.0

        above_count = 0
        valid_count = 0

        for _ticker, df in universe_data.items():
            if df.empty or len(df) < 50 or "Close" not in df.columns:
                continue

            close_numeric = pd.to_numeric(df["Close"], errors="coerce")
            ma_50 = close_numeric.rolling(window=50).mean()
            latest_close = close_numeric.iloc[-1]
            latest_ma = ma_50.iloc[-1]

            if pd.isna(latest_close) or pd.isna(latest_ma):
                continue

            valid_count += 1
            if float(latest_close) > float(latest_ma):
                above_count += 1

        if valid_count == 0:
            return 50.0

        return round((above_count / valid_count) * 100.0, 2)

    def _compute_trend_strength(self, spy_data: pd.DataFrame) -> float:
        """Compute ADX(14) on SPY — measures trend strength on a 0-100 scale."""
        period = 14
        # Need at least 2*period rows for a meaningful ADX
        if len(spy_data) < period * 3:
            return 0.0

        high = pd.to_numeric(spy_data["High"], errors="coerce").fillna(method="ffill").values
        low = pd.to_numeric(spy_data["Low"], errors="coerce").fillna(method="ffill").values
        close = pd.to_numeric(spy_data["Close"], errors="coerce").fillna(method="ffill").values
        n = len(high)

        # Step 1: True Range, +DM, -DM (raw, per-bar)
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)

        for i in range(1, n):
            h_diff = high[i] - high[i - 1]
            l_diff = low[i - 1] - low[i]

            # True Range
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

            # Directional movement
            if h_diff > l_diff and h_diff > 0:
                plus_dm[i] = h_diff
            if l_diff > h_diff and l_diff > 0:
                minus_dm[i] = l_diff

        # Step 2: Wilder smoothing for ATR, +DM, -DM
        atr = np.zeros(n)
        smooth_plus_dm = np.zeros(n)
        smooth_minus_dm = np.zeros(n)

        # Seed with simple sum of first 'period' values (bars 1..period)
        atr[period] = np.sum(tr[1 : period + 1])
        smooth_plus_dm[period] = np.sum(plus_dm[1 : period + 1])
        smooth_minus_dm[period] = np.sum(minus_dm[1 : period + 1])

        for i in range(period + 1, n):
            atr[i] = atr[i - 1] - (atr[i - 1] / period) + tr[i]
            smooth_plus_dm[i] = (
                smooth_plus_dm[i - 1] - (smooth_plus_dm[i - 1] / period) + plus_dm[i]
            )
            smooth_minus_dm[i] = (
                smooth_minus_dm[i - 1]
                - (smooth_minus_dm[i - 1] / period)
                + minus_dm[i]
            )

        # Step 3: +DI, -DI, DX
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

        # Step 4: ADX — Wilder smoothing of DX
        adx = np.zeros(n)
        adx_start = period * 2  # first valid ADX index

        if adx_start >= n:
            return 0.0

        # Seed ADX with mean of DX values from period .. 2*period-1
        adx[adx_start] = np.mean(dx[period : adx_start + 1])

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
        """Classify the market regime and estimate confidence."""
        # High volatility takes priority — stress dominates all other signals
        if vix_proxy > 30:
            overshoot = min((vix_proxy - 30) / 20.0, 1.0)  # scale 30-50 -> 0-1
            confidence = 0.5 + 0.5 * overshoot
            return "high_volatility", round(confidence, 3)

        # Strong trend with broad participation -> trending up
        if trend_strength > 25 and breadth > 60:
            confidence = min(trend_strength / 100.0, 1.0)
            return "trending_up", round(confidence, 3)

        # Strong trend with weak breadth -> trending down
        if trend_strength > 25 and breadth < 40:
            confidence = min(trend_strength / 100.0, 1.0)
            return "trending_down", round(confidence, 3)

        # No dominant trend -> mean-reverting / range-bound
        confidence = max(1.0 - trend_strength / 100.0, 0.0)
        return "mean_reverting", round(confidence, 3)
