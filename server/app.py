"""Blank admin server — FastAPI backend for license validation, telemetry, config, and logs."""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator, Optional

import psycopg2
import psycopg2.extras
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

logger = logging.getLogger("blank.server")

# ── Config ───────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ADMIN_KEY = os.environ.get("BLANK_ADMIN_KEY", "admin")
WEBSITE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "website")

# ── Database ─────────────────────────────────────────────────────────────

def _init_db(conn: psycopg2.extensions.connection) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS licenses (
                id SERIAL PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                name TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                last_active TIMESTAMPTZ,
                machine_id TEXT
            );
            CREATE TABLE IF NOT EXISTS downloads (
                id SERIAL PRIMARY KEY,
                ip TEXT,
                user_agent TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                license_key TEXT,
                level TEXT,
                message TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            );
        """)
    conn.commit()
    # seed default config if empty
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM config")
        if cur.fetchone()["c"] == 0:
            defaults = [
                ("kill_switch", "false"),
                ("maintenance_mode", "false"),
                ("force_update", "false"),
            ]
            for k, v in defaults:
                cur.execute("INSERT INTO config (key, value) VALUES (%s, %s)", (k, v))
    conn.commit()


@contextmanager
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def db_dependency() -> Generator[psycopg2.extensions.connection, None, None]:
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
    with get_db() as conn:
        _init_db(conn)
    logger.info("blank server started — db: postgres")


# ── Website serving ──────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def landing_page() -> HTMLResponse:
    with open(os.path.join(WEBSITE_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    with open(os.path.join(WEBSITE_DIR, "admin.html"), encoding="utf-8") as f:
        html = f.read()
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
        "download_url_bloomberg": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/BlankBloombergSetup.exe",
        "download_url_simple": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/BlankSimpleSetup.exe",
    }


# ── License endpoints (public) ───────────────────────────────────────────

@app.post("/api/license/validate")
def validate_license(
    body: LicenseValidateRequest,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE key = %s", (body.key,))
        row = cur.fetchone()

    if not row:
        return {"valid": False, "reason": "license key not found"}

    if row["status"] == "revoked":
        return {"valid": False, "reason": "license has been revoked"}

    if row["status"] == "expired":
        return {"valid": False, "reason": "license has expired"}

    # check expiry date
    if row["expires_at"]:
        expires = row["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            with conn.cursor() as cur:
                cur.execute("UPDATE licenses SET status = 'expired' WHERE key = %s", (body.key,))
            conn.commit()
            return {"valid": False, "reason": "license has expired"}

    # update last active + machine id
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE licenses SET last_active = NOW(), machine_id = %s WHERE key = %s",
            (body.machine_id or row["machine_id"], body.key),
        )
    conn.commit()

    # fetch remote config
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM config")
        config_rows = cur.fetchall()
    remote_config = {r["key"]: r["value"] for r in config_rows}

    return {
        "valid": True,
        "status": row["status"],
        "email": row["email"],
        "name": row["name"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "config": remote_config,
    }


# ── Download tracking (public) ──────────────────────────────────────────

@app.post("/api/download")
def track_download(
    request: Request,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO downloads (ip, user_agent) VALUES (%s, %s)", (ip, ua))
    conn.commit()
    return {"status": "tracked"}


# ── Telemetry / logs (public, requires valid license key) ────────────────

@app.post("/api/logs")
def ingest_logs(
    body: LogBatch,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM licenses WHERE key = %s", (body.license_key,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="invalid license key")

    with conn.cursor() as cur:
        for e in body.entries:
            cur.execute(
                "INSERT INTO logs (license_key, level, message) VALUES (%s, %s, %s)",
                (body.license_key, e.level, e.message),
            )
    conn.commit()
    return {"status": "ok", "count": str(len(body.entries))}


# ── Admin: stats ─────────────────────────────────────────────────────────

@app.get("/api/admin/stats")
def admin_stats(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM downloads")
        total_downloads = cur.fetchone()["c"]

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        cur.execute("SELECT COUNT(*) AS c FROM downloads WHERE created_at >= %s", (week_ago,))
        week_downloads = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE status = 'active'")
        total_licenses = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE status = 'trial'")
        trial_licenses = cur.fetchone()["c"]

        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE last_active >= %s", (day_ago,))
        active_users = cur.fetchone()["c"]

        soon = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "SELECT COUNT(*) AS c FROM licenses WHERE expires_at BETWEEN %s AND %s AND status = 'active'",
            (now, soon),
        )
        expiring_soon = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM logs WHERE level = 'error' AND created_at >= %s", (day_ago,))
        errors_24h = cur.fetchone()["c"]

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
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    """Daily download counts for the last N days."""
    results = []
    with conn.cursor() as cur:
        for i in range(days - 1, -1, -1):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            cur.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE created_at::date = %s",
                (date,),
            )
            results.append({"date": date, "count": cur.fetchone()["c"]})
    return results


# ── Admin: licenses ──────────────────────────────────────────────────────

@app.get("/api/admin/licenses")
def admin_list_licenses(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM licenses ORDER BY created_at DESC")
        rows = cur.fetchall()
    # serialise datetimes
    results = []
    for r in rows:
        d = dict(r)
        for k in ("created_at", "expires_at", "last_active"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        results.append(d)
    return results


def _generate_license_key() -> str:
    """Generate a key like BLK-7F2A-X9D1."""
    parts = [secrets.token_hex(2).upper() for _ in range(2)]
    return f"BLK-{parts[0]}-{parts[1]}"


@app.post("/api/admin/licenses")
def admin_create_license(
    body: LicenseCreateRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    key = _generate_license_key()
    expires = (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO licenses (key, email, name, status, expires_at) VALUES (%s, %s, %s, 'active', %s)",
            (key, body.email, body.name, expires),
        )
    conn.commit()
    return {"key": key, "email": body.email, "expires_at": expires}


@app.put("/api/admin/licenses/{license_key}")
def admin_update_license(
    license_key: str,
    body: LicenseUpdateRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM licenses WHERE key = %s", (license_key,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="license not found")

    with conn.cursor() as cur:
        if body.status:
            cur.execute("UPDATE licenses SET status = %s WHERE key = %s", (body.status, license_key))
        if body.email:
            cur.execute("UPDATE licenses SET email = %s WHERE key = %s", (body.email, license_key))
        if body.name:
            cur.execute("UPDATE licenses SET name = %s WHERE key = %s", (body.name, license_key))
        if body.days:
            expires = (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat()
            cur.execute("UPDATE licenses SET expires_at = %s WHERE key = %s", (expires, license_key))
    conn.commit()
    return {"status": "updated"}


@app.delete("/api/admin/licenses/{license_key}")
def admin_revoke_license(
    license_key: str,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("UPDATE licenses SET status = 'revoked' WHERE key = %s", (license_key,))
    conn.commit()
    return {"status": "revoked"}


# ── Admin: config ────────────────────────────────────────────────────────

@app.get("/api/admin/config")
def admin_get_config(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM config")
        rows = cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


@app.put("/api/admin/config")
def admin_update_config(
    body: ConfigUpdateRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (body.key, body.value),
        )
    conn.commit()
    return {"status": "updated"}


# ── Admin: logs ──────────────────────────────────────────────────────────

@app.get("/api/admin/logs")
def admin_get_logs(
    limit: int = 50,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("created_at") is not None:
            d["created_at"] = d["created_at"].isoformat()
        results.append(d)
    return results


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
