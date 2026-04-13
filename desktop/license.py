"""License validation client — gates the app behind a valid server-issued key."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("blank.license")

LICENSE_FILE = Path.home() / ".blank" / "license.key"
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
    if LICENSE_FILE.exists():
        return LICENSE_FILE.read_text(encoding="utf-8").strip()
    return None


def save_key(key: str) -> None:
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(key.strip(), encoding="utf-8")


def validate(
    server_url: Optional[str] = None,
    key: Optional[str] = None,
    status_callback: Optional[Any] = None,
) -> dict[str, Any]:
    """Validate a license key against the server.

    Returns dict with 'valid' bool, plus 'reason' on failure
    or 'config', 'email', 'name' on success.

    Retries up to 3 times with increasing timeouts to handle
    Render free-tier cold starts (30-60s).
    """
    server_url = server_url or _read_server_url()
    key = key or _read_stored_key()
    if not key:
        return {"valid": False, "reason": "no license key found"}

    url = f"{server_url.rstrip('/')}/api/license/validate"
    payload = {"key": key, "machine_id": _machine_id()}
    timeouts = [20, 40, 60]

    for attempt, timeout in enumerate(timeouts):
        if status_callback:
            if attempt == 0:
                status_callback("CONNECTING...")
            else:
                status_callback(f"WAKING SERVER... (ATTEMPT {attempt + 1}/3)")

        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            return {"valid": False, "reason": f"server returned {resp.status_code}"}
        except requests.ConnectionError:
            if attempt < len(timeouts) - 1:
                logger.info("Connection failed (attempt %d), retrying...", attempt + 1)
                continue
            return {"valid": False, "reason": "cannot reach license server"}
        except requests.Timeout:
            if attempt < len(timeouts) - 1:
                logger.info("Timeout after %ds (attempt %d), retrying...", timeout, attempt + 1)
                continue
            return {"valid": False, "reason": "license server timeout"}
        except Exception as exc:
            return {"valid": False, "reason": str(exc)}

    return {"valid": False, "reason": "license server timeout"}


def send_logs(
    entries: list[dict[str, str]],
    server_url: Optional[str] = None,
    key: Optional[str] = None,
) -> bool:
    """Send log entries to the server. Returns True on success."""
    server_url = server_url or _read_server_url()
    key = key or _read_stored_key()
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
