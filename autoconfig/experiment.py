"""Run a single backtest experiment with config overrides.

Usage:
    python autoconfig/experiment.py                          # Run with current config.json watchlist
    python autoconfig/experiment.py --universe medium         # 30 diverse stocks (default for autoconfig)
    python autoconfig/experiment.py --universe large          # 60 stocks
    python autoconfig/experiment.py --universe full           # 100+ stocks (slow but thorough)
    python autoconfig/experiment.py --universe small          # 15 stocks (quick screening)
    python autoconfig/experiment.py --sector tech             # Tech sector only
    python autoconfig/experiment.py --sector volatile         # High-volatility stocks
    python autoconfig/experiment.py --overrides '{"strategy": {"threshold_buy": 0.60}}'
    python autoconfig/experiment.py --fast --no-mirofish      # Fastest mode

Outputs a single JSON object to stdout with all metrics.
Config.json is NEVER modified — overrides are applied in-memory only.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List

# Suppress noisy warnings during experiments
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.runner import BacktestRunner
from backtesting.types import BacktestConfig


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge overrides into base config."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_config(overrides: Dict[str, Any] | None = None,
                 config_file: str | None = None) -> dict:
    """Load base config.json and apply overrides."""
    config_path = PROJECT_ROOT / "config.json"
    with open(config_path) as f:
        cfg = json.load(f)

    if config_file:
        with open(config_file) as f:
            file_overrides = json.load(f)
        cfg = _deep_merge(cfg, file_overrides)

    if overrides:
        cfg = _deep_merge(cfg, overrides)

    return cfg


def _build_backtest_config(cfg: dict, fast: bool = False,
                           no_mirofish: bool = False,
                           tickers_override: List[str] | None = None) -> BacktestConfig:
    """Build BacktestConfig from merged config dict."""
    strategy = cfg.get("strategy", {})
    risk = cfg.get("risk", {})
    bt_cfg = cfg.get("backtesting", {})
    mf_cfg = cfg.get("mirofish", {})

    # Resolve tickers — override takes priority
    if tickers_override:
        tickers = tickers_override
    else:
        watchlists = cfg.get("watchlists", {})
        active = cfg.get("active_watchlist", "")
        tickers = watchlists.get(active, cfg.get("tickers", []))

    use_mirofish = bt_cfg.get("use_mirofish", mf_cfg.get("enabled", False))
    if no_mirofish:
        use_mirofish = False

    return BacktestConfig(
        start_date=bt_cfg.get("start_date", cfg.get("start_date", "2018-01-01")),
        end_date=bt_cfg.get("end_date", cfg.get("end_date", "2026-03-27")),
        tickers=tickers,
        min_train_days=bt_cfg.get("min_train_days", 252),
        test_window_days=bt_cfg.get("test_window_days", 20),
        step_days=bt_cfg.get("step_days", 20),
        expanding_window=bt_cfg.get("expanding_window", True),
        initial_capital=cfg.get("capital", 100_000),
        max_positions=strategy.get("max_positions", 8),
        position_size_fraction=strategy.get("position_size_fraction", 0.12),
        threshold_buy=strategy.get("threshold_buy", 0.58),
        threshold_sell=strategy.get("threshold_sell", 0.42),
        slippage_pct=bt_cfg.get("slippage_pct", 0.001),
        commission_per_trade=0.0,
        use_stops=bt_cfg.get("use_stops", True),
        atr_stop_multiplier=risk.get("atr_stop_multiplier", 1.8),
        atr_profit_multiplier=risk.get("atr_profit_multiplier", 2.5),
        use_mirofish=use_mirofish,
        mirofish_n_sims=bt_cfg.get("mirofish_n_sims", 12),
        n_processes=bt_cfg.get("n_processes"),
        mode="fast" if fast else "full",
    )


def _compute_score(metrics: dict) -> float:
    """Compute a single composite score from backtest metrics.

    Higher is better. Weights:
        signal_accuracy:  40%  (foundation — bad signals = bad trades)
        win_rate:         25%  (direct profitability indicator)
        sharpe_ratio:     15%  (risk-adjusted returns)
        profit_factor:    10%  (sustainability)
        max_drawdown:     10%  (penalty — lower is better)
    """
    accuracy = metrics.get("signal_accuracy", 0.0)
    win_rate = metrics.get("win_rate", 0.0)
    sharpe = metrics.get("sharpe_ratio", 0.0)
    profit_factor = min(metrics.get("profit_factor", 0.0), 5.0)  # Cap at 5 to avoid inf
    max_dd = metrics.get("max_drawdown_pct", 100.0)

    score = (
        accuracy * 40.0
        + win_rate * 25.0
        + min(max(sharpe, -2.0), 4.0) * 3.75   # Sharpe scaled: 15% weight over [-2, 4] range
        + profit_factor * 2.0                     # PF scaled: 10% weight over [0, 5] range
        + max(0.0, 10.0 - max_dd * 0.1)          # DD penalty: 10% weight, 0% DD = 10pts
    )
    return round(score, 4)


def run_experiment(
    overrides: Dict[str, Any] | None = None,
    config_file: str | None = None,
    fast: bool = False,
    no_mirofish: bool = False,
    universe: str | None = None,
    sector: str | None = None,
    universe_seed: int | None = None,
) -> Dict[str, Any]:
    """Run a single backtest experiment and return structured results."""
    t0 = time.time()

    # Resolve ticker universe
    tickers_override: List[str] | None = None
    universe_label = "watchlist"

    if sector:
        from autoconfig.universe import SECTOR_GROUPS
        tickers_override = SECTOR_GROUPS.get(sector)
        universe_label = f"sector:{sector} ({len(tickers_override or [])} tickers)"
    elif universe:
        from autoconfig.universe import get_universe
        tickers_override = get_universe(universe, seed=universe_seed)
        universe_label = f"{universe} ({len(tickers_override)} tickers)"

    if tickers_override:
        print(f"  -> Universe: {universe_label}", file=sys.stderr, flush=True)

    cfg = _load_config(overrides, config_file)
    bt_config = _build_backtest_config(
        cfg, fast=fast, no_mirofish=no_mirofish,
        tickers_override=tickers_override,
    )

    # Write progress to both stdout (for Claude's tool output) and a log
    # file (for run.py to tail live while Claude's -p mode buffers).
    progress_log = PROJECT_ROOT / "autoconfig" / ".progress"

    def _progress(msg: str) -> None:
        print(f"  -> {msg}", flush=True)
        try:
            with open(progress_log, "a", encoding="utf-8") as pf:
                pf.write(f"{msg}\n")
                pf.flush()
        except Exception:
            pass

    # Clear previous progress
    try:
        progress_log.write_text("", encoding="utf-8")
    except Exception:
        pass

    runner = BacktestRunner(bt_config)
    result = runner.run(on_progress=_progress)
    # Separator line so Claude knows where progress ends and JSON begins
    print("---JSON---", flush=True)

    duration = time.time() - t0

    # Extract metrics
    m = result.metrics
    output: Dict[str, Any] = {
        "status": "ok" if result.folds else "no_data",
        "n_folds": len(result.folds),
        "n_tickers": len(bt_config.tickers),
        "universe": universe_label,
        "duration_seconds": round(duration, 1),
        "mode": bt_config.mode,
        "use_mirofish": bt_config.use_mirofish,
    }

    if m:
        metrics = {
            "signal_accuracy": round(m.signal_accuracy, 4),
            "signal_precision": round(m.signal_precision, 4),
            "signal_recall": round(m.signal_recall, 4),
            "total_return_pct": round(m.total_return_pct, 2),
            "annualised_return_pct": round(m.annualised_return_pct, 2),
            "sharpe_ratio": round(m.sharpe_ratio, 4),
            "sortino_ratio": round(m.sortino_ratio, 4),
            "calmar_ratio": round(m.calmar_ratio, 4),
            "max_drawdown_pct": round(m.max_drawdown_pct, 2),
            "total_trades": m.total_trades,
            "win_rate": round(m.win_rate, 4),
            "profit_factor": round(m.profit_factor, 4),
            "avg_win_pct": round(m.avg_win_pct, 2),
            "avg_loss_pct": round(m.avg_loss_pct, 2),
            "avg_hold_days": round(m.avg_hold_days, 1),
        }
        output["metrics"] = metrics
        output["score"] = _compute_score(metrics)
    else:
        output["metrics"] = {}
        output["score"] = 0.0

    # Include the overrides that were applied (for logging)
    if overrides:
        output["overrides"] = overrides

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single backtest experiment")
    parser.add_argument(
        "--overrides", type=str, default=None,
        help="JSON string of config overrides (e.g. '{\"strategy\": {\"threshold_buy\": 0.60}}')",
    )
    parser.add_argument(
        "--config-file", type=str, default=None,
        help="Path to a JSON file with config overrides",
    )
    parser.add_argument("--fast", action="store_true", help="Fast mode (signal accuracy only)")
    parser.add_argument("--no-mirofish", action="store_true", help="Disable MiroFish")
    parser.add_argument(
        "--universe", type=str, default=None,
        choices=["small", "medium", "large", "full"],
        help="Stock universe size: small (15), medium (30), large (60), full (100+)",
    )
    parser.add_argument(
        "--sector", type=str, default=None,
        help="Test a specific sector: tech, finance, healthcare, consumer, energy, industrial, volatile, uk_ftse, eu_blue",
    )
    parser.add_argument(
        "--universe-seed", type=int, default=None,
        help="Random seed for reproducible universe sampling",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    overrides = None
    if args.overrides:
        overrides = json.loads(args.overrides)

    result = run_experiment(
        overrides=overrides,
        config_file=args.config_file,
        fast=args.fast,
        no_mirofish=args.no_mirofish,
        universe=args.universe,
        sector=args.sector,
        universe_seed=args.universe_seed,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
