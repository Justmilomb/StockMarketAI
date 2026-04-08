"""Immutable evaluation harness for Polymarket edge detection — DO NOT MODIFY.

Imports the agent's train.py, fetches resolved markets, runs edge
detection, simulates betting, and prints the score.

Three evaluation modes:
    legacy   — single flat CONFIG from train.py
    profile  — single profile from profile_configs.py
    combined — all profiles sequentially, weighted average score

Usage:
    python evaluate.py                            # Legacy mode
    python evaluate.py --profile balanced_edge    # Single profile
    python evaluate.py --combined                 # All profiles
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

from research_polymarket.data import fetch_resolved_markets
from research_polymarket.evaluator import PolymarketMetrics, evaluate_edge_strategy

PROFILES_DIR = Path(__file__).parent / "profiles"


# ── Score weights per profile ──────────────────────────────────────────

# 8 scoring components (matching stock research rigour)
# brier, return, edge_accuracy, win_rate, bet_volume, drawdown, profit_factor, sharpe
PROFILE_SCORE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "balanced_edge": {
        "brier": 15.0, "return": 15.0, "edge_accuracy": 15.0,
        "win_rate": 15.0, "bet_volume": 10.0, "drawdown": 15.0,
        "profit_factor": 10.0, "sharpe": 5.0,
    },
    "aggressive_edge": {
        "brier": 10.0, "return": 25.0, "edge_accuracy": 10.0,
        "win_rate": 10.0, "bet_volume": 15.0, "drawdown": 10.0,
        "profit_factor": 10.0, "sharpe": 10.0,
    },
    "conservative_edge": {
        "brier": 20.0, "return": 10.0, "edge_accuracy": 15.0,
        "win_rate": 15.0, "bet_volume": 5.0, "drawdown": 20.0,
        "profit_factor": 10.0, "sharpe": 5.0,
    },
    "trend_follower": {
        "brier": 10.0, "return": 20.0, "edge_accuracy": 15.0,
        "win_rate": 10.0, "bet_volume": 10.0, "drawdown": 10.0,
        "profit_factor": 15.0, "sharpe": 10.0,
    },
    "mean_reversion": {
        "brier": 15.0, "return": 15.0, "edge_accuracy": 20.0,
        "win_rate": 15.0, "bet_volume": 10.0, "drawdown": 10.0,
        "profit_factor": 10.0, "sharpe": 5.0,
    },
}

DEFAULT_WEIGHTS: Dict[str, float] = {
    "brier": 15.0, "return": 15.0, "edge_accuracy": 15.0,
    "win_rate": 15.0, "bet_volume": 10.0, "drawdown": 15.0,
    "profit_factor": 10.0, "sharpe": 5.0,
}


# ── Scoring ────────────────────────────────────────────────────────────

def _compute_score(
    metrics: PolymarketMetrics,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Composite score — higher is better. Max theoretical ~100.

    8 components matching the stock research scorer rigour:
    - Brier: calibration quality (lower = better)
    - Return: total profit normalised to 25% (not 50% — harder target)
    - Edge accuracy: fraction of edge calls that were correct
    - Win rate: fraction of bets won
    - Bet volume: normalised to 50 bets (not 30)
    - Drawdown: penalise large drawdowns (inverted — lower dd = higher score)
    - Profit factor: gross wins / gross losses, capped at 3.0
    - Sharpe: risk-adjusted return, capped at 2.0
    """
    w = weights or DEFAULT_WEIGHTS

    # Brier score: 0.0 = perfect, 0.25 = random
    brier_norm = max(0.0, 1.0 - metrics.brier_score / 0.25)

    # Return: 25% = full credit (was 50% — too easy with binary payouts)
    return_norm = max(0.0, min(metrics.total_return_pct / 25.0, 1.0))

    # Edge accuracy: raw 0-1
    edge_acc = metrics.edge_accuracy

    # Win rate: raw 0-1
    win_rate = metrics.win_rate

    # Bet volume: 50 bets = full credit (was 30 — too easy)
    bet_vol_norm = min(metrics.n_bets / 50.0, 1.0)

    # Drawdown: 0% = perfect, 50%+ = zero score (inverted)
    dd_norm = max(0.0, 1.0 - metrics.max_drawdown_pct / 50.0)

    # Profit factor: 3.0+ = full credit
    pf_norm = min(metrics.profit_factor / 3.0, 1.0)

    # Sharpe: 2.0+ = full credit
    sharpe_norm = max(0.0, min(metrics.sharpe_ratio / 2.0, 1.0))

    score = (
        brier_norm * w["brier"]
        + return_norm * w["return"]
        + edge_acc * w["edge_accuracy"]
        + win_rate * w["win_rate"]
        + bet_vol_norm * w["bet_volume"]
        + dd_norm * w["drawdown"]
        + pf_norm * w["profit_factor"]
        + sharpe_norm * w["sharpe"]
    )
    return round(score, 4)


