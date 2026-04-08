"""License validation client — gates the app behind a valid server-issued key."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger("blank.license")

LICENSE_FILE = Path.home() / ".blank" / "license.key"
DEFAULT_SERVER = "http://localhost:8000"


def _read_server_url() -> str:
    """Read server URL from config.json next to the exe, falling back to env/default."""
    import json
    # check config.json in working directory
    config_path = Path("config.json")
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            url = cfg.get("server", {}).get("url", "")
            if url:
                return url.rstrip("/")
        except Exception:
            pass
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


def validate(server_url: Optional[str] = None, key: Optional[str] = None) -> dict[str, Any]:
    """Validate a license key against the server.

    Returns dict with 'valid' bool, plus 'reason' on failure
    or 'config', 'email', 'name' on success.
    """
    server_url = server_url or _read_server_url()
    key = key or _read_stored_key()
    if not key:
        return {"valid": False, "reason": "no license key found"}

    try:
        resp = requests.post(
            f"{server_url.rstrip('/')}/api/license/validate",
            json={"key": key, "machine_id": _machine_id()},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        return {"valid": False, "reason": f"server returned {resp.status_code}"}
    except requests.ConnectionError:
        return {"valid": False, "reason": "cannot reach license server"}
    except requests.Timeout:
        return {"valid": False, "reason": "license server timeout"}
    except Exception as exc:
        return {"valid": False, "reason": str(exc)}


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
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False
