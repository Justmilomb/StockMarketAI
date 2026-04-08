"""Update checker — compares local version against a remote version file.

On startup the app hits a single URL to check for newer versions.
If one exists, shows a non-blocking notification with a download link.
No auto-download, no background service — just a version check.

Setup:
  Host a JSON file at your UPDATE_URL containing:
  {"version": "1.1.0", "download_url": "https://example.com/BlankSetup.exe"}

  Update UPDATE_URL below to point to your hosted file.
"""
from __future__ import annotations

import logging
from typing import Optional

from packaging.version import Version

from desktop import __version__

logger = logging.getLogger(__name__)

# Point this at a raw JSON file you control (GitHub releases, S3, your server)
UPDATE_URL = "https://blank-api.onrender.com/api/version"


def check_for_update() -> Optional[dict]:
    """Check if a newer version is available.

    Returns {"version": "x.y.z", "download_url": "..."} if update exists,
    None otherwise. Never raises — returns None on any error.
    """
    if not UPDATE_URL:
        return None

    try:
        import requests
        resp = requests.get(UPDATE_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        remote_version = data.get("version", "")
        if not remote_version:
            return None

        if Version(remote_version) > Version(__version__):
            return {
                "version": remote_version,
                "download_url": data.get("download_url", ""),
            }
    except Exception as exc:
        logger.debug("Update check failed: %s", exc)

    return None
