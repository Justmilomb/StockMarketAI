"""Autonomous config optimisation launcher.

Repeatedly invokes Claude Code CLI sessions to run backtest experiments
and iteratively find the best config. Modelled after Karpathy's autoresearch.

Usage:
    python autoconfig/run.py                     # Default: 10 experiments per session
    python autoconfig/run.py --batch-size 20     # 20 experiments per session
    python autoconfig/run.py --max-sessions 50   # Stop after 50 sessions
    python autoconfig/run.py --dry-run           # Print the command without running

Each session:
  1. Launches Claude Code (Opus 4.6) pointing at program.md
  2. Claude runs N experiments, modifying configs and evaluating
  3. Session ends, results are persisted to results.tsv
  4. Loop restarts with a new session (fresh context)

The human can interrupt at any time with Ctrl+C. Progress is saved
in autoconfig/results.tsv and autoconfig/best_config.json.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUTOCONFIG_DIR = PROJECT_ROOT / "autoconfig"
RESULTS_FILE = AUTOCONFIG_DIR / "results.tsv"
BEST_CONFIG_FILE = AUTOCONFIG_DIR / "best_config.json"
PROGRAM_FILE = AUTOCONFIG_DIR / "program.md"


def _count_experiments() -> int:
    """Count completed experiments from results.tsv."""
    if not RESULTS_FILE.exists():
        return 0
    lines = RESULTS_FILE.read_text().strip().split("\n")
    return max(0, len(lines) - 1)  # Subtract header


def _build_prompt(batch_size: int, session_num: int) -> str:
    """Build the prompt for a Claude Code session."""
    n_done = _count_experiments()

    prompt = f"""You are an autonomous config optimisation agent for StockMarketAI.

Read autoconfig/program.md for full instructions.

This is session #{session_num}. There are {n_done} experiments completed so far.

{'Read autoconfig/results.tsv to see prior results and autoconfig/best_config.json for the current best config.' if n_done > 0 else 'This is the first session - start with a baseline experiment.'}

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

IMPORTANT: Work from the {PROJECT_ROOT} directory.
IMPORTANT: NEVER modify config.json - only use --overrides for experiments.
IMPORTANT: Run all {batch_size} experiments before finishing. Do not stop early."""

    return prompt


def _run_session(batch_size: int, session_num: int, dry_run: bool = False) -> bool:
    """Launch one Claude Code session. Returns True if it completed without error."""
    prompt = _build_prompt(batch_size, session_num)

    if dry_run:
        print(f"\n[DRY RUN] Would execute claude session with prompt:")
        print(f"  {prompt[:300]}...")
        return True

    print(f"\n{'='*70}")
    print(f"  SESSION #{session_num}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Experiments completed so far: {_count_experiments()}")
    print(f"  Batch size: {batch_size}")
    print(f"{'='*70}\n")

    cmd = [
        "claude",
        "-p", prompt,
        "--model", "claude-opus-4-6",
        "--allowedTools", "Bash,Read,Edit,Write,Glob,Grep",
        "--verbose",
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
        )
        return proc.returncode == 0
    except FileNotFoundError:
        print("\n  [ERROR] 'claude' CLI not found. Install Claude Code first:")
        print("    npm install -g @anthropic-ai/claude-code")
        return False
    except Exception as e:
        print(f"\n  [ERROR] Session #{session_num} failed: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous config optimisation via Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python autoconfig/run.py                    # Run indefinitely
    python autoconfig/run.py --batch-size 5     # 5 experiments per session
    python autoconfig/run.py --max-sessions 10  # Stop after 10 sessions
    python autoconfig/run.py --dry-run          # Preview without executing

Press Ctrl+C at any time to stop. Progress is saved automatically.
        """,
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Experiments per Claude session (default: 10)",
    )
    parser.add_argument(
        "--max-sessions", type=int, default=0,
        help="Max sessions to run (0 = infinite, default: 0)",
    )
    parser.add_argument(
        "--cooldown", type=int, default=30,
        help="Seconds to wait between sessions (default: 30)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print commands without executing",
    )

    args = parser.parse_args()

    print(r"""
     _         _         ____             __ _
    / \  _   _| |_ ___  / ___|___  _ __  / _(_) __ _
   / _ \| | | | __/ _ \| |   / _ \| '_ \| |_| |/ _` |
  / ___ \ |_| | || (_) | |__| (_) | | | |  _| | (_| |
 /_/   \_\__,_|\__\___/ \____\___/|_| |_|_| |_|\__, |
                                                 |___/
    Autonomous Config Optimiser for StockMarketAI
    Powered by Claude Opus 4.6
    """)

    print(f"  Batch size:    {args.batch_size} experiments per session")
    print(f"  Max sessions:  {'unlimited' if args.max_sessions == 0 else args.max_sessions}")
    print(f"  Cooldown:      {args.cooldown}s between sessions")
    print(f"  Results file:  {RESULTS_FILE}")
    print(f"  Best config:   {BEST_CONFIG_FILE}")
    print(f"  Experiments done so far: {_count_experiments()}")
    print()

    if not PROGRAM_FILE.exists():
        print(f"  [ERROR] {PROGRAM_FILE} not found. Run from project root.")
        sys.exit(1)

    # Verify claude CLI exists
    if not args.dry_run:
        try:
            subprocess.run(
                ["claude", "--version"],
                capture_output=True, timeout=60,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("  [ERROR] 'claude' CLI not found. Install it first:")
            print("    npm install -g @anthropic-ai/claude-code")
            sys.exit(1)

    session_num = 1
    consecutive_failures = 0

    try:
        while True:
            if args.max_sessions > 0 and session_num > args.max_sessions:
                print(f"\n  Reached max sessions ({args.max_sessions}). Stopping.")
                break

            success = _run_session(args.batch_size, session_num, dry_run=args.dry_run)

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print(f"\n  [WARN] 3 consecutive failures — waiting 5 minutes before retry")
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
        if BEST_CONFIG_FILE.exists():
            print(f"  Best config saved at: {BEST_CONFIG_FILE}")
        print("  To resume later, just run this script again.\n")


if __name__ == "__main__":
    main()
