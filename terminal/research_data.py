"""Reads experiment data from the research/ autoresearch directory.

Parses git log for experiment history and reads train.py for current config.
All operations are read-only — the terminal never modifies research state.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

RESEARCH_DIR = Path(__file__).resolve().parent.parent / "research"

# Hide console windows on Windows
_SUBPROCESS_FLAGS: dict = {}
if sys.platform == "win32":
    _SUBPROCESS_FLAGS["creationflags"] = subprocess.CREATE_NO_WINDOW

_SCORE_RE = re.compile(r"score\s*=\s*([\d.]+)", re.IGNORECASE)


def is_research_available() -> bool:
    """Check if the research directory and git repo exist."""
    return (RESEARCH_DIR / ".git").is_dir()


def get_experiment_log(limit: int = 50) -> List[Dict[str, Any]]:
    """Parse research git log into structured experiment records.

    Each commit with 'exp:' in the message is an experiment.
    Format: 'exp: <description> score=<X.XX>'

    Returns list of dicts sorted most-recent-first:
        [{"hash": "abc123", "date": "2026-04-02", "message": "...",
          "score": 45.2, "is_experiment": True}, ...]
    """
    if not is_research_available():
        return []

    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={limit}", "--format=%H|%ai|%s"],
            capture_output=True, text=True, timeout=10,
            cwd=str(RESEARCH_DIR), encoding="utf-8",
            **_SUBPROCESS_FLAGS,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    experiments: List[Dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        commit_hash, date_str, message = parts

        is_exp = message.lower().startswith("exp:")
        score_match = _SCORE_RE.search(message)
        score = float(score_match.group(1)) if score_match else None

        experiments.append({
            "hash": commit_hash[:7],
            "date": date_str[:10],
            "time": date_str[11:16],
            "message": message,
            "score": score,
            "is_experiment": is_exp,
        })

    return experiments


def get_best_score(experiments: List[Dict[str, Any]] | None = None) -> float:
    """Return the highest score from experiment history."""
    if experiments is None:
        experiments = get_experiment_log()
    scores = [e["score"] for e in experiments if e.get("score") is not None]
    return max(scores) if scores else 0.0


def get_current_config() -> Dict[str, Any]:
    """Read the current CONFIG from research/train.py."""
    train_path = RESEARCH_DIR / "train.py"
    if not train_path.exists():
        return {}

    try:
        spec = importlib.util.spec_from_file_location("train_read", str(train_path))
        if spec is None or spec.loader is None:
            return {}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return dict(getattr(mod, "CONFIG", {}))
    except Exception:
        return {}


def get_live_progress() -> Optional[Dict[str, Any]]:
    """Read the live progress file written by evaluate.py during a run.

    Returns None if no progress file exists or it's stale (>10 min old).
    """
    progress_path = RESEARCH_DIR / ".progress.json"
    if not progress_path.exists():
        return None

    try:
        import json as _json
        import time as _time

        # Stale check: if file is older than 10 minutes, ignore it
        age = _time.time() - progress_path.stat().st_mtime
        if age > 600:
            return None

        data = _json.loads(progress_path.read_text(encoding="utf-8"))
        data["age_seconds"] = round(age, 1)
        return data
    except (OSError, ValueError):
        return None


def is_research_running() -> bool:
    """Check if research is actively running by looking at the progress file.

    The progress file is written by evaluate.py every few seconds during a run.
    If it exists and was updated recently (<2 min), research is running.
    """
    progress = get_live_progress()
    if progress is None:
        return False
    # If status is "running" or "starting" and file is fresh, it's running
    status = progress.get("status", "")
    age = progress.get("age_seconds", 999)
    return status in ("running", "starting") and age < 120


def get_score_trend(experiments: List[Dict[str, Any]] | None = None) -> List[float]:
    """Return chronological list of experiment scores for sparkline display."""
    if experiments is None:
        experiments = get_experiment_log()
    # Reverse to chronological (oldest first)
    scores = [
        e["score"] for e in reversed(experiments)
        if e.get("score") is not None
    ]
    return scores
