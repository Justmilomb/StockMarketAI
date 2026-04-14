"""blank admin server — FastAPI backend for license validation, telemetry, config, and logs."""
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
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
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
            CREATE TABLE IF NOT EXISTS releases (
                id SERIAL PRIMARY KEY,
                version TEXT UNIQUE NOT NULL,
                download_url TEXT NOT NULL,
                sha256 TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                mandatory BOOLEAN DEFAULT FALSE,
                published_at TIMESTAMPTZ DEFAULT NOW(),
                is_current BOOLEAN DEFAULT TRUE,
                scheduled_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS idx_releases_current ON releases(is_current);
        """)
        # Additive migration for databases that pre-date scheduled releases.
        # Must run before creating the scheduled_at index — if the table already
        # exists without this column, the index CREATE above would fail with
        # UndefinedColumn and abort the whole transaction.
        cur.execute(
            "ALTER TABLE releases ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ",
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_releases_schedule ON releases(scheduled_at)",
        )
    conn.commit()
    # seed default config if missing — use INSERT … ON CONFLICT DO NOTHING so
    # re-runs on an existing database never overwrite admin changes.
    with conn.cursor() as cur:
        defaults = [
            ("maintenance_mode", "false"),
            ("maintenance_message", ""),
            ("notification_message", ""),
            ("notification_at", ""),
        ]
        for k, v in defaults:
            cur.execute(
                "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (k, v),
            )
    conn.commit()
    # seed release history — upserts notes/dates so the website always shows
    # the full version timeline. is_current=TRUE only on the latest version;
    # the api/version endpoint serves whichever row has is_current=TRUE.
    with conn.cursor() as cur:
        # (version, published_at, is_current, notes)
        seed_releases = [
            (
                "1.0.0",
                "2025-10-14",
                False,
                "- first public release — ai-powered stock analysis in a bloomberg-style terminal\n"
                "- live prices, candlestick charts, and full portfolio tracking from day one\n"
                "- ask the ai anything: earnings, macro, sector rotation, your own positions\n"
                "- paper trading mode so you can test strategies without real money on the line",
            ),
            (
                "1.0.1",
                "2026-03-20",
                False,
                "- fixed the chart freezing when switching tickers quickly\n"
                "- ai responses no longer cut off mid-sentence on slow connections\n"
                "- installer no longer requires admin rights\n"
                "- startup is roughly 40% faster on cold boot",
            ),
            (
                "1.1.0",
                "2026-03-25",
                False,
                "- portfolio heat map: all your positions at a glance, colour-coded by gain/loss\n"
                "- watchlist now persists across sessions\n"
                "- ai now reads full earnings transcripts, not just headlines\n"
                "- added keyboard shortcuts for the most common chart actions",
            ),
            (
                "1.2.0",
                "2026-03-30",
                False,
                "- multi-timeframe forecasts: 1-day, 5-day, and 20-day outlooks run in parallel\n"
                "- five specialised analyst personas now debate every trade before a signal fires\n"
                "- regime detection — the ai knows whether we are in bull, bear, or sideways conditions\n"
                "- backtesting engine: replay any strategy against up to five years of history",
            ),
            (
                "2.0.0",
                "2026-04-03",
                False,
                "- complete ui rebuild — faster, sharper, more bloomberg than bloomberg\n"
                "- live trading via trading 212 alongside paper mode\n"
                "- ai ensemble: twelve machine-learning models vote on every trade simultaneously\n"
                "- risk manager: kelly criterion sizing, atr-based stops, portfolio drawdown limits\n"
                "- background news scanner feeds the ai real-time rss sentiment around the clock",
            ),
            (
                "2.0.1",
                "2026-04-06",
                False,
                "- fixed positions panel showing stale prices after market close\n"
                "- chat no longer hangs if the ai takes more than 30 seconds to respond\n"
                "- portfolio value now updates in real time instead of on the next price tick\n"
                "- fixed a crash when opening the app with no internet connection\n"
                "- blank now installs updates automatically — no manual reinstall required\n"
                "- maintenance messages from the team appear inside the app without restarting",
            ),
            (
                "2.1.0",
                "2026-04-07",
                True,
                "- chat replies come back in seconds, not at the end of the next iteration\n"
                "- ask blank several questions at once — answers come back in parallel\n"
                "- paper mode is impossible to miss: gold banner, watermark, one-click flip to live\n"
                "- paper positions and cash save between sessions instead of resetting\n"
                "- smarter ai picks — fast model for info, careful model for real trade decisions\n"
                "- new chat command: \"clear my watchlist except what i own\"\n"
                "- removed the invisible thinking-time cap so the ai can finish its work",
            ),
        ]
        base_url = "https://github.com/Justmilomb/StockMarketAI/releases/download"
        for version, pub_date, is_current, notes in seed_releases:
            url = f"{base_url}/v{version}/BlankSetup.exe"
            cur.execute(
                """
                INSERT INTO releases (version, download_url, sha256, notes, mandatory,
                                      is_current, published_at)
                VALUES (%s, %s, '', %s, FALSE, %s, %s::date)
                ON CONFLICT (version) DO UPDATE SET
                    notes        = EXCLUDED.notes,
                    published_at = EXCLUDED.published_at
                """,
                (version, url, notes, is_current, pub_date),
            )
    conn.commit()


@contextmanager
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor, connect_timeout=5)
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


class ReleaseCreateRequest(BaseModel):
    version: str
    download_url: str
    sha256: str = ""
    notes: str = ""
    mandatory: bool = False
    scheduled_at: Optional[str] = None  # ISO-8601 UTC; None = publish immediately


class ScheduleNotificationRequest(BaseModel):
    message: str
    notify_at: str  # ISO-8601 UTC timestamp


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
    try:
        with get_db() as conn:
            _init_db(conn)
        logger.info("blank server started — db: postgres")
    except Exception as e:
        logger.error("failed to initialise database: %s", e)
        raise


# ── Website serving ──────────────────────────────────────────────────────

def _escape_html(s: str) -> str:
    """Minimal HTML escape for user-supplied release notes and versions."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_releases_html(conn: psycopg2.extensions.connection) -> str:
    """Render the public release list as `<li class="release">…</li>` blocks.

    Scheduled releases whose time has not arrived are excluded — they become
    visible automatically on the next request after ``scheduled_at`` passes,
    so there is no background job to run. The most recent *visible* release
    is tagged with ``latest`` so the stylesheet glows its version in green.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT version, notes, published_at, scheduled_at
              FROM releases
             WHERE scheduled_at IS NULL OR scheduled_at <= NOW()
             ORDER BY COALESCE(scheduled_at, published_at) DESC
            """,
        )
        rows = cur.fetchall()

    if not rows:
        return (
            '            <li class="release latest">\n'
            '                <div class="release-head">\n'
            '                    <span class="version">coming soon</span>\n'
            '                </div>\n'
            '                <ul class="release-notes">\n'
            "                    <li>the first public release hasn't shipped yet — check back soon</li>\n"
            '                </ul>\n'
            "            </li>"
        )

    blocks: list[str] = []
    for i, row in enumerate(rows):
        classes = "release latest" if i == 0 else "release"
        version = f"v{row['version']}"
        when = row["scheduled_at"] or row["published_at"]
        date_str = when.strftime("%B %Y").lower() if when else ""

        raw = (row["notes"] or "").strip()
        bullets: list[str] = []
        for ln in raw.splitlines():
            s = ln.strip()
            if s.startswith(("-", "*", "•")):
                s = s[1:].strip()
            if s:
                bullets.append(s)
        if not bullets:
            bullets = ["no release notes"]

        bullets_html = "\n".join(
            f"                    <li>{_escape_html(b)}</li>" for b in bullets
        )
        blocks.append(
            f'            <li class="{classes}">\n'
            f'                <div class="release-head">\n'
            f'                    <span class="version">{_escape_html(version)}</span>\n'
            f'                    <span class="date">{_escape_html(date_str)}</span>\n'
            f'                </div>\n'
            f'                <ul class="release-notes">\n'
            f"{bullets_html}\n"
            f"                </ul>\n"
            f"            </li>"
        )

    return "\n".join(blocks)


