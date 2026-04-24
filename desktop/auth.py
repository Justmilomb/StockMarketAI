"""Account auth client.

Stores a server-issued JWT under ``~/.blank/session.token`` and
exchanges it for user info via ``/api/auth/me``. Replaces the old
licence-key gate — users never see the underlying licence key; the
server still tracks them by it internally.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import requests

from desktop.license import _read_server_url

logger = logging.getLogger("blank.auth")

SESSION_FILE = Path.home() / ".blank" / "session.token"


def read_token() -> Optional[str]:
    if SESSION_FILE.exists():
        token = SESSION_FILE.read_text(encoding="utf-8").strip()
        return token or None
    return None


def save_token(token: str) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(token.strip(), encoding="utf-8")


def clear_token() -> None:
    try:
        SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


def fetch_me(
    token: Optional[str] = None,
    server_url: Optional[str] = None,
) -> dict[str, Any]:
    """Return ``{"ok": bool, "email"?, "name"?, "config"?, "reason"?}``.

    Network errors are non-fatal — the app still opens signed-out when
    the server is unreachable so a flaky connection doesn't brick a
    stored session. A 401/403 clears the stored token so the next
    launch stays signed-out instead of re-racing against a revoked
    account.
    """
    token = token or read_token()
    if not token:
        return {"ok": False, "reason": "no session token"}
    server_url = server_url or _read_server_url()
    try:
        resp = requests.get(
            f"{server_url.rstrip('/')}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.info("auth/me network error (continuing signed-out): %s", exc)
        return {"ok": False, "reason": "offline"}
    if resp.status_code in (401, 403):
        try:
            detail = resp.json().get("detail", "unauthorised")
        except Exception:
            detail = "unauthorised"
        clear_token()
        return {"ok": False, "reason": detail}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"server returned {resp.status_code}"}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "reason": "malformed server response"}
    return {"ok": True, **body}


def fetch_plan(
    token: Optional[str] = None,
    server_url: Optional[str] = None,
) -> dict[str, Any]:
    """Return ``{"ok": bool, "plan"?, "commission_pct"?, "monthly_fee"?, "is_dev"?}``.

    Mirrors :func:`fetch_me` semantics — offline / 4xx are non-fatal so the
    UI keeps working with whatever stored snapshot the AuthState has.
    """
    result = api_call("/api/me/plan", token=token, server_url=server_url)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "unknown")}
    data = result.get("data") or {}
    return {
        "ok": True,
        "plan": str(data.get("plan", "starter")),
        "commission_pct": float(data.get("commission_pct", 20.0)),
        "monthly_fee": float(data.get("monthly_fee", 0.0)),
        "is_dev": bool(data.get("is_dev", False)),
    }


def api_call(
    path: str,
    method: str = "GET",
    *,
    json_body: Optional[dict[str, Any]] = None,
    token: Optional[str] = None,
    server_url: Optional[str] = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Authenticated call to ``server_url + path``.

    Returns ``{"ok": bool, "data"?, "reason"?, "status"?}``. Same
    offline-tolerant contract as :func:`fetch_me`. Callers that need
    to dispatch several requests serialise on the returned dict
    instead of raising. 401/403 clears the stored token so the next
    launch stays signed-out.
    """
    token = token or read_token()
    if not token:
        return {"ok": False, "reason": "no session token"}
    server_url = server_url or _read_server_url()
    url = f"{server_url.rstrip('/')}{path}"
    try:
        resp = requests.request(
            method.upper(), url,
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.info("api %s %s network error: %s", method, path, exc)
        return {"ok": False, "reason": "offline"}
    if resp.status_code in (401, 403):
        clear_token()
        return {"ok": False, "reason": "unauthorised", "status": resp.status_code}
    if resp.status_code >= 400:
        return {"ok": False, "reason": f"server returned {resp.status_code}", "status": resp.status_code}
    try:
        body = resp.json()
    except Exception:
        return {"ok": False, "reason": "malformed server response"}
    return {"ok": True, "data": body, "status": resp.status_code}
