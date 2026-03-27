"""
AutoResearch runner — autonomous strategy optimisation loop.

Usage:
  python -m autoresearch.runner [options]

Options:
  --cycle-hours FLOAT   Hours to sleep between experiments (default: 5)
  --db-path PATH        Path to the SQLite database (default: data/terminal_history.db)
  --config-path PATH    Path to config.json (default: config.json)
  --strategy-path PATH  Path to strategy.py (default: strategy.py)
  --max-cycles INT      Stop after this many cycles (0 = run forever, default: 0)
  --dry-run             Propose changes but never write them to disk
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import shutil
import subprocess
import sys
import time
import traceback
import types
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [autoresearch] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("autoresearch")

# ---------------------------------------------------------------------------
# Paths relative to the project root (the directory ABOVE autoresearch/)
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).parent          # autoresearch/
_PROJECT_ROOT = _PACKAGE_DIR.parent           # StockMarketAI/
_BACKUPS_DIR = _PACKAGE_DIR / "backups"
_EXPERIMENT_LOG = _PACKAGE_DIR / "experiment_log.jsonl"
_MAX_BACKUPS = 5
_MAX_CONSECUTIVE_REJECTS = 5


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExperimentRecord:
    """One row in the experiment log."""

    timestamp: str
    cycle: int
    baseline_accuracy: float
    result_accuracy: float
    baseline_sharpe: float
    result_sharpe: float
    result_pnl: float
    n_trades: int
    decision: str          # "ACCEPTED" | "REJECTED" | "ERROR"
    reasoning: str
    diff_summary: str
    config_changes: Dict[str, Any]


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: Path, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _load_text(path: Path) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _save_text(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _backup_strategy(strategy_path: Path, cycle: int) -> None:
    """Keep at most _MAX_BACKUPS copies of strategy.py in autoresearch/backups/."""
    _BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    dest = _BACKUPS_DIR / f"strategy_cycle{cycle:04d}_{ts}.py"
    shutil.copy2(strategy_path, dest)

    # Prune old backups
    all_backups = sorted(_BACKUPS_DIR.glob("strategy_cycle*.py"))
    while len(all_backups) > _MAX_BACKUPS:
        all_backups[0].unlink()
        all_backups = all_backups[1:]


def _log_experiment(record: ExperimentRecord) -> None:
    """Append an experiment record to the JSONL log."""
    with open(_EXPERIMENT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record)) + "\n")


def _load_recent_experiments(n: int = 10) -> List[Dict]:
    """Return the last `n` experiment records from the JSONL log."""
    if not _EXPERIMENT_LOG.exists():
        return []
    records: List[Dict] = []
    with open(_EXPERIMENT_LOG, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records[-n:]


# ---------------------------------------------------------------------------
# Claude subprocess call
# ---------------------------------------------------------------------------


def _call_claude(prompt: str, model: str, timeout: int = 300) -> str:
    """Call the `claude` CLI and return the raw text output.

    Uses the same subprocess pattern as claude_client.py so there is no
    separate API key requirement — it piggybacks on the user's subscription.
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
        output = result.stdout.strip()

        _ERROR_MARKERS = [
            "out of extra usage",
            "rate limit",
            "quota exceeded",
            "overloaded",
            "too many requests",
            "capacity",
        ]
        output_lower = output.lower()
        for marker in _ERROR_MARKERS:
            if marker in output_lower:
                logger.warning("Claude CLI usage-limit hit: %s", output[:120])
                return ""

        return output
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out after %ds", timeout)
        return ""
    except FileNotFoundError:
        logger.error(
            "claude CLI not found on PATH. "
            "Install it from https://docs.anthropic.com/en/docs/claude-cli"
        )
        return ""
    except Exception as exc:
        logger.error("Unexpected error calling Claude CLI: %s", exc)
        return ""


