# Forecaster — Statistical

ARIMA + Holt-Winters ETS baseline forecasters via statsmodels. Provides classical time-series signals as the "statistical" family in the three-family meta-ensemble.

## Purpose

Complements the ML ensemble with traditional econometric models that capture autocorrelation and trend structure differently from tree/gradient boosting methods. Runs in parallel per ticker and degrades gracefully when `statsmodels` or `scipy` are absent.

## How It Works

For each ticker × horizon combination:
1. Extract the Close price series (up to 250 bars)
2. Fit ARIMA(1,1,1) — get forecast mean and standard error
3. Fit Holt-Winters ETS (additive trend, no seasonality) — get forecast price and residual std
4. Convert each model's forecast return distribution to P(up) via the normal CDF: `P(up) = Phi(mean / std)`
5. Blend: average probability and return, take minimum confidence
6. Return one `ForecasterSignal` per horizon per ticker

## Public API

```python
class StatisticalForecaster:
    is_available: bool  # True when statsmodels + scipy installed

    def fit_and_predict(
        universe_data: Dict[str, pd.DataFrame],
        horizons: List[int],
        on_progress: Callable | None,
    ) -> Dict[str, List[ForecasterSignal]]
```

## ForecasterSignal Fields

`family="statistical", ticker, probability, confidence, forecast_return, horizon_days, model_name="arima+ets"`

## Degradation

- No `statsmodels` or `scipy`: returns neutral signals (probability=0.5, confidence=0.0) for all tickers
- Fewer than 30 bars: returns neutral signals for that ticker
- Individual ARIMA/ETS fit failures: returns neutral for that model, blends what succeeded

## Configuration

```json
{
  "statistical_forecaster": {
    "arima_order": [1, 1, 1]
  }
}
```

## Dependencies

- `statsmodels` (optional — ARIMA, ExponentialSmoothing)
- `scipy.stats.norm` (optional — normal CDF for P(up))
- `cpu_config.get_cpu_cores()` — ThreadPoolExecutor max_workers
- `types_shared.ForecasterSignal`
