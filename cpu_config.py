"""Central CPU core configuration.

Every module that spawns processes, threads, or sets scikit-learn n_jobs
should call ``get_cpu_cores()`` instead of using ``os.cpu_count()`` or
hard-coding ``n_jobs=-1``.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


@lru_cache(maxsize=1)
def get_cpu_cores() -> int:
    """Return the configured CPU core limit.

    Resolution order:
      1. ``config.json`` → ``"cpu_cores"`` (explicit int)
      2. ``os.cpu_count()`` (system default)
      3. Fallback to 4

    The value is capped at ``os.cpu_count()`` so a stale config on a
    smaller machine can never request more cores than exist.
    """
    physical = os.cpu_count() or 4

    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f).get("cpu_cores")
    except (OSError, json.JSONDecodeError):
        return physical

    if raw is None:
        return physical

    configured = int(raw)
    return max(1, min(configured, physical))


def get_n_jobs() -> int:
    """Return a value suitable for scikit-learn's ``n_jobs`` parameter.

    scikit-learn interprets positive ints as an explicit core count.
    """
    return get_cpu_cores()
