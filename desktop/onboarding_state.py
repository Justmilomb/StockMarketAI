"""Per-mode onboarding state — "don't show again" with silent 30-day reset.

Paper and live mode each have their own onboarding flow and their own
independent "don't show again" flag. When the user ticks the checkbox
we store an expiry timestamp 30 days from now; once that expires we
silently forget the flag so the walkthrough comes back without telling
the user. The 30-day window is the minimum spec the user asked for —
we never tell them the flag auto-resets.

T212 credentials helpers also live here: the live-mode onboarding needs
to know whether a key is already saved (so it can skip its API-key
step) and needs a place to persist what the user typed. We write to
``.env`` in the user data dir — the same file ``desktop.main._load_dotenv``
reads on startup — and feed ``os.environ`` in the current process so
the rest of the app sees the new values without a restart.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

_DONT_SHOW_DAYS = 30
_STATE_FILENAME = "onboarding_state.json"


# ─── Path helpers ────────────────────────────────────────────────────

def _state_path() -> Path:
    try:
        from desktop.paths import user_data_dir
        return user_data_dir() / _STATE_FILENAME
    except Exception:
        return Path.home() / ".blank" / _STATE_FILENAME


def _dotenv_path() -> Path:
    try:
        from desktop.paths import dotenv_path
        return dotenv_path()
    except Exception:
        return Path.cwd() / ".env"


# ─── State I/O ───────────────────────────────────────────────────────

def _load() -> dict:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("onboarding_state: unreadable state file (%s) — resetting", exc)
        return {}


def _save(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ─── Public API: should_show / mark_done ─────────────────────────────

def reset_expired_flags() -> None:
    """Silently clear any "don't show" entries whose 30-day window has passed.

    Safe to call on every launch. Deliberately quiet — we never surface
    the reset to the user; the onboarding just re-appears.
    """
    data = _load()
    now = datetime.now(timezone.utc)
    changed = False
    for mode in ("paper", "live"):
        entry = data.get(mode)
        if not isinstance(entry, dict):
            continue
        until_raw = entry.get("dont_show_until")
        if not until_raw:
            continue
        try:
            until = datetime.fromisoformat(str(until_raw))
        except ValueError:
            entry.pop("dont_show_until", None)
            changed = True
            continue
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if now >= until:
            entry.pop("dont_show_until", None)
            changed = True
    if changed:
        _save(data)


def _should_show(mode: str) -> bool:
    data = _load()
    entry = data.get(mode)
    if not isinstance(entry, dict):
        return True
    until_raw = entry.get("dont_show_until")
    if not until_raw:
        return True
    try:
        until = datetime.fromisoformat(str(until_raw))
    except ValueError:
        return True
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= until


def should_show_paper() -> bool:
    """Return True if the paper onboarding should be shown this launch."""
    return _should_show("paper")


def should_show_live() -> bool:
    """Return True if the live onboarding walkthrough should be shown.

    Note: the T212-key *step* inside live onboarding is enforced
    independently — if no credentials are saved, the onboarding is shown
    regardless of this flag. See ``desktop.main`` for the gating logic.
    """
    return _should_show("live")


def _mark_done(mode: str, dont_show_again: bool) -> None:
    data = _load()
    entry = data.setdefault(mode, {}) if isinstance(data.get(mode), dict) else {}
    data[mode] = entry
    now = datetime.now(timezone.utc)
    entry["completed_at"] = now.isoformat()
    if dont_show_again:
        entry["dont_show_until"] = (now + timedelta(days=_DONT_SHOW_DAYS)).isoformat()
    else:
        entry.pop("dont_show_until", None)
    _save(data)


def mark_paper_done(dont_show_again: bool) -> None:
    _mark_done("paper", dont_show_again)


def mark_live_done(dont_show_again: bool) -> None:
    _mark_done("live", dont_show_again)


# ─── T212 credentials (stored in user .env) ──────────────────────────

def has_t212_credentials() -> bool:
    """Return True if both T212_API_KEY and T212_SECRET_KEY are set."""
    api = (os.environ.get("T212_API_KEY") or "").strip()
    secret = (os.environ.get("T212_SECRET_KEY") or "").strip()
    if api and secret:
        return True
    # The process might have been launched before .env was written;
    # re-read the file just in case.
    env_vars = _read_dotenv()
    return bool(env_vars.get("T212_API_KEY")) and bool(env_vars.get("T212_SECRET_KEY"))


def _read_dotenv() -> dict:
    path = _dotenv_path()
    out: dict = {}
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def save_t212_credentials(api_key: str, secret_key: str) -> None:
    """Persist T212 creds to the user .env and refresh the running process.

    Merges with any existing .env content — other environment entries
    (unrelated keys) are preserved.
    """
    api_key = api_key.strip()
    secret_key = secret_key.strip()
    env_vars = _read_dotenv()
    env_vars["T212_API_KEY"] = api_key
    env_vars["T212_SECRET_KEY"] = secret_key
    path = _dotenv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{k}={v}" for k, v in env_vars.items() if k) + "\n",
        encoding="utf-8",
    )
    os.environ["T212_API_KEY"] = api_key
    os.environ["T212_SECRET_KEY"] = secret_key


def validate_t212_credentials(
    api_key: str,
    secret_key: str,
    *,
    practice: bool = False,
) -> Tuple[bool, str]:
    """Test a T212 API key pair by calling ``/equity/account/cash``.

    Returns ``(ok, message)``. ``message`` is safe to show the user.
    Hits the live endpoint by default; pass ``practice=True`` to test
    against the demo endpoint instead.
    """
    api_key = api_key.strip()
    secret_key = secret_key.strip()
    if not api_key:
        return False, "Enter an API key."
    if not secret_key:
        return False, "Enter an API secret."

    try:
        import base64
        import requests
    except ImportError:
        return False, "Network library missing — reinstall blank."

    base_url = (
        "https://demo.trading212.com" if practice else "https://live.trading212.com"
    )
    token = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(
            f"{base_url}/api/v0/equity/account/cash",
            headers=headers,
            timeout=15,
        )
    except requests.RequestException as exc:
        return False, f"Network error: {exc.__class__.__name__}."

    if resp.status_code == 200:
        return True, "Key works. You're ready to trade live."
    if resp.status_code in (401, 403):
        return False, "Key rejected by Trading 212 — double-check the value."
    if resp.status_code == 429:
        return False, "Trading 212 rate-limited the check. Try again in a minute."
    return False, f"Trading 212 returned HTTP {resp.status_code}."
