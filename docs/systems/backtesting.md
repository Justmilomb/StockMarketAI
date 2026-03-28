# Backtesting Engine

Walk-forward validation system that replays historical signals against price data to measure real out-of-sample performance before going live.

## Architecture

```
backtest.py (CLI)
  └─ BacktestRunner
       ├─ data_loader.fetch_universe_data()    # OHLCV from yfinance
       ├─ data_prep.prepare_backtest_data()    # V2 features + labels
       ├─ data_prep.generate_walk_forward_splits()
       ├─ BacktestEngine.run_fold() × N folds  # parallel or serial
       │   ├─ split_data_for_fold()
       │   ├─ _train_fold_ensemble()           # EnsembleModel or SimpleEnsemble
       │   ├─ _predict_test_period()           # per-day per-ticker P(up)
       │   └─ TradeSimulator.process_day()     # (full mode only)
       │       ├─ _check_stops()               # SL/TP vs intraday H/L
       │       ├─ _process_sells()             # signal < threshold_sell
       │       ├─ _process_buys()              # signal > threshold_buy, ranked
       │       └─ _record_snapshot()           # equity, drawdown, daily return
       └─ compute_metrics()                    # aggregate all folds
```

## Two Modes

| Mode | What it does | Speed |
|------|-------------|-------|
| `fast` | Train/predict each fold, measure accuracy/precision/recall. No trades. | Minutes |
| `full` | Same + day-by-day trade simulation with P&L, stops, slippage. | Longer |

## Walk-Forward Validation

**Expanding window** (default): each fold trains on all data from start to train_end, then tests on the next `test_window_days`. The training window grows each fold.

**Rolling window** (`--rolling`): training window stays fixed at `min_train_days`, sliding forward each step.

```
Fold 0: [=====TRAIN=====][TEST]
Fold 1: [========TRAIN========][TEST]
Fold 2: [===========TRAIN===========][TEST]
```

## Trade Simulation

- **Position sizing:** `equity × position_size_fraction` (default 12%), capped to 95% of cash
- **Slippage:** buy at `close × 1.001`, sell at `close × 0.999`
- **Stop-loss:** `entry - ATR × 1.5` — triggered by intraday low
- **Take-profit:** `entry + ATR × 2.0` — triggered by intraday high
- **Commission:** £0 (Trading 212 is commission-free)
- **Max positions:** 8 concurrent
- **End-of-fold:** all positions force-closed at last day's close

## Performance Metrics

**Returns:** total return, annualised return, buy-and-hold comparison
**Risk-adjusted:** Sharpe ratio, Sortino ratio, Calmar ratio
**Drawdown:** max drawdown %, avg drawdown %, max drawdown duration (days)
**Trades:** win rate, profit factor, avg win/loss %, best/worst trade, avg hold days
**Signal quality:** accuracy, precision, recall (from fast-mode predictions)
**Attribution:** win rate by signal probability band (>0.70, 0.55-0.70, 0.50-0.55)

## CLI Usage

```bash
python backtest.py                          # Full backtest, all watchlist tickers
python backtest.py --fast                   # Signal-accuracy-only
python backtest.py --ticker TSLA AAPL       # Specific tickers
python backtest.py --start 2020-01-01       # Custom date range
python backtest.py --folds                  # Per-fold breakdown table
python backtest.py --rolling                # Rolling instead of expanding window
python backtest.py --cores 4               # Limit parallelism
python backtest.py --json                  # Machine-readable output
python backtest.py -v                      # Debug logging
```

## Files

| File | Purpose |
|------|---------|
| `backtest.py` | CLI entry point, arg parsing, config building |
| `backtesting/types.py` | All dataclasses (config, splits, trades, metrics) |
| `backtesting/data_prep.py` | Feature pre-computation, walk-forward split generation |
| `backtesting/simulator.py` | TradeSimulator — stops, slippage, sizing, equity tracking |
| `backtesting/engine.py` | BacktestEngine — per-fold train/predict/simulate |
| `backtesting/metrics.py` | Sharpe, Sortino, Calmar, drawdown, attribution, text report |
| `backtesting/runner.py` | BacktestRunner — parallel fold executor, data loading |

## Parallelism

Folds run across all CPU cores via `ProcessPoolExecutor`. Data is serialised to dicts (not raw DataFrames) for safe cross-process transfer. Falls back to serial execution if multiprocessing fails.

## Ensemble Training

Each fold trains a fresh ensemble. Tries `EnsembleModel` (12 models) first, falls back to `SimpleEnsemble` (RandomForest + GradientBoosting + LogisticRegression) if imports fail.
