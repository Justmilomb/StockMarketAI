"""Autonomous config optimisation launcher.

Two modes:
    --direct (default): Runs experiments directly via Python — no Claude CLI
        needed. Uses systematic parameter sweeps (grid/random) to explore
        the config space. Works on any machine including headless VMs.

    --claude: Launches Claude Code CLI sessions to design and run experiments
        interactively. Requires the claude CLI to be installed and authenticated.

Usage:
    python autoconfig/run.py                     # Direct mode, systematic sweep
    python autoconfig/run.py --batch-size 20     # 20 experiments per batch
    python autoconfig/run.py --max-experiments 50
    python autoconfig/run.py --claude             # Use Claude CLI sessions instead
    python autoconfig/run.py --dry-run            # Preview without executing

Progress is saved in autoconfig/results.tsv and autoconfig/best_config.json.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTOCONFIG_DIR = PROJECT_ROOT / "autoconfig"
RESULTS_FILE = AUTOCONFIG_DIR / "results.tsv"
BEST_CONFIG_FILE = AUTOCONFIG_DIR / "best_config.json"
PROGRAM_FILE = AUTOCONFIG_DIR / "program.md"

# Add project root for imports in direct mode
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Parameter space for direct-mode sweeps
# ---------------------------------------------------------------------------

PARAM_SPACE: Dict[str, Dict[str, Any]] = {
    "strategy.threshold_buy":           {"min": 0.50, "max": 0.72, "step": 0.02},
    "strategy.threshold_sell":          {"min": 0.30, "max": 0.50, "step": 0.02},
    "strategy.max_positions":           {"min": 3,    "max": 15,   "step": 1, "type": "int"},
    "strategy.position_size_fraction":  {"min": 0.05, "max": 0.25, "step": 0.02},
    "risk.atr_stop_multiplier":         {"min": 1.0,  "max": 3.5,  "step": 0.25},
    "risk.atr_profit_multiplier":       {"min": 1.5,  "max": 5.0,  "step": 0.25},
    "risk.kelly_fraction_cap":          {"min": 0.15, "max": 0.50, "step": 0.05},
    "risk.drawdown_threshold":          {"min": 0.08, "max": 0.30, "step": 0.02},
    "consensus.min_consensus_pct":      {"min": 45.0, "max": 85.0, "step": 5.0},
    "consensus.disagreement_penalty":   {"min": 0.2,  "max": 0.9,  "step": 0.1},
}


def _count_experiments() -> int:
    """Count completed experiments from results.tsv."""
    if not RESULTS_FILE.exists():
        return 0
    lines = RESULTS_FILE.read_text().strip().split("\n")
    return max(0, len(lines) - 1)  # Subtract header


def _get_best_score() -> float:
    """Read the best score from results.tsv."""
    if not RESULTS_FILE.exists():
        return 0.0
    lines = RESULTS_FILE.read_text().strip().split("\n")
    if len(lines) < 2:
        return 0.0
    best = 0.0
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                best = max(best, float(parts[1]))
            except ValueError:
                pass
    return best


def _dotpath_to_overrides(dotpath: str, value: Any) -> Dict[str, Any]:
    """Convert 'strategy.threshold_buy' + value into nested dict."""
    keys = dotpath.split(".")
    result: Dict[str, Any] = {}
    current = result
    for key in keys[:-1]:
        current[key] = {}
        current = current[key]
    current[keys[-1]] = value
    return result


def _generate_sweep_experiments(n: int) -> List[Tuple[Dict[str, Any], str]]:
    """Generate N experiments: mix of single-param sweeps and random combos.

    Returns list of (overrides_dict, notes_string).
    """
    experiments: List[Tuple[Dict[str, Any], str]] = []
    param_names = list(PARAM_SPACE.keys())

    # First half: single-parameter sweeps (one param at a time, random value)
    n_single = n // 2
    for _ in range(n_single):
        param = random.choice(param_names)
        spec = PARAM_SPACE[param]
        if spec.get("type") == "int":
            value = random.randint(int(spec["min"]), int(spec["max"]))
        else:
            # Snap to grid
            steps = round((spec["max"] - spec["min"]) / spec["step"])
            step_idx = random.randint(0, steps)
            value = round(spec["min"] + step_idx * spec["step"], 4)
        overrides = _dotpath_to_overrides(param, value)
        notes = f"sweep {param}={value}"
        experiments.append((overrides, notes))

    # Second half: 2-param combos
    n_combo = n - n_single
    for _ in range(n_combo):
        chosen = random.sample(param_names, min(2, len(param_names)))
        merged: Dict[str, Any] = {}
        parts: List[str] = []
        for param in chosen:
            spec = PARAM_SPACE[param]
            if spec.get("type") == "int":
                value = random.randint(int(spec["min"]), int(spec["max"]))
            else:
                steps = round((spec["max"] - spec["min"]) / spec["step"])
                step_idx = random.randint(0, steps)
                value = round(spec["min"] + step_idx * spec["step"], 4)
            override = _dotpath_to_overrides(param, value)
            # Deep merge
            for k, v in override.items():
                if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                    merged[k].update(v)
                else:
                    merged[k] = v
            parts.append(f"{param}={value}")
        notes = "combo " + " + ".join(parts)
        experiments.append((merged, notes))

    return experiments


def _record_result(
    exp_id: int,
    result: Dict[str, Any],
    overrides: Dict[str, Any],
    notes: str,
) -> None:
    """Append a row to results.tsv."""
    # Ensure header exists
    if not RESULTS_FILE.exists() or RESULTS_FILE.stat().st_size == 0:
        RESULTS_FILE.write_text(
            "id\tscore\taccuracy\twin_rate\tsharpe\tprofit_factor\tmax_dd\tduration\toverrides\tnotes\n"
        )

    metrics = result.get("metrics", {})
    row = (
        f"{exp_id}\t"
        f"{result.get('score', 0.0)}\t"
        f"{metrics.get('signal_accuracy', 0.0)}\t"
        f"{metrics.get('win_rate', 0.0)}\t"
        f"{metrics.get('sharpe_ratio', 0.0)}\t"
        f"{metrics.get('profit_factor', 0.0)}\t"
        f"{metrics.get('max_drawdown_pct', 0.0)}\t"
        f"{result.get('duration_seconds', 0.0)}\t"
        f"{json.dumps(overrides)}\t"
        f"{notes}\n"
    )
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(row)


def _update_best_config(overrides: Dict[str, Any], score: float) -> None:
    """Update best_config.json if this score is the new best."""
    # Load current config as base
    config_path = PROJECT_ROOT / "config.json"
    try:
        with open(config_path) as f:
            base = json.load(f)
    except Exception:
        base = {}

    # Deep merge overrides
    from autoconfig.experiment import _deep_merge
    merged = _deep_merge(base, overrides)
    merged["_autoconfig_score"] = score
    merged["_autoconfig_updated"] = datetime.now().isoformat()

    with open(BEST_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)


def _run_direct_batch(
    batch_size: int,
    fast: bool,
    no_mirofish: bool,
    universe: str,
    universe_seed: int | None,
) -> int:
    """Run a batch of experiments directly (no Claude CLI).

    Returns the number of experiments completed.
    """
    from autoconfig.experiment import run_experiment

    start_id = _count_experiments()
    best_score = _get_best_score()

    experiments = _generate_sweep_experiments(batch_size)

    completed = 0
    for i, (overrides, notes) in enumerate(experiments):
        exp_id = start_id + i
        print(f"\n  {'─'*60}")
        print(f"  Experiment #{exp_id}: {notes}")
        print(f"  Overrides: {json.dumps(overrides)}")
        print(f"  {'─'*60}")

        try:
            result = run_experiment(
                overrides=overrides,
                fast=fast,
                no_mirofish=no_mirofish,
                universe=universe,
                universe_seed=universe_seed,
            )

            score = result.get("score", 0.0)
            _record_result(exp_id, result, overrides, notes)

            status = result.get("status", "?")
            metrics = result.get("metrics", {})
            print(f"\n  Result: score={score:.4f} | "
                  f"acc={metrics.get('signal_accuracy', 0):.4f} | "
                  f"wr={metrics.get('win_rate', 0):.4f} | "
                  f"sharpe={metrics.get('sharpe_ratio', 0):.4f} | "
                  f"status={status}")

            if score > best_score:
                print(f"  *** NEW BEST: {score:.4f} (was {best_score:.4f}) ***")
                best_score = score
                _update_best_config(overrides, score)

            completed += 1

        except KeyboardInterrupt:
            print("\n  Interrupted by user.")
            break
        except Exception as e:
            print(f"\n  Experiment #{exp_id} CRASHED: {e}")
            _record_result(exp_id, {"score": 0.0, "metrics": {}}, overrides, f"CRASH: {e}")
            completed += 1

    return completed


# ---------------------------------------------------------------------------
# Claude CLI mode (original behaviour)
# ---------------------------------------------------------------------------

def _build_prompt(batch_size: int, session_num: int) -> str:
    """Build the prompt for a Claude Code session."""
    n_done = _count_experiments()

    prompt = f"""You are an autonomous config optimisation agent for StockMarketAI.

