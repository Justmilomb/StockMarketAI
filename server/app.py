"""Blank admin server — FastAPI backend for license validation, telemetry, config, and logs."""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger("blank.server")

# ── Config ───────────────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get("BLANK_DB_PATH", "server/blank.db"))
ADMIN_KEY = os.environ.get("BLANK_ADMIN_KEY", "admin")
WEBSITE_DIR = Path(__file__).resolve().parent.parent / "website"

# ── Database ─────────────────────────────────────────────────────────────

def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            name TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT,
            last_active TEXT,
            machine_id TEXT
        );
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT,
            level TEXT,
            message TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
    """)
    # seed default config if empty
    cursor = conn.execute("SELECT COUNT(*) FROM config")
    if cursor.fetchone()[0] == 0:
        defaults = [
            # kill switches — these block the app from running
            ("kill_switch", "false"),          # emergency stop: app exits immediately
            ("maintenance_mode", "false"),     # pauses app, shows "back soon" message

            # update control
            ("force_update", "false"),         # shows update prompt on next launch
            ("update_url", ""),                # download URL for the new installer

            # trading controls — remotely override user config
            ("auto_trading", "true"),          # allow autonomous trade execution
            ("paper_mode", "true"),            # force paper mode (safety net)

            # strategy params — remotely tune risk
            ("max_position_pct", "5"),         # max single position as % of portfolio
            ("confidence_threshold", "0.65"),  # min confidence to execute a trade
            ("trailing_stop_pct", "2.5"),      # trailing stop loss %
            ("refresh_interval_s", "300"),     # seconds between pipeline runs
        ]
        conn.executemany(
            "INSERT INTO config (key, value) VALUES (?, ?)", defaults,
        )
        conn.commit()


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def db_dependency() -> Generator[sqlite3.Connection, None, None]:
    with get_db() as conn:
        yield conn


# ── Pydantic models ──────────────────────────────────────────────────────

class LicenseValidateRequest(BaseModel):
    key: str
    machine_id: str = ""


class LicenseCreateRequest(BaseModel):
    email: str
    name: str = ""
    days: int = 365


class LicenseUpdateRequest(BaseModel):
    status: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    days: Optional[int] = None


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str


class LogEntry(BaseModel):
    level: str
    message: str


class LogBatch(BaseModel):
    license_key: str
    entries: list[LogEntry]


# ── Auth ─────────────────────────────────────────────────────────────────

def require_admin(x_admin_key: str = Header(...)) -> str:
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="invalid admin key")
    return x_admin_key


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(title="blank admin", docs_url="/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        _init_db(conn)
    logger.info("blank server started — db: %s", DB_PATH)


# ── Website serving ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def landing_page() -> HTMLResponse:
    html = (WEBSITE_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    html = (WEBSITE_DIR / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


# ── Health / version (public) ────────────────────────────────────────────

@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Simple health check for app connectivity verification."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/version")
def version_info() -> dict[str, str]:
    """Version info for the desktop update checker."""
    return {
        "version": "1.0.0",
        "download_url": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/BlankSetup.exe",
    }


# ── License endpoints (public) ───────────────────────────────────────────

@app.post("/api/license/validate")
def validate_license(
    body: LicenseValidateRequest,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM licenses WHERE key = ?", (body.key,),
    ).fetchone()

    if not row:
        return {"valid": False, "reason": "license key not found"}

    if row["status"] == "revoked":
        return {"valid": False, "reason": "license has been revoked"}

    if row["status"] == "expired":
        return {"valid": False, "reason": "license has expired"}

    # check expiry date
    if row["expires_at"]:
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
            conn.execute(
                "UPDATE licenses SET status = 'expired' WHERE key = ?",
                (body.key,),
            )
            conn.commit()
            return {"valid": False, "reason": "license has expired"}

    # update last active + machine id
    conn.execute(
        "UPDATE licenses SET last_active = datetime('now'), machine_id = ? WHERE key = ?",
        (body.machine_id or row["machine_id"], body.key),
    )
    conn.commit()

    # fetch remote config
    config_rows = conn.execute("SELECT key, value FROM config").fetchall()
    remote_config = {r["key"]: r["value"] for r in config_rows}

    return {
        "valid": True,
        "status": row["status"],
        "email": row["email"],
        "name": row["name"],
        "expires_at": row["expires_at"],
        "config": remote_config,
    }


# ── Download tracking (public) ──────────────────────────────────────────

@app.post("/api/download")
def track_download(
    request: Request,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    conn.execute(
        "INSERT INTO downloads (ip, user_agent) VALUES (?, ?)", (ip, ua),
    )
    conn.commit()
    return {"status": "tracked"}


# ── Telemetry / logs (public, requires valid license key) ────────────────

@app.post("/api/logs")
def ingest_logs(
    body: LogBatch,
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    # verify license exists
    row = conn.execute(
        "SELECT id FROM licenses WHERE key = ?", (body.license_key,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="invalid license key")

    conn.executemany(
        "INSERT INTO logs (license_key, level, message) VALUES (?, ?, ?)",
        [(body.license_key, e.level, e.message) for e in body.entries],
    )
    conn.commit()
    return {"status": "ok", "count": str(len(body.entries))}


# ── Admin: stats ─────────────────────────────────────────────────────────

@app.get("/api/admin/stats")
def admin_stats(
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, Any]:
    total_downloads = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    week_downloads = conn.execute(
        "SELECT COUNT(*) FROM downloads WHERE created_at >= ?", (week_ago,),
    ).fetchone()[0]

    total_licenses = conn.execute(
        "SELECT COUNT(*) FROM licenses WHERE status = 'active'",
    ).fetchone()[0]
    trial_licenses = conn.execute(
        "SELECT COUNT(*) FROM licenses WHERE status = 'trial'",
    ).fetchone()[0]

    # active users = licenses with last_active in the last 24h
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    active_users = conn.execute(
        "SELECT COUNT(*) FROM licenses WHERE last_active >= ?", (day_ago,),
    ).fetchone()[0]

    # expiring soon = within 7 days
    soon = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    expiring_soon = conn.execute(
        "SELECT COUNT(*) FROM licenses WHERE expires_at BETWEEN ? AND ? AND status = 'active'",
        (now, soon),
    ).fetchone()[0]

    # error count last 24h
    errors_24h = conn.execute(
        "SELECT COUNT(*) FROM logs WHERE level = 'error' AND created_at >= ?",
        (day_ago,),
    ).fetchone()[0]

    return {
        "total_downloads": total_downloads,
        "week_downloads": week_downloads,
        "active_licenses": total_licenses,
        "trial_licenses": trial_licenses,
        "active_users": active_users,
        "expiring_soon": expiring_soon,
        "errors_24h": errors_24h,
    }


@app.get("/api/admin/downloads")
def admin_downloads(
    days: int = 14,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    """Daily download counts for the last N days."""
    results = []
    for i in range(days - 1, -1, -1):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM downloads WHERE date(created_at) = ?",
            (date,),
        ).fetchone()[0]
        results.append({"date": date, "count": count})
    return results


# ── Admin: licenses ──────────────────────────────────────────────────────

@app.get("/api/admin/licenses")
def admin_list_licenses(
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM licenses ORDER BY created_at DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def _generate_license_key() -> str:
    """Generate a key like BLK-7F2A-X9D1."""
    parts = [secrets.token_hex(2).upper() for _ in range(2)]
    return f"BLK-{parts[0]}-{parts[1]}"


@app.post("/api/admin/licenses")
def admin_create_license(
    body: LicenseCreateRequest,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, Any]:
    key = _generate_license_key()
    expires = (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat()
    conn.execute(
        "INSERT INTO licenses (key, email, name, status, expires_at) VALUES (?, ?, ?, 'active', ?)",
        (key, body.email, body.name, expires),
    )
    conn.commit()
    return {"key": key, "email": body.email, "expires_at": expires}


@app.put("/api/admin/licenses/{license_key}")
def admin_update_license(
    license_key: str,
    body: LicenseUpdateRequest,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    row = conn.execute(
        "SELECT id FROM licenses WHERE key = ?", (license_key,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="license not found")

    if body.status:
        conn.execute("UPDATE licenses SET status = ? WHERE key = ?", (body.status, license_key))
    if body.email:
        conn.execute("UPDATE licenses SET email = ? WHERE key = ?", (body.email, license_key))
    if body.name:
        conn.execute("UPDATE licenses SET name = ? WHERE key = ?", (body.name, license_key))
    if body.days:
        expires = (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat()
        conn.execute("UPDATE licenses SET expires_at = ? WHERE key = ?", (expires, license_key))

    conn.commit()
    return {"status": "updated"}


@app.delete("/api/admin/licenses/{license_key}")
def admin_revoke_license(
    license_key: str,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    conn.execute(
        "UPDATE licenses SET status = 'revoked' WHERE key = ?", (license_key,),
    )
    conn.commit()
    return {"status": "revoked"}


# ── Admin: config ────────────────────────────────────────────────────────

@app.get("/api/admin/config")
def admin_get_config(
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.put("/api/admin/config")
def admin_update_config(
    body: ConfigUpdateRequest,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> dict[str, str]:
    conn.execute(
        "INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (body.key, body.value),
    )
    conn.commit()
    return {"status": "updated"}


# ── Admin: logs ──────────────────────────────────────────────────────────

@app.get("/api/admin/logs")
def admin_get_logs(
    limit: int = 50,
    _: str = Depends(require_admin),
    conn: sqlite3.Connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
