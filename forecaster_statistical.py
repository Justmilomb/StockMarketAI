"""Statistical baseline forecasters — ARIMA + ETS.

Provides classical time-series models as a complementary signal family
alongside the ML ensemble and deep-learning forecasters.  Each model
fits independently per ticker and produces a ForecasterSignal with
calibrated P(up), expected return, and confidence.

When *statsmodels* is not installed the module degrades gracefully:
every method returns neutral signals (probability = 0.5).
"""

from __future__ import annotations

import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

from types_shared import ForecasterSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation for optional statsmodels / scipy
# ---------------------------------------------------------------------------

_HAS_STATSMODELS = False
try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    _HAS_STATSMODELS = True
except ImportError:
    pass

_HAS_SCIPY = False
try:
    from scipy.stats import norm

    _HAS_SCIPY = True
except ImportError:
    pass

# Maximum history length fed to the models (keeps fitting fast)
_MAX_HISTORY = 250

# Probability clamp bounds — avoids extreme certainty
_PROB_FLOOR = 0.05
_PROB_CEIL = 0.95

_NEUTRAL_PROB = 0.5
_NEUTRAL_RETURN = 0.0
_NEUTRAL_CONF = 0.0

from cpu_config import get_cpu_cores

_MAX_WORKERS = get_cpu_cores()