@app.get("/", response_class=HTMLResponse)
def landing_page(
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> HTMLResponse:
    """Serve the landing page with the update log injected from the DB.

    The template carries a ``<!-- RELEASES -->`` placeholder; everything
    between ``<!-- RELEASES:START -->`` and ``<!-- RELEASES:END -->`` is
    replaced with the rendered release list on every request. If the DB
    read fails for any reason, the template is returned as-is so the
    landing page never 500s over a changelog.
    """
    with open(os.path.join(WEBSITE_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()

    try:
        releases_html = _render_releases_html(conn)
    except Exception as e:
        logger.warning("release render failed, serving template as-is: %s", e)
        return HTMLResponse(content=html)

    start_tag = "<!-- RELEASES:START -->"
    end_tag = "<!-- RELEASES:END -->"
    si = html.find(start_tag)
    ei = html.find(end_tag)
    if si != -1 and ei != -1 and ei > si:
        html = (
            html[: si + len(start_tag)]
            + "\n"
            + releases_html
            + "\n            "
            + html[ei:]
        )

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
def version_info(
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Public update manifest consumed by the desktop ``UpdateService``.

    Also includes maintenance mode state and any scheduled notification
    so the client can react without needing a separate polling endpoint.
    """
    with conn.cursor() as cur:
        # Scheduled releases whose time has not arrived are hidden from
        # clients — same filter as the website update log so what the user
        # sees on the landing page matches what desktop agents pull.
        cur.execute(
            """
            SELECT version, download_url, sha256, notes, mandatory, published_at
              FROM releases
             WHERE scheduled_at IS NULL OR scheduled_at <= NOW()
             ORDER BY COALESCE(scheduled_at, published_at) DESC
             LIMIT 1
            """,
        )
        row = cur.fetchone()

        cur.execute("SELECT key, value FROM config WHERE key IN "
                    "('maintenance_mode','maintenance_message','notification_message','notification_at')")
        cfg = {r["key"]: r["value"] for r in cur.fetchall()}

    base = {
        "maintenance": cfg.get("maintenance_mode", "false") == "true",
        "maintenance_message": cfg.get("maintenance_message", ""),
        "notification_message": cfg.get("notification_message", ""),
        "notification_at": cfg.get("notification_at", ""),
    }

    if not row:
        return {
            "version": "2.1.2",
            "download_url": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/BlankSetup.exe",
            "sha256": "",
            "notes": "",
            "mandatory": False,
            "published_at": None,
            **base,
        }

    return {
        "version": row["version"],
        "download_url": row["download_url"],
        "sha256": row["sha256"] or "",
        "notes": row["notes"] or "",
        "mandatory": bool(row["mandatory"]),
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        **base,
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

        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        cur.execute("SELECT COUNT(*) AS c FROM downloads WHERE created_at >= %s", (week_ago,))
        week_downloads = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE status = 'active'")
        total_licenses = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE status = 'trial'")
        trial_licenses = cur.fetchone()["c"]

        day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        cur.execute("SELECT COUNT(*) AS c FROM licenses WHERE last_active >= %s", (day_ago,))
        active_users = cur.fetchone()["c"]

        soon = datetime.now(timezone.utc) + timedelta(days=7)
        now = datetime.now(timezone.utc)
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
            date_obj = (datetime.now(timezone.utc) - timedelta(days=i)).date()
            cur.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE created_at::date = %s",
                (date_obj,),
            )
            results.append({"date": date_obj.isoformat(), "count": cur.fetchone()["c"]})
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
    expires = datetime.now(timezone.utc) + timedelta(days=body.days)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO licenses (key, email, name, status, expires_at) VALUES (%s, %s, %s, 'active', %s)",
            (key, body.email, body.name, expires),
        )
    conn.commit()
    return {"key": key, "email": body.email, "expires_at": expires.isoformat()}


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
            expires = datetime.now(timezone.utc) + timedelta(days=body.days)
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


# ── Admin: releases ──────────────────────────────────────────────────────

def _serialise_release(row: dict[str, Any]) -> dict[str, Any]:
    """Stringify TIMESTAMPTZ fields so JSONResponse can serialise.

    Adds a computed ``status`` field the admin UI uses instead of toggling
    ``is_current`` manually — it reflects whether the release is pending
    a scheduled publish, currently visible to clients, or superseded.
    """
    d = dict(row)
    sched = d.get("scheduled_at")
    if d.get("published_at") is not None:
        d["published_at"] = d["published_at"].isoformat()
    if sched is not None:
        now = datetime.now(timezone.utc)
        if sched.tzinfo is None:
            sched = sched.replace(tzinfo=timezone.utc)
        is_future = sched > now
        d["scheduled_at"] = sched.isoformat()
    else:
        is_future = False
    d["mandatory"] = bool(d.get("mandatory", False))
    d["is_current"] = bool(d.get("is_current", False))
    if is_future:
        d["status"] = "scheduled"
    elif d["is_current"]:
        d["status"] = "live"
    else:
        d["status"] = "superseded"
    return d


@app.get("/api/admin/releases")
def admin_list_releases(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> list[dict[str, Any]]:
    """All releases, newest first. Used by the admin Releases tab."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, version, download_url, sha256, notes, mandatory,
                   published_at, is_current, scheduled_at
              FROM releases
             ORDER BY COALESCE(scheduled_at, published_at) DESC
            """,
        )
        rows = cur.fetchall()
    return [_serialise_release(r) for r in rows]


@app.post("/api/admin/releases")
def admin_create_release(
    body: ReleaseCreateRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Publish a new release.

    Immediate publish (``scheduled_at`` is ``None`` or already in the past):
    demote every existing row and insert the new one as ``is_current = TRUE``.
    Re-publishing the same version updates the existing row in place and
    re-promotes it so the operator can fix a typo without retracting.

    Scheduled publish (``scheduled_at`` in the future): insert the release
    with ``is_current = FALSE`` and leave the currently-live release alone.
    The scheduled release becomes visible on its own — both ``/api/version``
    and the landing page query filter on ``scheduled_at <= NOW()``, so the
    changeover happens the moment the first request arrives after that time.
    No cron. No background job. If the operator edits ``scheduled_at`` via a
    re-publish, the ``ON CONFLICT DO UPDATE`` path picks it up.
    """
    if not body.version.strip() or not body.download_url.strip():
        raise HTTPException(status_code=400, detail="version and download_url are required")

    # Parse scheduled_at if given; reject future schedules with bad ISO strings.
    scheduled_dt: Optional[datetime] = None
    raw_sched = (body.scheduled_at or "").strip()
    if raw_sched:
        try:
            parsed = datetime.fromisoformat(raw_sched.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="scheduled_at must be ISO-8601")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        # Treat a schedule that's already passed as "publish now" — avoids
        # leaving a confused scheduled_at on what is effectively a live row.
        if parsed > datetime.now(timezone.utc):
            scheduled_dt = parsed

    is_scheduled = scheduled_dt is not None
    mark_current = not is_scheduled

    with conn.cursor() as cur:
        if mark_current:
            # Only demote existing releases when the new one is going live
            # right now — scheduled publishes must not yank the current
            # release out from under clients before their time.
            cur.execute("UPDATE releases SET is_current = FALSE WHERE is_current = TRUE")
        cur.execute(
            """
            INSERT INTO releases (
                version, download_url, sha256, notes, mandatory,
                is_current, published_at, scheduled_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (version) DO UPDATE SET
                download_url = EXCLUDED.download_url,
                sha256       = EXCLUDED.sha256,
                notes        = EXCLUDED.notes,
                mandatory    = EXCLUDED.mandatory,
                is_current   = EXCLUDED.is_current,
                published_at = NOW(),
                scheduled_at = EXCLUDED.scheduled_at
            RETURNING id, version, download_url, sha256, notes, mandatory,
                      published_at, is_current, scheduled_at
            """,
            (
                body.version,
                body.download_url,
                body.sha256,
                body.notes,
                body.mandatory,
                mark_current,
                scheduled_dt,
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return _serialise_release(row)


@app.delete("/api/admin/releases/{version}")
def admin_retract_release(
    version: str,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Retract a release.

    Hard-deletes the row. If the deleted release was the current one,
    promotes the next-most-recent surviving release so ``/api/version``
    keeps returning a usable manifest. Returns the new current release
    (or ``None`` if the table is now empty).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT is_current FROM releases WHERE version = %s", (version,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="release not found")
        was_current = bool(row["is_current"])

        cur.execute("DELETE FROM releases WHERE version = %s", (version,))

        new_current: Optional[dict[str, Any]] = None
        if was_current:
            cur.execute(
                "SELECT id FROM releases ORDER BY published_at DESC LIMIT 1",
            )
            successor = cur.fetchone()
            if successor:
                cur.execute(
                    "UPDATE releases SET is_current = TRUE WHERE id = %s "
                    "RETURNING id, version, download_url, sha256, notes, mandatory, "
                    "published_at, is_current",
                    (successor["id"],),
                )
                new_current = _serialise_release(cur.fetchone())
    conn.commit()
    return {"retracted": version, "new_current": new_current}


# ── Admin: notifications ─────────────────────────────────────────────────

@app.post("/api/admin/notifications/schedule")
def admin_schedule_notification(
    body: ScheduleNotificationRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    """Schedule a broadcast notification for all connected terminals."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")
    if not body.notify_at.strip():
        raise HTTPException(status_code=400, detail="notify_at is required")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("notification_message", body.message),
        )
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("notification_at", body.notify_at),
        )
    conn.commit()
    return {"status": "scheduled", "notify_at": body.notify_at}


@app.delete("/api/admin/notifications")
def admin_clear_notification(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    """Clear the scheduled notification."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("notification_message", ""),
        )
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("notification_at", ""),
        )
    conn.commit()
    return {"status": "cleared"}


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