def _extract_metrics(m: PolymarketMetrics) -> dict:
    """Flatten PolymarketMetrics into a serializable dict."""
    return {
        "brier_score": round(m.brier_score, 4),
        "log_loss": round(m.log_loss, 4),
        "total_return_pct": round(m.total_return_pct, 2),
        "final_bankroll": round(m.final_bankroll, 2),
        "edge_accuracy": round(m.edge_accuracy, 4),
        "win_rate": round(m.win_rate, 4),
        "n_bets": m.n_bets,
        "n_markets_evaluated": m.n_markets_evaluated,
        "max_drawdown_pct": round(m.max_drawdown_pct, 2),
        "avg_bet_size": round(m.avg_bet_size, 2),
        "profit_factor": round(m.profit_factor, 4),
        "sharpe_ratio": round(m.sharpe_ratio, 4),
        "category_win_rates": {
            k: round(v, 4) for k, v in m.category_win_rates.items()
        },
    }


# ── Best-config persistence ───────────────────────────────────────────

def _save_best_profile(
    profile_name: str,
    score: float,
    metrics: dict,
    config: Dict[str, Any],
) -> bool:
    """Save profile config if it beats the current best."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    best_file = PROFILES_DIR / f"best_{profile_name}.json"

    current_best = 0.0
    if best_file.exists():
        try:
            existing = json.loads(best_file.read_text(encoding="utf-8"))
            current_best = existing.get("score", 0.0)
        except (json.JSONDecodeError, OSError):
            pass

    if score <= current_best:
        return False

    data = {
        "profile": profile_name,
        "score": score,
        "previous_best": current_best,
        "metrics": metrics,
        "config": config,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    best_file.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    _append_score_log(profile_name, score)
    return True


def _append_score_log(profile_name: str, score: float) -> None:
    """Append to the scores trajectory log."""
    scores_file = PROFILES_DIR / "scores.json"
    entries: list = []
    if scores_file.exists():
        try:
            entries = json.loads(scores_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    entries.append({
        "profile": profile_name,
        "score": score,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    scores_file.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    import importlib.util
    import logging

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    parser = argparse.ArgumentParser(description="Evaluate Polymarket edge strategy")
    parser.add_argument("--time", type=int, default=0,
                        help="Max wall-clock seconds (0 = unlimited)")
    parser.add_argument("--profile", type=str, default="",
                        help="Evaluate a single profile")
    parser.add_argument("--combined", action="store_true",
                        help="Evaluate all profiles")
    parser.add_argument("--refresh-cache", action="store_true",
                        help="Force re-fetch resolved markets from API")
    args = parser.parse_args()

    # Optionally clear cache
    if args.refresh_cache:
        from research_polymarket.data import RESOLVED_CACHE
        if RESOLVED_CACHE.exists():
            RESOLVED_CACHE.unlink()
            print("Cleared resolved market cache", flush=True)

    # Import train.py
    spec = importlib.util.spec_from_file_location(
        "train", Path(__file__).parent / "train.py",
    )
    train = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(train)

    profile_name = args.profile or getattr(train, "ACTIVE_PROFILE", "")
    profile_mode = args.profile or getattr(train, "PROFILE_MODE", False)
    combined_mode = args.combined or getattr(train, "EVALUATE_COMBINED", False)

    if combined_mode:
        _run_combined(train, args)
    elif profile_mode and profile_name:
        _run_profile(profile_name, train, args)
    else:
        _run_legacy(train, args)


def _run_legacy(train: object, args: object) -> None:
    """Legacy mode — single CONFIG."""
    cfg = getattr(train, "CONFIG", {})

    print(f"Mode: LEGACY (polymarket)", flush=True)
    print(f"Min edge: {cfg.get('min_edge_pct', 5.0)}%", flush=True)
    print(f"Categories: {cfg.get('categories', ['all'])}", flush=True)
    print("---", flush=True)

    t0 = time.time()
    print("Fetching resolved markets...", flush=True)
    markets = fetch_resolved_markets(max_markets=300)
    print(f"Loaded {len(markets)} resolved markets", flush=True)

    if not markets:
        print("ERROR: No resolved markets available", flush=True)
        print(json.dumps({"score": 0.0, "metrics": {}, "error": "no markets"}, indent=2), flush=True)
        return

    print("Running edge evaluation...", flush=True)
    metrics = evaluate_edge_strategy(markets, cfg)

    duration = time.time() - t0
    extracted = _extract_metrics(metrics)
    score = _compute_score(metrics)

    print("\n---RESULT---", flush=True)
    output = {
        "score": score,
        "metrics": extracted,
        "duration_seconds": round(duration, 1),
    }
    print(json.dumps(output, indent=2, default=str), flush=True)


def _run_profile(profile_name: str, train: object, args: object) -> None:
    """Single profile mode."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "profile_configs", Path(__file__).parent / "profile_configs.py",
    )
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    configs = getattr(pc, "PROFILE_CONFIGS", {})
    if profile_name not in configs:
        print(f"ERROR: Profile '{profile_name}' not found", flush=True)
        print(f"Available: {list(configs.keys())}", flush=True)
        sys.exit(1)

    profile_cfg = configs[profile_name]

    print(f"Mode: PROFILE ({profile_name}) [polymarket]", flush=True)
    print(f"Min edge: {profile_cfg.get('min_edge_pct', 5.0)}%", flush=True)
    print(f"Categories: {profile_cfg.get('categories', ['all'])}", flush=True)
    print("---", flush=True)

    t0 = time.time()
    print("Fetching resolved markets...", flush=True)
    markets = fetch_resolved_markets(max_markets=300)
    print(f"Loaded {len(markets)} resolved markets", flush=True)

    if not markets:
        print("ERROR: No resolved markets available", flush=True)
        output = {"score": 0.0, "profile": profile_name, "metrics": {}, "error": "no markets"}
        print(json.dumps(output, indent=2, default=str), flush=True)
        return

    print("Running edge evaluation...", flush=True)
    metrics = evaluate_edge_strategy(markets, profile_cfg)

    duration = time.time() - t0
    extracted = _extract_metrics(metrics)
    weights = PROFILE_SCORE_WEIGHTS.get(profile_name, DEFAULT_WEIGHTS)
    score = _compute_score(metrics, weights)

    saved = _save_best_profile(profile_name, score, extracted, profile_cfg)

    print("\n---RESULT---", flush=True)
    output = {
        "score": score,
        "profile": profile_name,
        "metrics": extracted,
        "is_new_best": saved,
        "duration_seconds": round(duration, 1),
    }
    print(json.dumps(output, indent=2, default=str), flush=True)

    if saved:
        print(f"\n  *** NEW BEST for {profile_name}: {score:.2f} ***", flush=True)


