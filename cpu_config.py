"""Central CPU core configuration.

Every module that spawns processes, threads, or sets scikit-learn n_jobs
should call ``get_cpu_cores()`` instead of using ``os.cpu_count()`` or
hard-coding ``n_jobs=-1``.

For parallel fold execution, use ``get_max_parallel_folds()`` and
``get_n_jobs_per_fold()`` to avoid over-subscribing the CPU.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def get_cpu_cores() -> int:
    """Return the configured CPU core limit.

    Resolution order:
      1. ``AUTOCONFIG_CPU_CORES`` env var (for experiments)
      2. ``config.json`` → ``"cpu_cores"`` (explicit int)
      3. ``os.cpu_count()`` (system default)
      4. Fallback to 4

    The value is capped at ``os.cpu_count()`` so a stale config on a
    smaller machine can never request more cores than exist.
    """
    physical = os.cpu_count() or 4
    env_val = os.environ.get("AUTOCONFIG_CPU_CORES")
    if env_val is not None:
        return max(1, min(int(env_val), physical))
    raw = _load_config().get("cpu_cores")

    if raw is None:
        return physical

    configured = int(raw)
    return max(1, min(configured, physical))


def get_max_parallel_folds() -> int:
    """Return the max number of parallel backtest folds.

    Resolution order:
      1. ``AUTOCONFIG_MAX_FOLDS`` env var (for experiments)
      2. ``config.json`` → ``"max_parallel_folds"``
      3. All CPU cores (each fold runs in its own process)
    """
    env_val = os.environ.get("AUTOCONFIG_MAX_FOLDS")
    if env_val is not None:
        return max(1, int(env_val))
    raw = _load_config().get("max_parallel_folds")
    if raw is not None:
        return max(1, int(raw))
    return max(2, get_cpu_cores())


def get_n_jobs_per_fold() -> int:
    """Return n_jobs for scikit-learn models running inside a parallel fold.

    Divides total cores across parallel folds so total threads ≈ total cores.
    """
    folds = get_max_parallel_folds()
    return max(1, get_cpu_cores() // folds)


def get_n_jobs() -> int:
    """Return a value suitable for scikit-learn's ``n_jobs`` parameter.

    When called outside of backtesting (e.g. live pipeline), uses all cores.
    """
    return get_cpu_cores()
