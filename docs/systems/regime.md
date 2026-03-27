# Regime (Market Regime Detector)

## Purpose
Classifies the current market environment using SPY macro indicators. Provides per-feature-group weight adjustments to re-tune ensemble predictions for the detected regime.

## Regime Types
| Regime | Condition | Weight Adjustments |
|--------|-----------|-------------------|
| trending_up | ADX>25, breadth>60% | trend 1.3x, momentum 1.2x, vol 0.8x |
| trending_down | ADX>25, breadth<40% | trend 1.3x, momentum 1.2x, vol 0.8x |
| mean_reverting | Low ADX (default) | trend 0.7x, vol 1.3x, volume 1.1x |
| high_volatility | VIX proxy>30% | trend 0.6x, momentum 0.7x, vol 1.4x |

## Three Macro Signals
1. **VIX Proxy** — 20-day rolling std of SPY returns, annualised (%)
2. **Breadth** — % of universe tickers above their 50-day MA
3. **Trend Strength** — ADX(14) on SPY (Wilder's smoothing, 0-100)

## Public API
- `RegimeDetector.detect(universe_data?) -> RegimeState` — Full detection pipeline
- `RegimeDetector.get_model_weight_adjustments(regime) -> Dict[str, float]` — Per-group multipliers

## Configuration
- regime.lookback_days (60), regime.spy_ticker ("SPY")

## Dependencies
- data_loader.py, types_shared.py, pandas, numpy