def _parse_claude_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract the JSON proposal from Claude's response.

    Claude may wrap it in a markdown code block — handle both cases.
    """
    text = text.strip()

    # Strip optional markdown fence
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    if text.endswith("```"):
        text = text[:-3]

    # Find the JSON object boundaries
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse Claude JSON response: %s", exc)
        return None


# ---------------------------------------------------------------------------
# diff application
# ---------------------------------------------------------------------------


def _apply_unified_diff(original_text: str, diff_text: str) -> Optional[str]:
    """Apply a unified diff string to original_text.

    Returns the patched text, or None if patching fails.
    Python's stdlib does not ship a patch applier, so we implement a
    minimal one that handles standard unified-diff hunks.
    """
    if not diff_text or not diff_text.strip():
        return original_text  # no change requested

    original_lines = original_text.splitlines(keepends=True)
    result_lines = list(original_lines)

    try:
        import re

        hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        diff_lines = diff_text.splitlines(keepends=True)

        # Skip the --- / +++ header lines
        patch_lines = [
            l for l in diff_lines if not l.startswith("--- ") and not l.startswith("+++ ")
        ]

        offset = 0  # cumulative line offset due to insertions/deletions
        i = 0
        while i < len(patch_lines):
            m = hunk_header.match(patch_lines[i])
            if not m:
                i += 1
                continue

            orig_start = int(m.group(1)) - 1  # 0-indexed
            i += 1

            remove_lines: List[str] = []
            add_lines: List[str] = []

            while i < len(patch_lines) and not hunk_header.match(patch_lines[i]):
                line = patch_lines[i]
                if line.startswith("-"):
                    remove_lines.append(line[1:])
                elif line.startswith("+"):
                    add_lines.append(line[1:])
                # context lines (space) we skip
                i += 1

            # Find where these remove_lines appear in result_lines
            target_start = orig_start + offset
            # Verify context match
            r_idx = target_start
            match_found = False
            # Search within a small window in case of offset drift
            for search_offset in range(-5, 10):
                pos = target_start + search_offset
                if pos < 0 or pos + len(remove_lines) > len(result_lines):
                    continue
                if all(
                    result_lines[pos + j] == remove_lines[j]
                    for j in range(len(remove_lines))
                ):
                    r_idx = pos
                    match_found = True
                    break

            if not match_found and remove_lines:
                logger.warning(
                    "Patch hunk starting at line %d could not be applied — skipping",
                    orig_start + 1,
                )
                continue

            result_lines[r_idx : r_idx + len(remove_lines)] = add_lines
            offset += len(add_lines) - len(remove_lines)

        return "".join(result_lines)

    except Exception as exc:
        logger.warning("Diff application failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Config update helper
# ---------------------------------------------------------------------------


def _apply_config_changes(config: Dict, changes: Dict[str, Any]) -> Dict:
    """Apply dot-notation config changes to a config dict (deep copy mutated)."""
    import copy

    cfg = copy.deepcopy(config)
    for key, value in changes.items():
        parts = key.split(".")
        node = cfg
        for part in parts[:-1]:
            if part not in node:
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
    return cfg


# ---------------------------------------------------------------------------
# Strategy loader (for evaluation)
# ---------------------------------------------------------------------------


def _load_strategy_module_from_path(path: Path) -> types.ModuleType:
    """Dynamically import a strategy.py file."""
    mod_name = "_autoresearch_strategy_tmp"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy from {path}")
    module = importlib.util.module_from_spec(spec)
    # Python 3.14 dataclass decorator needs the module in sys.modules
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


# ---------------------------------------------------------------------------
# Universe data loader
# ---------------------------------------------------------------------------


def _load_universe(config: Dict, project_root: Path) -> Dict[str, "pd.DataFrame"]:
    """Fetch historical OHLCV data for the active watchlist.

    Adds the project root to sys.path temporarily so data_loader can be
    imported even when runner is executed as a module from outside.
    """
    import importlib as _il

    root_str = str(project_root)
    added = False
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        added = True
    try:
        data_loader = _il.import_module("data_loader")
    finally:
        if added:
            sys.path.remove(root_str)

    watchlists = config.get("watchlists", {})
    active = config.get("active_watchlist", "")
    tickers = watchlists.get(active, [])
    if not tickers:
        # Fall back to any watchlist
        for v in watchlists.values():
            tickers = v
            break

    start_date = config.get("start_date", "2020-01-01")
    end_date = config.get("end_date", "2025-01-01")
    data_dir = project_root / config.get("data_dir", "data")

    logger.info("Loading universe data for %d tickers (%s → %s)", len(tickers), start_date, end_date)
    universe = data_loader.fetch_universe_data(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        data_dir=data_dir,
        use_cache=True,
    )
    logger.info("Universe loaded: %d tickers with data", len(universe))
    return universe


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt(
    program_md: str,
    accuracy: "AccuracyResult",
    recent_experiments: List[Dict],
) -> str:
    """Fill in the {{ACCURACY_SECTION}} and {{HISTORY_SECTION}} placeholders."""
    from autoresearch.evaluator import AccuracyResult  # local import to avoid circularity

    # --- accuracy section ---
    source_lines = "\n".join(
        f"  {src}: {rate:.1%}" for src, rate in sorted(accuracy.sources.items())
    )
    accuracy_text = (
        f"Window: last {accuracy.window_days} days\n"
        f"Overall hit-rate: {accuracy.overall:.1%} ({accuracy.total_predictions} resolved predictions)\n"
        f"Per-source hit-rates:\n{source_lines if source_lines else '  (no resolved predictions yet)'}"
    )

    # --- history section ---
    if recent_experiments:
        history_lines = []
        for i, exp in enumerate(recent_experiments, 1):
            history_lines.append(
                f"Experiment {i}: [{exp.get('decision', '?')}] "
                f"baseline={exp.get('baseline_accuracy', 0):.1%} → "
                f"result={exp.get('result_accuracy', 0):.1%} | "
                f"sharpe={exp.get('result_sharpe', 0):.2f} | "
                f"pnl={exp.get('result_pnl', 0):+.0f} | "
                f"reasoning: {exp.get('reasoning', '')[:100]}"
            )
        history_text = "\n".join(history_lines)
    else:
        history_text = "No experiments run yet — this is the first cycle."

    prompt = program_md.replace("{{ACCURACY_SECTION}}", accuracy_text)
    prompt = prompt.replace("{{HISTORY_SECTION}}", history_text)
    return prompt


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def _count_consecutive_rejects(recent: List[Dict]) -> int:
    """Count how many of the most recent experiments were rejected."""
    count = 0
    for exp in reversed(recent):
        if exp.get("decision") == "REJECTED":
            count += 1
        else:
            break
    return count


def run(
    cycle_hours: float = 5.0,
    db_path: str = "data/terminal_history.db",
    config_path: str = "config.json",
    strategy_path: str = "strategy.py",
    max_cycles: int = 0,
    dry_run: bool = False,
) -> None:
    """Main autonomous optimisation loop."""
    from autoresearch.evaluator import measure_accuracy, backtest

    project_root = _PROJECT_ROOT
    strategy_file = project_root / strategy_path
    config_file = project_root / config_path
    program_file = _PACKAGE_DIR / "program.md"
    db_file = project_root / db_path

    # Validate paths
    for p, name in [(strategy_file, "strategy.py"), (config_file, "config.json"), (program_file, "program.md")]:
        if not p.exists():
            logger.error("Required file not found: %s (%s)", p, name)
            sys.exit(1)

    logger.info(
        "AutoResearch starting. cycle=%.1fh, dry_run=%s, strategy=%s",
        cycle_hours,
        dry_run,
        strategy_file,
    )

    cycle = 0
    while True:
        cycle += 1
        if max_cycles > 0 and cycle > max_cycles:
            logger.info("Reached max_cycles=%d — exiting.", max_cycles)
            break

        logger.info("═══ Cycle %d ═══", cycle)
        cycle_start = time.monotonic()

        try:
            _run_cycle(
                cycle=cycle,
                strategy_file=strategy_file,
                config_file=config_file,
                program_file=program_file,
                db_file=db_file,
                dry_run=dry_run,
            )
        except KeyboardInterrupt:
            logger.info("Interrupted by user — exiting.")
            break
        except Exception as exc:
            logger.error("Cycle %d failed with unhandled exception: %s", cycle, exc)
            logger.debug(traceback.format_exc())

        # Pause logic: double sleep if too many consecutive rejects
        recent = _load_recent_experiments(n=10)
        consecutive_rejects = _count_consecutive_rejects(recent)
        sleep_hours = cycle_hours
        if consecutive_rejects >= _MAX_CONSECUTIVE_REJECTS:
            sleep_hours = cycle_hours * 2
            logger.warning(
                "%d consecutive rejects — pausing for %.1fh instead of %.1fh",
                consecutive_rejects,
                sleep_hours,
                cycle_hours,
            )

        elapsed = (time.monotonic() - cycle_start) / 3600
        remaining = max(0.0, sleep_hours - elapsed)
        if remaining > 0 and (max_cycles == 0 or cycle < max_cycles):
            logger.info("Sleeping %.1fh until next cycle.", remaining)
            time.sleep(remaining * 3600)


def _run_cycle(
    cycle: int,
    strategy_file: Path,
    config_file: Path,
    program_file: Path,
    db_file: Path,
    dry_run: bool,
) -> None:
    """Execute a single research cycle."""
    from autoresearch.evaluator import measure_accuracy, backtest

    # ── 1. Load current files ─────────────────────────────────────────────
    config = _load_json(config_file)
    original_strategy_text = _load_text(strategy_file)
    program_md = _load_text(program_file)

    # Determine Claude model from config (use medium/sonnet for proposals)
    claude_config = config.get("claude", {})
    model = claude_config.get("model_medium", "claude-sonnet-4-20250514")

    # ── 2. Baseline accuracy from DB ──────────────────────────────────────
    baseline_accuracy = measure_accuracy(str(db_file), window_days=7)
    logger.info("Baseline accuracy: overall=%.1f%%, n=%d", baseline_accuracy.overall * 100, baseline_accuracy.total_predictions)

    # ── 3. Load universe data for backtest ────────────────────────────────
    universe_data = _load_universe(config, _PROJECT_ROOT)
    if not universe_data:
        logger.warning("No universe data available — skipping backtest baseline")

    # ── 4. Baseline backtest with current strategy ────────────────────────
    baseline_bt = _backtest_strategy(strategy_file, universe_data, config)
    logger.info(
        "Baseline backtest: accuracy=%.1f%%, sharpe=%.2f, pnl=%+.0f, trades=%d",
        baseline_bt.accuracy * 100,
        baseline_bt.sharpe_ratio,
        baseline_bt.total_pnl,
        baseline_bt.n_trades,
    )

    # ── 5. Build prompt and call Claude ───────────────────────────────────
    recent_experiments = _load_recent_experiments(n=10)
    prompt = _build_prompt(program_md, baseline_accuracy, recent_experiments)

    # Append the current strategy.py so Claude can propose a diff
    prompt += (
        f"\n\n---\n\n## Current strategy.py\n\n```python\n{original_strategy_text}\n```\n\n"
        "Respond now with your JSON proposal."
    )

    logger.info("Calling Claude (%s) for proposal...", model)
    raw_response = _call_claude(prompt, model=model, timeout=300)

    if not raw_response:
        logger.warning("Empty response from Claude — skipping cycle.")
        _log_experiment(ExperimentRecord(
            timestamp=datetime.utcnow().isoformat(),
            cycle=cycle,
            baseline_accuracy=baseline_accuracy.overall,
            result_accuracy=0.0,
            baseline_sharpe=baseline_bt.sharpe_ratio,
            result_sharpe=0.0,
            result_pnl=0.0,
            n_trades=0,
            decision="ERROR",
            reasoning="Empty Claude response",
            diff_summary="",
            config_changes={},
        ))
        return

    # ── 6. Parse proposal ─────────────────────────────────────────────────
    proposal = _parse_claude_response(raw_response)
    if proposal is None:
        logger.warning("Could not parse Claude response as JSON — skipping cycle.")
        logger.debug("Raw response: %s", raw_response[:500])
        _log_experiment(ExperimentRecord(
            timestamp=datetime.utcnow().isoformat(),
            cycle=cycle,
            baseline_accuracy=baseline_accuracy.overall,
            result_accuracy=0.0,
            baseline_sharpe=baseline_bt.sharpe_ratio,
            result_sharpe=0.0,
            result_pnl=0.0,
            n_trades=0,
            decision="ERROR",
            reasoning="Could not parse JSON proposal",
            diff_summary="",
            config_changes={},
        ))
        return

    reasoning = str(proposal.get("reasoning", ""))
    diff_text = str(proposal.get("strategy_py_diff", ""))
    config_changes: Dict[str, Any] = proposal.get("config_changes", {})

    logger.info("Proposal reasoning: %s", reasoning[:200])
    if diff_text:
        logger.info("Strategy diff proposed (%d chars)", len(diff_text))
    if config_changes:
        logger.info("Config changes proposed: %s", config_changes)

    # ── 7. Apply changes to temporary copies ──────────────────────────────
    # --- strategy.py candidate ---
    candidate_strategy_text: Optional[str] = original_strategy_text
    if diff_text.strip():
        candidate_strategy_text = _apply_unified_diff(original_strategy_text, diff_text)
        if candidate_strategy_text is None:
            logger.warning("Failed to apply diff — falling back to original strategy")
            candidate_strategy_text = original_strategy_text
            diff_text = ""  # treat as no change

    # Write candidate strategy to a temp file for evaluation
    tmp_strategy = _PACKAGE_DIR / "_tmp_strategy_candidate.py"
    _save_text(tmp_strategy, candidate_strategy_text)

    # --- config candidate ---
    candidate_config = _apply_config_changes(config, config_changes) if config_changes else config

    # ── 8. Backtest the candidate ─────────────────────────────────────────
    candidate_bt = _backtest_strategy(tmp_strategy, universe_data, candidate_config)
    logger.info(
        "Candidate backtest: accuracy=%.1f%%, sharpe=%.2f, pnl=%+.0f, trades=%d",
        candidate_bt.accuracy * 100,
        candidate_bt.sharpe_ratio,
        candidate_bt.total_pnl,
        candidate_bt.n_trades,
    )

    # Clean up temp file
    tmp_strategy.unlink(missing_ok=True)

    # ── 9. Decision ───────────────────────────────────────────────────────
    # Accept if candidate is better on BOTH accuracy AND Sharpe, OR if it has
    # no backtest data (n_trades == 0) we fall back to trusting the proposal.
    decision = _make_decision(baseline_bt, candidate_bt)
    logger.info("Decision: %s", decision)

    diff_summary = _summarise_diff(diff_text) if diff_text else str(config_changes)

    record = ExperimentRecord(
        timestamp=datetime.utcnow().isoformat(),
        cycle=cycle,
        baseline_accuracy=baseline_accuracy.overall,
        result_accuracy=candidate_bt.accuracy,
        baseline_sharpe=baseline_bt.sharpe_ratio,
        result_sharpe=candidate_bt.sharpe_ratio,
        result_pnl=candidate_bt.total_pnl,
        n_trades=candidate_bt.n_trades,
        decision=decision,
        reasoning=reasoning,
        diff_summary=diff_summary,
        config_changes=config_changes,
    )

    if decision == "ACCEPTED" and not dry_run:
        # Back up current strategy
        _backup_strategy(strategy_file, cycle)
        # Overwrite strategy.py
        if diff_text.strip():
            _save_text(strategy_file, candidate_strategy_text)
            logger.info("strategy.py updated.")
        # Overwrite config.json
        if config_changes:
            _save_json(config_file, candidate_config)
            logger.info("config.json updated: %s", config_changes)
    elif decision == "ACCEPTED" and dry_run:
        logger.info("[dry-run] Would have accepted changes but did not write files.")

    _log_experiment(record)
    logger.info("Cycle %d complete — %s", cycle, decision)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backtest_strategy(
    strategy_path: Path,
    universe_data: Dict,
    config: Dict,
) -> "BacktestResult":
    """Load strategy from path and run backtest. Returns a zero result on failure."""
    from autoresearch.evaluator import backtest, BacktestResult

    if not universe_data:
        return BacktestResult(
            accuracy=0.0, sharpe_ratio=0.0, total_pnl=0.0, n_trades=0, n_correct=0
        )
    try:
        module = _load_strategy_module_from_path(strategy_path)
        return backtest(module, universe_data, config)
    except Exception as exc:
        logger.warning("Backtest failed: %s", exc)
        logger.debug(traceback.format_exc())
        return BacktestResult(
            accuracy=0.0, sharpe_ratio=0.0, total_pnl=0.0, n_trades=0, n_correct=0
        )


def _make_decision(
    baseline: "BacktestResult",
    candidate: "BacktestResult",
) -> str:
    """Return "ACCEPTED" or "REJECTED".

    Accept if candidate is strictly better on at least one metric and not
    significantly worse on any metric.  When there are too few trades to be
    meaningful (< 5) we are conservative and reject.
    """
    if candidate.n_trades < 5:
        return "REJECTED"

    acc_better = candidate.accuracy > baseline.accuracy
    sharpe_better = candidate.sharpe_ratio > baseline.sharpe_ratio
    pnl_better = candidate.total_pnl > baseline.total_pnl

    acc_delta = candidate.accuracy - baseline.accuracy
    sharpe_delta = candidate.sharpe_ratio - baseline.sharpe_ratio

    # Hard rejection: both accuracy AND Sharpe are worse
    if acc_delta < -0.01 and sharpe_delta < -0.1:
        return "REJECTED"

    # Accept if at least two of the three metrics improved
    improvements = sum([acc_better, sharpe_better, pnl_better])
    if improvements >= 2:
        return "ACCEPTED"

    # Accept if Sharpe improved meaningfully even if accuracy is flat
    if sharpe_delta > 0.15 and acc_delta >= -0.01:
        return "ACCEPTED"

    return "REJECTED"


def _summarise_diff(diff_text: str) -> str:
    """Return a one-line summary of the diff (added/removed line counts)."""
    added = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
    return f"+{added}/-{removed} lines"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AutoResearch: autonomous strategy optimisation loop"
    )
    parser.add_argument(
        "--cycle-hours",
        type=float,
        default=5.0,
        help="Hours between cycles (default: 5)",
    )
    parser.add_argument(
        "--db-path",
        default="data/terminal_history.db",
        help="SQLite database path (default: data/terminal_history.db)",
    )
    parser.add_argument(
        "--config-path",
        default="config.json",
        help="Config file path (default: config.json)",
    )
    parser.add_argument(
        "--strategy-path",
        default="strategy.py",
        help="Strategy file path (default: strategy.py)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=0,
        help="Stop after N cycles (0 = run forever, default: 0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Propose changes but do not write them to disk",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        cycle_hours=args.cycle_hours,
        db_path=args.db_path,
        config_path=args.config_path,
        strategy_path=args.strategy_path,
        max_cycles=args.max_cycles,
        dry_run=args.dry_run,
    )