def _run_combined(train: object, args: object) -> None:
    """Combined mode — evaluate all profiles, weighted average score."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "profile_configs", Path(__file__).parent / "profile_configs.py",
    )
    pc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pc)

    configs = getattr(pc, "PROFILE_CONFIGS", {})
    if not configs:
        print("ERROR: No profiles found", flush=True)
        sys.exit(1)

    print(f"Mode: COMBINED (polymarket)", flush=True)
    print(f"Profiles: {list(configs.keys())}", flush=True)
    print("---", flush=True)

    t0 = time.time()

    # Fetch markets once (shared across profiles)
    print("Fetching resolved markets...", flush=True)
    markets = fetch_resolved_markets(max_markets=300)
    print(f"Loaded {len(markets)} resolved markets", flush=True)

    if not markets:
        print("ERROR: No resolved markets available", flush=True)
        print(json.dumps({"score": 0.0, "error": "no markets"}, indent=2), flush=True)
        return

    profile_scores: Dict[str, float] = {}
    profile_metrics: Dict[str, dict] = {}

    for name, cfg in configs.items():
        print(f"\nEvaluating {name}...", flush=True)
        metrics = evaluate_edge_strategy(markets, cfg)
        extracted = _extract_metrics(metrics)
        weights = PROFILE_SCORE_WEIGHTS.get(name, DEFAULT_WEIGHTS)
        score = _compute_score(metrics, weights)

        profile_scores[name] = score
        profile_metrics[name] = extracted

        _save_best_profile(name, score, extracted, cfg)
        print(f"  {name}: score={score:.2f}, bets={metrics.n_bets}, "
              f"return={metrics.total_return_pct:+.1f}%", flush=True)

    # Combined score = weighted average
    combined_score = sum(profile_scores.values()) / len(profile_scores) if profile_scores else 0.0
    duration = time.time() - t0

    print("\n---RESULT---", flush=True)
    output = {
        "score": round(combined_score, 4),
        "mode": "combined",
        "profile_scores": {k: round(v, 4) for k, v in profile_scores.items()},
        "profile_metrics": profile_metrics,
        "duration_seconds": round(duration, 1),
    }
    print(json.dumps(output, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