Read autoconfig/program.md for full instructions.

This is session #{session_num}. There are {n_done} experiments completed so far.

{'Read autoconfig/results.tsv to see prior results and autoconfig/best_config.json for the current best config.' if n_done > 0 else 'This is the first session — start with a baseline experiment.'}

Run {batch_size} experiments this session following the program.md workflow.
After each experiment, record results in autoconfig/results.tsv.
If you find improvements, update autoconfig/best_config.json (including strategy_profiles).

The stock universe has ~250 tickers across US mega/mid-cap, UK FTSE, EU blue chips,
crypto proxies, and user watchlist. Use --universe medium (30 stocks) for fast iteration,
--universe large (80 stocks) for validation, --universe full (~250 stocks) for final checks.
Every 10 experiments, validate winners against --universe large and --stress-test.

Also optimise per-profile strategy parameters (conservative, day_trader, swing,
crisis_alpha, trend_follower) using --strategy-profile <name>. Save improved profile
params to best_config.json under the strategy_profiles key.

IMPORTANT: Work from the E:/Coding/StockMarketAI directory.
IMPORTANT: NEVER modify config.json — only use --overrides for experiments.
IMPORTANT: Run all {batch_size} experiments before finishing. Do not stop early."""

    return prompt


def _run_claude_session(batch_size: int, session_num: int, dry_run: bool = False) -> bool:
    """Launch one Claude Code session. Returns True if it completed without error."""

    prompt = _build_prompt(batch_size, session_num)

    cmd = [
        "claude",
        "-p", prompt,
        "--model", "claude-opus-4-6",
        "--allowedTools",
        "Bash(python autoconfig/*) Bash(cat autoconfig/*) Bash(head *) Bash(wc *) Read Edit Write Glob Grep",
        "--max-budget-usd", "50",
        "--verbose",
    ]

    if dry_run:
        print(f"\n[DRY RUN] Would execute:")
        print(f"  {' '.join(cmd[:6])}...")
        print(f"  Prompt: {prompt[:200]}...")
        return True

    print(f"\n{'='*70}")
    print(f"  SESSION #{session_num}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Experiments completed so far: {_count_experiments()}")
    print(f"  Batch size: {batch_size}")
    print(f"{'='*70}\n")

    try:
        # Stream all Claude output directly to terminal for full visibility
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
        )

        proc.wait()

        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"\n  [TIMEOUT] Session #{session_num} exceeded 2 hours — moving to next session")
        return False
    except FileNotFoundError:
        print("\n  [ERROR] 'claude' CLI not found. Install Claude Code first:")
        print("    npm install -g @anthropic-ai/claude-code")
        return False
    except Exception as e:
        print(f"\n  [ERROR] Session #{session_num} failed: {e}")
        return False




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous config optimisation for StockMarketAI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python autoconfig/run.py                          # Direct mode (no Claude CLI needed)
    python autoconfig/run.py --batch-size 20          # 20 experiments per batch
    python autoconfig/run.py --max-experiments 50     # Stop after 50 experiments
    python autoconfig/run.py --fast                   # Signal-accuracy only (faster)
    python autoconfig/run.py --universe small          # Smaller universe (fastest)
    python autoconfig/run.py --claude                  # Use Claude CLI sessions instead
    python autoconfig/run.py --dry-run                 # Preview without executing

Press Ctrl+C at any time to stop. Progress is saved automatically.
        """,
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Experiments per batch (default: 10)",
    )
    parser.add_argument(
        "--max-experiments", type=int, default=0,
        help="Max total experiments to run (0 = infinite, default: 0)",
    )
    parser.add_argument(
        "--max-sessions", type=int, default=0,
        help="Max sessions/batches to run (0 = infinite, default: 0)",
    )
    parser.add_argument(
        "--cooldown", type=int, default=10,
        help="Seconds to wait between batches (default: 10)",
    )
    parser.add_argument(
        "--claude", action="store_true",
        help="Use Claude CLI sessions instead of direct parameter sweeps",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="Signal-accuracy-only mode (no trade simulation, faster)",
    )
    parser.add_argument(
        "--no-mirofish", action="store_true",
        help="Disable MiroFish (faster experiments)",
    )
    parser.add_argument(
        "--universe", type=str, default="medium",
        choices=["small", "medium", "large", "full"],
        help="Stock universe size (default: medium)",
    )
    parser.add_argument(
        "--universe-seed", type=int, default=42,
        help="Seed for reproducible universe sampling (default: 42)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print experiment plans without executing",
    )

    args = parser.parse_args()

    mode_label = "Claude CLI" if args.claude else "Direct (no Claude needed)"

    print(r"""
     _         _         ____             __ _
    / \  _   _| |_ ___  / ___|___  _ __  / _(_) __ _
   / _ \| | | | __/ _ \| |   / _ \| '_ \| |_| |/ _` |
  / ___ \ |_| | || (_) | |__| (_) | | | |  _| | (_| |
 /_/   \_\__,_|\__\___/ \____\___/|_| |_|_| |_|\__, |
                                                 |___/
    Autonomous Config Optimiser for StockMarketAI
    """)

    print(f"  Mode:          {mode_label}")
    print(f"  Batch size:    {args.batch_size} experiments per batch")
    print(f"  Max experiments: {'unlimited' if args.max_experiments == 0 else args.max_experiments}")
    print(f"  Universe:      {args.universe} (seed={args.universe_seed})")
    print(f"  Fast mode:     {'on' if args.fast else 'off'}")
    print(f"  MiroFish:      {'off' if args.no_mirofish else 'on'}")
    print(f"  Results file:  {RESULTS_FILE}")
    print(f"  Best config:   {BEST_CONFIG_FILE}")
    print(f"  Experiments done so far: {_count_experiments()}")
    print()

    # ── Claude CLI mode ──────────────────────────────────────────────────
    if args.claude:
        if not PROGRAM_FILE.exists():
            print(f"  [ERROR] {PROGRAM_FILE} not found. Run from project root.")
            sys.exit(1)

        if not args.dry_run:
            try:
                subprocess.run(
                    ["claude", "--version"],
                    capture_output=True, timeout=60,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                print("  [ERROR] 'claude' CLI not found. Install it first:")
                print("    npm install -g @anthropic-ai/claude-code")
                print("  Or run without --claude for direct mode (no Claude needed).")
                sys.exit(1)

        session_num = 1
        consecutive_failures = 0

        try:
            while True:
                if args.max_sessions > 0 and session_num > args.max_sessions:
                    print(f"\n  Reached max sessions ({args.max_sessions}). Stopping.")
                    break

                success = _run_claude_session(args.batch_size, session_num, dry_run=args.dry_run)

                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= 3:
                        print(f"\n  [WARN] 3 consecutive failures — waiting 5 minutes")
                        time.sleep(300)
                        consecutive_failures = 0

                session_num += 1

                n_done = _count_experiments()
                print(f"\n  Total experiments completed: {n_done}")
                print(f"  Next session in {args.cooldown}s... (Ctrl+C to stop)")

                if not args.dry_run:
                    time.sleep(args.cooldown)

                if args.dry_run and session_num > 3:
                    print("\n  [DRY RUN] Stopping after 3 preview sessions")
                    break

        except KeyboardInterrupt:
            print(f"\n\n  Stopped by user after {session_num - 1} sessions.")
            print(f"  Total experiments: {_count_experiments()}")

        return

    # ── Direct mode (default) ────────────────────────────────────────────
    session_num = 1
    total_completed = 0

    try:
        while True:
            if args.max_sessions > 0 and session_num > args.max_sessions:
                print(f"\n  Reached max batches ({args.max_sessions}). Stopping.")
                break

            if args.max_experiments > 0 and total_completed >= args.max_experiments:
                print(f"\n  Reached max experiments ({args.max_experiments}). Stopping.")
                break

            remaining = args.batch_size
            if args.max_experiments > 0:
                remaining = min(remaining, args.max_experiments - total_completed)

            if args.dry_run:
                experiments = _generate_sweep_experiments(remaining)
                print(f"\n  [DRY RUN] Batch #{session_num} — {len(experiments)} experiments:")
                for overrides, notes in experiments:
                    print(f"    {notes}  |  {json.dumps(overrides)}")
                total_completed += len(experiments)
                if session_num >= 3:
                    print("\n  [DRY RUN] Stopping after 3 preview batches")
                    break
            else:
                print(f"\n{'='*70}")
                print(f"  BATCH #{session_num}")
                print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  Experiments completed so far: {_count_experiments()}")
                print(f"  Running {remaining} experiments...")
                print(f"{'='*70}")

                done = _run_direct_batch(
                    batch_size=remaining,
                    fast=args.fast,
                    no_mirofish=args.no_mirofish,
                    universe=args.universe,
                    universe_seed=args.universe_seed,
                )
                total_completed += done

            session_num += 1

            n_done = _count_experiments()
            best = _get_best_score()
            print(f"\n  Total experiments: {n_done} | Best score: {best:.4f}")
            print(f"  Next batch in {args.cooldown}s... (Ctrl+C to stop)")

            if not args.dry_run:
                time.sleep(args.cooldown)

    except KeyboardInterrupt:
        print(f"\n\n  Stopped by user.")
        print(f"  Total experiments: {_count_experiments()}")
        if BEST_CONFIG_FILE.exists():
            print(f"  Best config saved at: {BEST_CONFIG_FILE}")
        print("  To resume later, just run this script again.\n")


if __name__ == "__main__":
    main()