class StatisticalForecaster:
    """ARIMA + ETS statistical baseline forecaster.

    Fits both models per ticker per horizon, blends them into a single
    ForecasterSignal, and returns the full universe of signals keyed by
    ticker.  Uses thread-level parallelism for speed.
    """

    def __init__(self, config: Dict[str, object] | None = None) -> None:
        cfg = config or {}
        raw_order = cfg.get("arima_order", [1, 1, 1])
        self._arima_order: Tuple[int, int, int] = tuple(int(x) for x in raw_order)  # type: ignore[assignment]
        self._cache_dir: str = str(cfg.get("cache_dir", "models/statistical"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True when statsmodels is installed and models can be fitted."""
        return _HAS_STATSMODELS

    def fit_and_predict(
        self,
        universe_data: Dict[str, pd.DataFrame],
        horizons: List[int],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> Dict[str, List[ForecasterSignal]]:
        """Fit ARIMA + ETS for every ticker and horizon, returning blended signals.

        Args:
            universe_data: ``{ticker: DataFrame}`` with OHLCV columns and
                a DatetimeIndex.
            horizons: List of forecast horizons in trading days (e.g. [1, 5, 20]).
            on_progress: Optional callback ``(current_idx, total, ticker)`` for
                TUI progress bars.

        Returns:
            ``{ticker: [ForecasterSignal, ...]}`` — one signal per horizon
            per ticker.
        """
        tickers = list(universe_data.keys())
        total = len(tickers)
        results: Dict[str, List[ForecasterSignal]] = {}

        if not _HAS_STATSMODELS or not _HAS_SCIPY:
            logger.warning(
                "statsmodels or scipy not installed — returning neutral signals"
            )
            for idx, ticker in enumerate(tickers):
                results[ticker] = self._neutral_signals(ticker, horizons)
                if on_progress is not None:
                    on_progress(idx + 1, total, ticker)
            return results

        # Build work items — extract close series once
        work: Dict[str, pd.Series] = {}
        for ticker, df in universe_data.items():
            close = self._extract_close(df)
            if close is not None and len(close) >= 30:
                work[ticker] = close
            else:
                results[ticker] = self._neutral_signals(ticker, horizons)

        # Parallel fitting across tickers
        completed = len(results)
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {
                pool.submit(self._fit_single_ticker, ticker, close, horizons): ticker
                for ticker, close in work.items()
            }
            for future in as_completed(futures):
                ticker = futures[future]
                completed += 1
                try:
                    signals = future.result()
                    results[ticker] = signals
                except Exception:
                    logger.exception("Statistical forecaster failed for %s", ticker)
                    results[ticker] = self._neutral_signals(ticker, horizons)
                if on_progress is not None:
                    on_progress(completed, total, ticker)

        return results

    # ------------------------------------------------------------------
    # Per-ticker fitting
    # ------------------------------------------------------------------

    def _fit_single_ticker(
        self,
        ticker: str,
        close_prices: pd.Series,
        horizons: List[int],
    ) -> List[ForecasterSignal]:
        """Fit ARIMA and ETS for each horizon and blend into one signal per horizon."""
        signals: List[ForecasterSignal] = []

        for horizon in horizons:
            arima_prob, arima_ret, arima_conf = self._fit_arima(close_prices, horizon)
            ets_prob, ets_ret, ets_conf = self._fit_ets(close_prices, horizon)

            # Blend: average probability and return, take min confidence
            blended_prob = (arima_prob + ets_prob) / 2.0
            blended_ret = (arima_ret + ets_ret) / 2.0
            blended_conf = min(arima_conf, ets_conf)

            signals.append(
                ForecasterSignal(
                    family="statistical",
                    ticker=ticker,
                    probability=blended_prob,
                    confidence=blended_conf,
                    forecast_return=blended_ret,
                    horizon_days=horizon,
                    model_name="arima+ets",
                )
            )

        return signals

    # ------------------------------------------------------------------
    # ARIMA
    # ------------------------------------------------------------------

    def _fit_arima(
        self, close_prices: pd.Series, horizon: int
    ) -> Tuple[float, float, float]:
        """Fit ARIMA and return (probability, forecast_return, confidence).

        On any fitting failure returns neutral values.
        """
        try:
            series = close_prices.iloc[-_MAX_HISTORY:]
            # Suppress convergence warnings that are expected for some tickers
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ARIMA(series, order=self._arima_order)
                fitted = model.fit()

            forecast_obj = fitted.get_forecast(steps=horizon)
            forecast_mean = forecast_obj.predicted_mean.iloc[-1]
            forecast_se = forecast_obj.se_mean.iloc[-1]

            current_price = float(series.iloc[-1])
            if current_price <= 0:
                return _NEUTRAL_PROB, _NEUTRAL_RETURN, _NEUTRAL_CONF

            forecast_return = (forecast_mean - current_price) / current_price
            forecast_std = forecast_se / current_price

            probability = self._returns_to_probability(forecast_return, forecast_std)
            confidence = min(1.0, abs(probability - 0.5) * 4.0)

            return probability, float(forecast_return), confidence

        except Exception:
            logger.debug("ARIMA fit failed for horizon=%d", horizon, exc_info=True)
            return _NEUTRAL_PROB, _NEUTRAL_RETURN, _NEUTRAL_CONF

    # ------------------------------------------------------------------
    # ETS (Holt-Winters Exponential Smoothing)
    # ------------------------------------------------------------------

    def _fit_ets(
        self, close_prices: pd.Series, horizon: int
    ) -> Tuple[float, float, float]:
        """Fit Exponential Smoothing and return (probability, forecast_return, confidence).

        On any fitting failure returns neutral values.
        """
        try:
            series = close_prices.iloc[-_MAX_HISTORY:]

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ExponentialSmoothing(
                    series,
                    trend="add",
                    seasonal=None,
                )
                fitted = model.fit(optimized=True)

            forecast_values = fitted.forecast(steps=horizon)
            forecast_price = float(forecast_values.iloc[-1])

            current_price = float(series.iloc[-1])
            if current_price <= 0:
                return _NEUTRAL_PROB, _NEUTRAL_RETURN, _NEUTRAL_CONF

            forecast_return = (forecast_price - current_price) / current_price

            # ETS does not produce a standard error directly from forecast();
            # approximate from the residual standard deviation scaled by sqrt(horizon).
            residuals = fitted.resid.dropna()
            if len(residuals) > 1:
                residual_std = float(residuals.std())
                forecast_std = (residual_std * np.sqrt(horizon)) / current_price
            else:
                forecast_std = 0.0

            probability = self._returns_to_probability(forecast_return, forecast_std)
            confidence = min(1.0, abs(probability - 0.5) * 4.0)

            return probability, float(forecast_return), confidence

        except Exception:
            logger.debug("ETS fit failed for horizon=%d", horizon, exc_info=True)
            return _NEUTRAL_PROB, _NEUTRAL_RETURN, _NEUTRAL_CONF

    # ------------------------------------------------------------------
    # Probability conversion
    # ------------------------------------------------------------------

    def _returns_to_probability(
        self, forecast_mean: float, forecast_std: float
    ) -> float:
        """Convert a return distribution to P(up) via the normal CDF.

        ``P(up) = 1 - Phi(-mean / std)`` which equals ``Phi(mean / std)``.

        Returns 0.5 when the standard error is zero, NaN, or scipy is
        unavailable.  The result is clamped to ``[0.05, 0.95]``.
        """
        if not _HAS_SCIPY:
            return _NEUTRAL_PROB

        if forecast_std is None or np.isnan(forecast_std) or forecast_std <= 0:
            # No uncertainty estimate — fall back to sign of mean
            if forecast_mean > 0:
                return min(_PROB_CEIL, 0.5 + abs(forecast_mean) * 10)
            elif forecast_mean < 0:
                return max(_PROB_FLOOR, 0.5 - abs(forecast_mean) * 10)
            return _NEUTRAL_PROB

        z = forecast_mean / forecast_std
        prob = float(norm.cdf(z))
        return float(np.clip(prob, _PROB_FLOOR, _PROB_CEIL))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_close(df: pd.DataFrame) -> pd.Series | None:
        """Pull the Close series from a DataFrame, returning None if missing."""
        if "Close" in df.columns:
            series = df["Close"].dropna()
            if len(series) == 0:
                return None
            return series
        return None

    @staticmethod
    def _neutral_signals(
        ticker: str, horizons: List[int]
    ) -> List[ForecasterSignal]:
        """Generate neutral ForecasterSignals when models cannot be fitted."""
        return [
            ForecasterSignal(
                family="statistical",
                ticker=ticker,
                probability=_NEUTRAL_PROB,
                confidence=_NEUTRAL_CONF,
                forecast_return=_NEUTRAL_RETURN,
                horizon_days=h,
                model_name="arima+ets",
            )
            for h in horizons
        ]
