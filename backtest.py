"""CLI entry point for backtesting.

Usage:
    python backtest.py                        # Full backtest, all watchlist tickers
    python backtest.py --fast                  # Signal-accuracy-only (no trades)
    python backtest.py --ticker TSLA AAPL      # Specific tickers
    python backtest.py --start 2020-01-01      # Custom date range
    python backtest.py --folds                 # Print fold-by-fold breakdown
    python backtest.py --cores 4               # Limit parallelism
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from typing import List

# Suppress sklearn internal parallelism warnings + deprecations
warnings.filterwarnings("ignore", category=UserWarning, module=r"sklearn\..*")
warnings.filterwarnings("ignore", category=FutureWarning, module=r"sklearn\..*")

from backtesting.metrics import format_report
from backtesting.runner import BacktestRunner
from backtesting.types import BacktestConfig


def _build_config(args: argparse.Namespace) -> BacktestConfig:
    """Build BacktestConfig from CLI args + config.json defaults."""
    # Load config.json for defaults
    cfg: dict = {}
    try:
        with open("config.json") as f:
            cfg = json.load(f)
    except Exception:
        pass

    strategy = cfg.get("strategy", {})
    risk = cfg.get("risk", {})
    bt_cfg = cfg.get("backtesting", {})

    # Resolve tickers
    tickers: List[str] = []
    if args.ticker:
        tickers = args.ticker
    else:
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        tickers = watchlists.get(active, cfg.get("tickers", []))

    return BacktestConfig(
        start_date=args.start or bt_cfg.get("start_date", cfg.get("start_date", "2018-01-01")),
        end_date=args.end or bt_cfg.get("end_date", cfg.get("end_date", "2026-03-27")),
        tickers=tickers,
        min_train_days=args.train_days,
        test_window_days=args.test_days,
        step_days=args.step_days,
        expanding_window=not args.rolling,
        initial_capital=cfg.get("capital", 100_000),
        max_positions=strategy.get("max_positions", 8),
        position_size_fraction=strategy.get("position_size_fraction", 0.12),
        threshold_buy=strategy.get("threshold_buy", 0.55),
        threshold_sell=strategy.get("threshold_sell", 0.45),
        slippage_pct=args.slippage,
        commission_per_trade=0.0,
        use_stops=not args.no_stops,
        atr_stop_multiplier=risk.get("atr_stop_multiplier", 1.5),
        atr_profit_multiplier=risk.get("atr_profit_multiplier", 2.0),
        use_mirofish=False,
        n_processes=args.cores,
        mode="fast" if args.fast else "full",
    )


def _print_fold_breakdown(result: "BacktestResult") -> None:
    """Print per-fold summary table."""
    from backtesting.types import BacktestResult

    print("\n" + "-" * 70)
    print("  FOLD-BY-FOLD BREAKDOWN")
    print("-" * 70)
    print(
        f"  {'Fold':>4}  {'Train':>12}  {'Test':>12}  "
        f"{'Acc':>6}  {'Prec':>6}  {'Trades':>6}  {'PnL':>8}"
    )
    print("  " + "-" * 64)

    for fold in result.folds:
        s = fold.split
        n_trades = len(fold.trades)
        total_pnl = sum(t.pnl for t in fold.trades)
        print(
            f"  {fold.fold_id:>4}  "
            f"{s.train_start}->{s.train_end}  "
            f"{s.test_start}->{s.test_end}  "
            f"{fold.accuracy:>5.1%}  "
            f"{fold.precision:>5.1%}  "
            f"{n_trades:>6}  "
            f"{total_pnl:>+8.0f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest for StockMarketAI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Signal-accuracy-only mode (no trade simulation)",
    )
    parser.add_argument(
        "--ticker", nargs="+", metavar="SYM",
        help="Tickers to backtest (default: watchlist from config.json)",
    )
    parser.add_argument("--start", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", help="End date YYYY-MM-DD")
    parser.add_argument(
        "--train-days", type=int, default=252,
        help="Minimum training window in trading days (default: 252)",
    )
    parser.add_argument(
        "--test-days", type=int, default=20,
        help="Test window per fold in trading days (default: 20)",
    )
    parser.add_argument(
        "--step-days", type=int, default=20,
        help="Step size between folds (default: 20)",
    )
    parser.add_argument(
        "--rolling", action="store_true",
        help="Use rolling window instead of expanding (default: expanding)",
    )
    parser.add_argument(
        "--no-stops", action="store_true",
        help="Disable stop-loss / take-profit",
    )
    parser.add_argument(
        "--slippage", type=float, default=0.001,
        help="Slippage fraction per trade (default: 0.001)",
    )
    parser.add_argument(
        "--cores", type=int, default=None,
        help="Number of CPU cores (default: all)",
    )
    parser.add_argument(
        "--folds", action="store_true",
        help="Print per-fold breakdown table",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON instead of text report",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    config = _build_config(args)

    print(f"\n  Backtesting {len(config.tickers)} tickers "
          f"({config.start_date} -> {config.end_date})")
    print(f"  Mode: {config.mode} | "
          f"Train: {config.min_train_days}d | "
          f"Test: {config.test_window_days}d | "
          f"Step: {config.step_days}d")
    print(f"  Window: {'expanding' if config.expanding_window else 'rolling'} | "
          f"Stops: {'on' if config.use_stops else 'off'}")
    print(f"  Capital: GBP{config.initial_capital:,.0f}")
    print()

    runner = BacktestRunner(config)
    result = runner.run(on_progress=lambda msg: print(f"  -> {msg}"))

    # Output
    if args.json:
        from dataclasses import asdict
        output = {
            "config": asdict(config),
            "n_folds": len(result.folds),
            "duration_seconds": result.total_duration_seconds,
        }
        if result.metrics:
            output["metrics"] = asdict(result.metrics)
        print(json.dumps(output, indent=2, default=str))
    else:
        print()
        print(format_report(result))
        if args.folds and result.folds:
            _print_fold_breakdown(result)

    # Save to SQLite
    if result.folds:
        try:
            from database import HistoryManager
            db = HistoryManager()
            run_id = db.save_backtest(result)
            print(f"\n  Saved to database (run #{run_id})")
        except Exception as e:
            print(f"\n  Warning: failed to save to database: {e}")

    # Exit code: 0 if we got results, 1 if no folds ran
    sys.exit(0 if result.folds else 1)


if __name__ == "__main__":
    main()
