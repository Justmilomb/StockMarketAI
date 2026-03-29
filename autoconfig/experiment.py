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
    python autoconfig/experiment.py --crisis 2020_covid_crash # Backtest against a specific crisis period
    python autoconfig/experiment.py --stress-test             # Run all crisis periods, compute resilience
    python autoconfig/experiment.py --strategy-profile momentum  # Apply a named strategy profile
    python autoconfig/experiment.py --use-strategy-selector   # Enable regime-aware strategy selection

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

    # Autoconfig uses step_days=120 (~15 folds) for speed.
    # Config.json's step_days=20 is for the live terminal, not experiments.
    step_days = 120

    return BacktestConfig(
        start_date=bt_cfg.get("start_date", cfg.get("start_date", "2018-01-01")),
        end_date=bt_cfg.get("end_date", cfg.get("end_date", "2026-03-27")),
        tickers=tickers,
        min_train_days=bt_cfg.get("min_train_days", 252),
        test_window_days=bt_cfg.get("test_window_days", 20),
        step_days=step_days,
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
        n_processes=bt_cfg.get("n_processes"),  # null = use all cores
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


def _extract_metrics_dict(m: object) -> Dict[str, float | int]:
    """Convert a PerformanceMetrics object to a flat dict for scoring/output."""
    return {
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


def _run_single_backtest(
    bt_config: BacktestConfig,
    label: str = "",
) -> Dict[str, Any]:
    """Execute one backtest run and return structured output dict."""
    progress_log = PROJECT_ROOT / "autoconfig" / ".progress"

    def _progress(msg: str) -> None:
        prefix = f"[{label}] " if label else "  -> "
        print(f"{prefix}{msg}", flush=True)
        try:
            with open(progress_log, "a", encoding="utf-8") as pf:
                pf.write(f"{prefix}{msg}\n")
                pf.flush()
        except Exception:
            pass

    runner = BacktestRunner(bt_config)
    result = runner.run(on_progress=_progress)

    m = result.metrics
    output: Dict[str, Any] = {
        "status": "ok" if result.folds else "no_data",
        "n_folds": len(result.folds),
        "n_tickers": len(bt_config.tickers),
    }

    if m:
        metrics = _extract_metrics_dict(m)
        output["metrics"] = metrics
        output["score"] = _compute_score(metrics)
    else:
        output["metrics"] = {}
        output["score"] = 0.0

    return output


def _compute_crisis_resilience(
    normal_metrics: Dict[str, float | int],
    crisis_results: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Score how well the strategy survives crisis periods.

    Penalties:
        - max_drawdown > 25% in any crisis
        - win_rate drop > 20% from normal to crisis
    Rewards:
        - Positive Sharpe ratio during crisis
    """
    if not crisis_results:
        return {"score": 0.0, "detail": "no_crisis_data"}

    normal_win_rate = normal_metrics.get("win_rate", 0.0)
    penalties: List[Dict[str, Any]] = []
    rewards: List[Dict[str, Any]] = []

    crisis_scores: List[float] = []
    for name, cr in crisis_results.items():
        cm = cr.get("metrics", {})
        if not cm:
            continue

        period_score = 50.0  # Baseline — surviving is worth something

        # Penalise excessive drawdown
        crisis_dd = cm.get("max_drawdown_pct", 100.0)
        if crisis_dd > 25.0:
            dd_penalty = min((crisis_dd - 25.0) * 0.5, 25.0)
            period_score -= dd_penalty
            penalties.append({
                "crisis": name,
                "type": "drawdown",
                "value": round(crisis_dd, 2),
                "penalty": round(dd_penalty, 2),
            })

        # Penalise win-rate collapse
        crisis_wr = cm.get("win_rate", 0.0)
        wr_drop = normal_win_rate - crisis_wr
        if wr_drop > 0.20:
            wr_penalty = min(wr_drop * 50.0, 20.0)
            period_score -= wr_penalty
            penalties.append({
                "crisis": name,
                "type": "win_rate_drop",
                "normal": round(normal_win_rate, 4),
                "crisis_value": round(crisis_wr, 4),
                "penalty": round(wr_penalty, 2),
            })

        # Reward positive risk-adjusted returns
        crisis_sharpe = cm.get("sharpe_ratio", 0.0)
        if crisis_sharpe > 0.0:
            sharpe_bonus = min(crisis_sharpe * 10.0, 25.0)
            period_score += sharpe_bonus
            rewards.append({
                "crisis": name,
                "type": "positive_sharpe",
                "value": round(crisis_sharpe, 4),
                "bonus": round(sharpe_bonus, 2),
            })

        crisis_scores.append(max(0.0, min(100.0, period_score)))

    avg_score = sum(crisis_scores) / len(crisis_scores) if crisis_scores else 0.0

    return {
        "score": round(avg_score, 4),
        "n_periods_tested": len(crisis_scores),
        "per_period_scores": {
            name: round(s, 4)
            for name, s in zip(crisis_results.keys(), crisis_scores)
        },
        "penalties": penalties,
        "rewards": rewards,
    }


def _sanitise_overrides(overrides: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Strip backtesting internals that the agent should never override.

    The autoconfig agent is only allowed to tune strategy, risk, consensus,
    mirofish, ai, ensemble, timeframes, forecasters, and regime params.
    Backtesting infrastructure (step_days, n_processes, mode, etc.) is
    locked down to prevent degenerate experiments.
    """
    if overrides is None:
        return None

    overrides = copy.deepcopy(overrides)

    # Remove entire backtesting section — agents must not touch it
    if "backtesting" in overrides:
        stripped = overrides.pop("backtesting")
        if stripped:
            print(
                f"  [guardrail] Stripped backtesting overrides: {stripped}",
                file=sys.stderr, flush=True,
            )

    return overrides if overrides else None


def run_experiment(
    overrides: Dict[str, Any] | None = None,
    config_file: str | None = None,
    fast: bool = False,
    no_mirofish: bool = False,
    universe: str | None = None,
    sector: str | None = None,
    universe_seed: int | None = None,
    crisis: str | None = None,
    stress_test: bool = False,
    strategy_profile: str | None = None,
    use_strategy_selector: bool = False,
) -> Dict[str, Any]:
    """Run a single backtest experiment and return structured results."""
    t0 = time.time()

    # --- Guardrail: strip backtesting overrides from agent --------------------
    overrides = _sanitise_overrides(overrides)

    # --- Resolve crisis period date overrides --------------------------------
    if crisis:
        from autoconfig.universe import get_crisis_period
        period = get_crisis_period(crisis)
        if period is None:
            from autoconfig.universe import CRISIS_PERIODS
            valid = ", ".join(CRISIS_PERIODS.keys())
            return {
                "status": "error",
                "error": f"Unknown crisis period '{crisis}'. Valid: {valid}",
                "score": 0.0,
            }
        # Inject start/end into overrides
        bt_override = {"start_date": period["start"], "end_date": period["end"]}
        if overrides is None:
            overrides = {"backtesting": bt_override}
        else:
            overrides = _deep_merge(overrides, {"backtesting": bt_override})

    # --- Apply strategy profile overrides ------------------------------------
    if strategy_profile:
        try:
            from autoconfig.strategy_profiles import get_profile
            profile = get_profile(strategy_profile)
            if profile is None:
                return {
                    "status": "error",
                    "error": f"Unknown strategy profile '{strategy_profile}'.",
                    "score": 0.0,
                }
            # Merge profile overrides (thresholds, sizing, etc.)
            if overrides is None:
                overrides = profile
            else:
                overrides = _deep_merge(overrides, profile)
        except ImportError:
            return {
                "status": "error",
                "error": "autoconfig/strategy_profiles.py not found.",
                "score": 0.0,
            }

    # --- Resolve ticker universe ---------------------------------------------
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

    # --- Enable regime-aware strategy selector if requested ------------------
    if use_strategy_selector and hasattr(bt_config, "use_strategy_selector"):
        bt_config.use_strategy_selector = True

    # Clear previous progress log
    progress_log = PROJECT_ROOT / "autoconfig" / ".progress"
    try:
        progress_log.write_text("", encoding="utf-8")
    except Exception:
        pass

    # --- Normal backtest run -------------------------------------------------
    normal_result = _run_single_backtest(bt_config, label="normal")

    # Separator line so Claude knows where progress ends and JSON begins
    print("---JSON---", flush=True)

    duration = time.time() - t0
    normal_result["duration_seconds"] = round(duration, 1)
    normal_result["universe"] = universe_label
    normal_result["mode"] = bt_config.mode
    normal_result["use_mirofish"] = bt_config.use_mirofish

    if overrides:
        normal_result["overrides"] = overrides

    # --- Stress test: run all crisis periods ---------------------------------
    if stress_test:
        from autoconfig.universe import get_all_crisis_periods

        all_crises = get_all_crisis_periods()
        crisis_results: Dict[str, Dict[str, Any]] = {}

        data_start = bt_config.start_date
        data_end = bt_config.end_date

        for cname, cperiod in all_crises.items():
            # Only test crises that overlap with the data range
            if cperiod["end"] < data_start or cperiod["start"] > data_end:
                print(
                    f"  -> Skipping {cname} (outside data range "
                    f"{data_start}..{data_end})",
                    file=sys.stderr, flush=True,
                )
                continue

            print(
                f"  -> Stress testing: {cname} "
                f"({cperiod['start']} to {cperiod['end']})",
                file=sys.stderr, flush=True,
            )

            crisis_bt = copy.deepcopy(bt_config)
            crisis_bt.start_date = cperiod["start"]
            crisis_bt.end_date = cperiod["end"]

            cr = _run_single_backtest(crisis_bt, label=cname)
            crisis_results[cname] = cr

        # Compute resilience score
        normal_metrics = normal_result.get("metrics", {})
        resilience = _compute_crisis_resilience(normal_metrics, crisis_results)

        normal_score = normal_result.get("score", 0.0)
        resilience_score = resilience["score"]
        combined_score = round(0.6 * normal_score + 0.4 * resilience_score, 4)

        normal_result["stress_test"] = {
            "crisis_results": crisis_results,
            "resilience": resilience,
            "normal_score": normal_score,
            "crisis_resilience_score": resilience_score,
            "combined_score": combined_score,
        }
        # Replace top-level score with the blended score
        normal_result["score"] = combined_score

        stress_duration = time.time() - t0
        normal_result["duration_seconds"] = round(stress_duration, 1)

    return normal_result


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
    parser.add_argument("--fast", action="store_true",
                        help="DEPRECATED — ignored. Full mode always used for trade metrics.")
    parser.add_argument("--no-mirofish", action="store_true", help="Disable MiroFish")
    parser.add_argument(
        "--universe", type=str, default=None,
        choices=["small", "medium", "large", "full"],
        help="Stock universe size: small (30), medium (100), large (180), full (~250)",
    )
    parser.add_argument(
        "--sector", type=str, default=None,
        help="Test a specific sector: tech, finance, healthcare, consumer, energy, industrial, volatile, uk_ftse, eu_blue",
    )
    parser.add_argument(
        "--universe-seed", type=int, default=None,
        help="Random seed for reproducible universe sampling",
    )
    parser.add_argument(
        "--crisis", type=str, default=None,
        help="Override dates to a named crisis period (e.g. 2020_covid_crash, 2022_bear_market)",
    )
    parser.add_argument(
        "--stress-test", action="store_true",
        help="Run all crisis periods sequentially and compute a combined resilience score",
    )
    parser.add_argument(
        "--strategy-profile", type=str, default=None,
        help="Apply a named strategy profile's overrides (e.g. momentum, mean_reversion)",
    )
    parser.add_argument(
        "--use-strategy-selector", action="store_true",
        help="Enable regime-aware strategy selection in the backtest",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    overrides = None
    if args.overrides:
        overrides = json.loads(args.overrides)

    result = run_experiment(
        overrides=overrides,
        config_file=args.config_file,
        fast=False,  # Always full mode — fast produces zero trade metrics
        no_mirofish=args.no_mirofish,
        universe=args.universe,
        sector=args.sector,
        universe_seed=args.universe_seed,
        crisis=args.crisis,
        stress_test=args.stress_test,
        strategy_profile=args.strategy_profile,
        use_strategy_selector=args.use_strategy_selector,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
