"""Shared license-server helpers (URL + machine id).

The user-facing licence-key flow was retired when we moved to account
authentication. We keep this module because a handful of callers still
need ``_read_server_url()`` and ``_machine_id()`` — the heartbeat, the
dev-monitor, and the auth client all reach for them. The legacy
``validate`` / ``save_key`` / ``_read_stored_key`` entry points are
kept as stubs so any stray import still resolves, but they no longer
do anything.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import uuid
from typing import Any, Optional

import requests

logger = logging.getLogger("blank.license")

# Hardcoded so a stale config.json from a previous install cannot point us at a
# dead URL. Override for dev via BLANK_SERVER_URL env var.
DEFAULT_SERVER = "https://blan-api.onrender.com"


def _read_server_url() -> str:
    """Return the license server URL. BLANK_SERVER_URL env var overrides."""
    return os.environ.get("BLANK_SERVER_URL", DEFAULT_SERVER)


def _machine_id() -> str:
    """Stable per-machine identifier (hashed MAC + hostname)."""
    raw = f"{uuid.getnode()}-{platform.node()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _read_stored_key() -> Optional[str]:
    """Compat stub — we no longer store licence keys on disk."""
    return None


def save_key(_key: str) -> None:
    """Compat stub — kept so stray imports from the old dialog don't blow up."""
    return None


def validate(
    server_url: Optional[str] = None,
    key: Optional[str] = None,
    status_callback: Optional[Any] = None,
) -> dict[str, Any]:
    """Compat stub — always reports invalid so any caller falls through to
    the signed-out path."""
    return {"valid": False, "reason": "licence flow retired"}


def send_logs(
    entries: list[dict[str, str]],
    server_url: Optional[str] = None,
    key: Optional[str] = None,
) -> bool:
    """Best-effort POST of agent log entries. Now keyed by the JWT session
    token instead of a licence key — the server accepts either.
    """
    server_url = server_url or _read_server_url()
    if key is None:
        from desktop.auth import read_token
        key = read_token() or ""
    if not key:
        return False
    try:
        resp = requests.post(
            f"{server_url.rstrip('/')}/api/logs",
            json={"license_key": key, "entries": entries},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False
