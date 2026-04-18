"""Stable, anonymised install ID for telemetry.

The ID is a 16-char hex digest of ``sha256(platform + user + host)``.
It is deterministic for one OS user on one machine, so all of an
install's events can be stitched together server-side, but it cannot
be reversed into the user's name, email, or hostname.

Once computed the ID is cached to ``{user_data_dir}/telemetry_id.txt``
so a reinstall preserves continuity across the same machine.
"""
from __future__ import annotations

import getpass
import hashlib
import logging
import platform
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

_ID_FILENAME = "telemetry_id.txt"


def _compute_raw_id() -> str:
    """Hash stable per-user fingerprints into a 16-char hex ID."""
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    try:
        host = socket.gethostname()
    except Exception:
        host = ""
    fingerprint = "|".join([platform.system(), platform.node(), user, host])
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]


def get_machine_id(user_data_dir: Path) -> str:
    """Return a stable hashed install ID, caching to ``user_data_dir``.

    Never raises. Falls back to an in-memory computation if the cache
    file can't be read or written.
    """
    cache = Path(user_data_dir) / _ID_FILENAME
    try:
        if cache.exists():
            cached = cache.read_text(encoding="utf-8").strip()
            if cached:
                return cached
    except OSError as exc:
        logger.debug("telemetry_id cache read failed: %s", exc)

    value = _compute_raw_id()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(value, encoding="utf-8")
    except OSError as exc:
        logger.debug("telemetry_id cache write failed: %s", exc)
    return value
