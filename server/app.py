"""blank admin server — FastAPI backend for license validation, telemetry, config, and logs."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import re
import secrets
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Deque, Dict, Generator, List, Optional

import psycopg2
import psycopg2.extras
import requests
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger("blank.server")

# ── Config ───────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
ADMIN_KEY = os.environ.get("BLANK_ADMIN_KEY", "admin")
WEBSITE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "website")

# Resend email — used by the public signup flow to email each new user
# their access key. When RESEND_API_KEY is unset (dev), the signup
# endpoint still creates the license row but skips the outbound call and
# logs a warning instead so local testing doesn't need a live key.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "blank <blank@resend.dev>")
DOWNLOAD_URL = os.environ.get(
    "BLANK_DOWNLOAD_URL",
    "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/blank-setup.exe",
)
# Public-facing URL used in outbound emails that ask the user to take
# action (renew, contact, give feedback). No billing page yet — point at
# the marketing site root and let the admin override per-deploy via env.
SITE_URL = os.environ.get("BLANK_SITE_URL", "https://stockmarketai-3qhs.onrender.com/")
SUPPORT_URL = os.environ.get("BLANK_SUPPORT_URL", SITE_URL)
ADMIN_EMAIL = os.environ.get("BLANK_ADMIN_EMAIL", "milomilomilomb@gmail.com")

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
            CREATE TABLE IF NOT EXISTS waitlist (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            -- Idempotency ledger for the auto-email system. Every send
            -- via send_template_once() writes one row. The composite
            -- unique constraint is what makes re-runs of the scheduler
            -- tick (or a double-click in the admin UI) safe.
            CREATE TABLE IF NOT EXISTS email_sent (
                id SERIAL PRIMARY KEY,
                recipient TEXT NOT NULL,
                template_id TEXT NOT NULL,
                reason_key TEXT NOT NULL,
                sent_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (recipient, template_id, reason_key)
            );
            CREATE INDEX IF NOT EXISTS idx_email_sent_template
                ON email_sent(template_id);
            -- Drafts waiting for admin to fill in missing vars before
            -- the actual user-facing email is dispatched.
            CREATE TABLE IF NOT EXISTS email_drafts (
                id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                prefilled_vars TEXT NOT NULL,
                admin_vars TEXT NOT NULL,
                reason_key TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                filled_at TIMESTAMPTZ,
                expires_at TIMESTAMPTZ NOT NULL
            );
            -- Per-key telemetry snapshots pushed by the desktop app.
            -- Pruned to 50 rows per key on each insert.
            CREATE TABLE IF NOT EXISTS telemetry_events (
                id SERIAL PRIMARY KEY,
                license_key TEXT NOT NULL,
                snapshot JSONB NOT NULL,
                uploaded_at TIMESTAMPTZ DEFAULT NOW()
            );
            -- Audit log for training data exports.
            CREATE TABLE IF NOT EXISTS training_exports (
                id SERIAL PRIMARY KEY,
                exported_at TIMESTAMPTZ DEFAULT NOW(),
                event_count INTEGER NOT NULL DEFAULT 0,
                file_size_bytes INTEGER NOT NULL DEFAULT 0,
                date_range_start TIMESTAMPTZ,
                date_range_end TIMESTAMPTZ
            );
        """)
        # Additive migration for databases that pre-date scheduled releases.
        # Must run before creating the scheduled_at index — if the table already
        # exists without this column, the index CREATE above would fail with
        # UndefinedColumn and abort the whole transaction.
        cur.execute(
            "ALTER TABLE releases ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ",
        )
        cur.execute(
            "ALTER TABLE licenses ADD COLUMN IF NOT EXISTS password_hash TEXT",
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_releases_schedule ON releases(scheduled_at)",
        )
        # telemetry_events: uploaded_at may be missing on DBs created before the
        # column was added to the CREATE TABLE block.
        cur.execute(
            "ALTER TABLE telemetry_events ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMPTZ DEFAULT NOW()",
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_key_time "
            "ON telemetry_events(license_key, uploaded_at DESC)",
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
            # Landing page mode: "coming_soon" serves the pre-launch
            # teaser with the countdown timer, "live" serves the normal
            # landing page with download + update log. Defaults to
            # coming_soon because v1 ships 2026-07-01 and pre-launch
            # visitors must not see a broken download link.
            ("landing_mode", "coming_soon"),
            # ISO-8601 UTC timestamp of last training-data export; empty = never exported.
            ("last_export_at", ""),
        ]
        for k, v in defaults:
            cur.execute(
                "INSERT INTO config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
                (k, v),
            )
    conn.commit()
    # v1.0.0 is the *first official release* of blank. The pre-v1 alpha
    # series (0.x through 2.1.x in the old seed list) was internal — it
    # never shipped, it had no paying users, and its changelog confused
    # the landing page. The one-time wipe below removes all of that so
    # the website starts fresh at v1.0.0. The ``config`` marker ensures
    # the wipe runs exactly once per database; after that, admin-added
    # releases are preserved across restarts and only the v1.0.0 seed
    # row is upserted for its notes/date.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM config WHERE key = 'releases_reset_v1'",
        )
        already_reset = cur.fetchone() is not None
        if not already_reset:
            cur.execute("DELETE FROM releases")
            cur.execute(
                "INSERT INTO config (key, value) VALUES ('releases_reset_v1', 'done') "
                "ON CONFLICT (key) DO NOTHING",
            )

        seed_notes = (
            "- first official release of blank — the previous 2.x line was internal alpha, this is v1\n"
            "- autonomous ai trading agent: reads news, social buzz, charts, and places orders on its own\n"
            "- paper mode runs as a £100 gbp sandbox so you can watch the agent trade without risking real money\n"
            "- live mode trades via trading 212 when you hand it a real api key\n"
            "- separate paper and live windows — no more accidental mode flips mid-session\n"
            "- persistent chat agent: ask blank anything and it replies in seconds, not at the end of the next iteration\n"
            "- background scrapers feed the agent news and sentiment from reddit, stocktwits, financial news feeds, marketwatch, and youtube 24/7\n"
            "- supports every major western exchange: nyse/nasdaq, lse, xetra, euronext, six, nordics, tase\n"
            "- bundled ai engine — no extra downloads or api keys needed, it just runs after install"
        )
        cur.execute(
            """
            INSERT INTO releases (version, download_url, sha256, notes, mandatory,
                                  is_current, published_at)
            VALUES (%s, %s, '', %s, FALSE, TRUE, %s::date)
            ON CONFLICT (version) DO UPDATE SET
                notes        = EXCLUDED.notes,
                published_at = EXCLUDED.published_at,
                is_current   = EXCLUDED.is_current
            """,
            (
                "1.0.0",
                "https://github.com/Justmilomb/StockMarketAI/releases/download/v1.0.0/blank-setup.exe",
                seed_notes,
                "2026-04-15",
            ),
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


class HeartbeatRequest(BaseModel):
    """Minute-cadence ping from the desktop app.

    The key is optional so a client that hasn't entered a licence yet
    (wizard is still up) can still poll for maintenance / update
    signals. All fields are plain strings so they survive JSON round-
    trip without schema fuss.
    """
    license_key: str = ""
    version: str = ""
    machine_id: str = ""


class LicenseCreateRequest(BaseModel):
    email: str
    name: str = ""
    days: int = 365


class SignupRequest(BaseModel):
    """Public self-serve signup from the live landing page."""
    email: str
    name: str = ""
    password: str = ""
    agreed_terms: bool = False
    agreed_risk: bool = False


class LicenseUpdateRequest(BaseModel):
    status: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None
    days: Optional[int] = None


class LicenseRevokeRequest(BaseModel):
    """Optional body for DELETE /api/admin/licenses/{key}.

    The admin UI sends ``reason`` so the outbound revocation email can
    explain what happened. Clients that send a bare DELETE still work —
    FastAPI's ``Body(default=...)`` hands this endpoint an empty model.
    """
    reason: str = ""


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str


class LogEntry(BaseModel):
    level: str
    message: str


class LogBatch(BaseModel):
    license_key: str
    entries: list[LogEntry]


class TelemetrySnapshotRequest(BaseModel):
    license_key: str
    snapshot: Dict[str, Any]


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

_ASSETS_DIR = os.path.join(WEBSITE_DIR, "assets")
if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")


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
    """Serve the landing page — either live or coming-soon teaser.

    The ``landing_mode`` config key picks which template to render:

    * ``coming_soon`` — pre-launch teaser with the countdown timer and
      feature preview grid. No download link, no changelog. This is the
      default until v1 ships on 2026-07-01.
    * ``live`` — normal landing page with download button and the
      update log injected between ``<!-- RELEASES:START -->`` and
      ``<!-- RELEASES:END -->``. If the DB read fails the template is
      served as-is so the landing page never 500s over a changelog.

    Any unknown value falls back to ``coming_soon`` so a typo in the
    admin panel fails safe.
    """
    mode = "coming_soon"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM config WHERE key = 'landing_mode'")
            row = cur.fetchone()
            if row and row["value"] == "live":
                mode = "live"
    except Exception as e:
        logger.warning("landing_mode read failed, falling back to coming_soon: %s", e)

    if mode == "coming_soon":
        with open(os.path.join(WEBSITE_DIR, "coming_soon.html"), encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

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


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> HTMLResponse:
    with open(os.path.join(WEBSITE_DIR, "privacy.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(content=html)


@app.get("/terms", response_class=HTMLResponse)
def terms_page() -> HTMLResponse:
    with open(os.path.join(WEBSITE_DIR, "terms.html"), encoding="utf-8") as f:
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
            "version": "1.0.0",
            "download_url": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/blank-setup.exe",
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


@app.post("/api/heartbeat")
def heartbeat(
    body: HeartbeatRequest,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Minute-cadence heartbeat from the desktop app.

    One endpoint, three jobs:

    1. **Update the manifest** — returns the same payload as
       ``/api/version`` so a newly-published release (or a toggled
       maintenance mode) reaches the client inside the next 60 s.
    2. **Record last-seen** — bumps ``licenses.last_active`` for the
       caller's license so the admin "who's online" column is never
       more than a minute stale.
    3. **Machine binding drift detection** — if the caller sends a
       ``machine_id`` that differs from the stored one, we log it but
       don't block (helps spotting licence sharing without a
       false-positive nuke on legit reinstalls).

    Missing/invalid licence keys are tolerated — we still return the
    manifest so the setup wizard can see maintenance banners before
    the user has entered a key.
    """
    key = (body.license_key or "").strip()
    machine_id = (body.machine_id or "").strip()

    with conn.cursor() as cur:
        if key:
            cur.execute(
                "UPDATE licenses SET last_active = NOW() WHERE key = %s",
                (key,),
            )
            if machine_id:
                # Tag the row with the first machine_id we see, and
                # update it if the client is now phoning in from a new
                # one. Two machines sharing a key is a moderation
                # signal, not a kill condition — the admin panel
                # surfaces licences whose machine_id changed recently.
                cur.execute(
                    "UPDATE licenses SET machine_id = %s "
                    "WHERE key = %s AND (machine_id IS NULL OR machine_id = '' OR machine_id <> %s)",
                    (machine_id, key, machine_id),
                )

        # Same query as /api/version — kept inline rather than
        # extracted so the two endpoints don't diverge silently when
        # someone adds a new manifest field.
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

        cur.execute(
            "SELECT key, value FROM config WHERE key IN "
            "('maintenance_mode','maintenance_message','notification_message','notification_at')",
        )
        cfg = {r["key"]: r["value"] for r in cur.fetchall()}

    conn.commit()

    base = {
        "maintenance": cfg.get("maintenance_mode", "false") == "true",
        "maintenance_message": cfg.get("maintenance_message", ""),
        "notification_message": cfg.get("notification_message", ""),
        "notification_at": cfg.get("notification_at", ""),
    }

    if not row:
        return {
            "version": "1.0.0",
            "download_url": "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/blank-setup.exe",
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


# ── Public signup (email → access key via Resend) ───────────────────────

# RFC-5322 is ridiculous; this regex covers the 99% case and we let
# the eventual Resend delivery failure catch anything exotic.
_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

# Per-IP rate limiter: max 3 signups per hour. In-memory because the
# server runs on a single Render instance and the worst-case reset on
# cold-start just gives one extra attempt. A deque of recent timestamps
# per IP is cheap and needs no background sweeper — expired entries are
# dropped the next time that IP hits the endpoint.
_SIGNUP_WINDOW_SECONDS = 3600
_SIGNUP_MAX_PER_WINDOW = 3
_signup_rate: Dict[str, Deque[float]] = {}
_signup_rate_lock = Lock()


def _is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def _signup_rate_ok(ip: str) -> bool:
    """True if this IP is still under the per-hour signup cap."""
    now = time.monotonic()
    cutoff = now - _SIGNUP_WINDOW_SECONDS
    with _signup_rate_lock:
        hits = _signup_rate.setdefault(ip, deque())
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= _SIGNUP_MAX_PER_WINDOW:
            return False
        hits.append(now)
        return True


def _render_signup_email_html(key: str, expires_iso: str) -> str:
    """Build the HTML body for the signup email.

    Kept intentionally small and inline-styled so Resend's downstream
    mail clients don't eat the dark aesthetic — Gmail and Outlook both
    strip <style> blocks, so the look has to live in ``style`` attrs.
    """
    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#000;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#fff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000;">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
        <tr><td style="padding:0 0 32px 0;">
          <h1 style="margin:0;font-size:44px;font-weight:700;letter-spacing:-0.04em;color:#fff;">blank</h1>
          <p style="margin:6px 0 0 0;font-size:13px;color:rgba(255,255,255,0.5);letter-spacing:0.02em;">autonomous ai trading terminal</p>
        </td></tr>
        <tr><td style="padding:24px 20px;border:1px solid rgba(255,255,255,0.12);background:#050505;">
          <p style="margin:0 0 14px 0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:0.32em;text-transform:uppercase;color:#00ff87;">access key</p>
          <p style="margin:0 0 20px 0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:22px;font-weight:500;color:#fff;letter-spacing:0.04em;word-break:break-all;">{key}</p>
          <p style="margin:0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            keep this safe — it unlocks the app on first launch.
            valid until <span style="color:#fff;">{expires_iso}</span>.
          </p>
        </td></tr>
        <tr><td style="padding:28px 0 0 0;" align="center">
          <a href="{DOWNLOAD_URL}" style="display:inline-block;padding:14px 36px;font-size:13px;font-weight:400;letter-spacing:0.08em;color:#00ff87;text-decoration:none;border:1px solid rgba(0,255,135,0.35);background:#000;">download for windows</a>
        </td></tr>
        <tr><td style="padding:28px 0 0 0;">
          <p style="margin:0 0 10px 0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);"><strong style="color:#fff;font-weight:400;">how to activate</strong></p>
          <ol style="margin:0 0 0 18px;padding:0;font-size:12px;line-height:1.65;color:rgba(255,255,255,0.5);">
            <li>run blank-setup.exe and let it install (no admin rights needed).</li>
            <li>launch blank from the start menu.</li>
            <li>paste your access key into the first-run prompt.</li>
            <li>the setup wizard takes it from there.</li>
          </ol>
        </td></tr>
        <tr><td style="padding:40px 0 0 0;border-top:1px solid rgba(255,255,255,0.08);margin-top:40px;">
          <p style="margin:24px 0 0 0;font-size:10px;letter-spacing:0.1em;color:rgba(255,255,255,0.25);">certified random &middot; you're receiving this because you requested access to blank.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _send_signup_email(email: str, key: str, expires_iso: str) -> bool:
    """POST the welcome email to Resend. Returns True on success.

    Non-fatal: a False return is logged but does not abort the signup
    flow, because the licence row has already been written and the
    admin can re-send the key manually from the /admin panel. When
    ``RESEND_API_KEY`` is unset we skip the network call entirely and
    return False so the dev path is loud but not broken.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY unset — skipping signup email to %s", email)
        return False

    payload = {
        "from": RESEND_FROM,
        "to": [email],
        "subject": "your blank access key",
        "html": _render_signup_email_html(key, expires_iso),
    }
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        logger.error("resend transport error for %s: %s", email, e)
        return False

    if r.status_code >= 300:
        logger.error("resend %s for %s: %s", r.status_code, email, r.text[:500])
        return False
    return True


@app.post("/api/signup")
def public_signup(
    body: SignupRequest,
    request: Request,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Public self-serve signup: email -> access key.

    Creates a 365-day licence row and emails the key via Resend. If the
    email has already been used we re-send the existing key instead of
    minting a new one — that way a user who loses the first mail can
    just re-submit on the landing page and get it back. Throttled per
    IP at 3 requests/hour to keep the Resend bill sane.
    """
    email = (body.email or "").strip().lower()
    if not _is_valid_email(email):
        raise HTTPException(status_code=400, detail="please enter a valid email address")

    if not body.agreed_terms:
        raise HTTPException(
            status_code=400,
            detail="you must agree to the terms of service and privacy policy",
        )
    if not body.agreed_risk:
        raise HTTPException(
            status_code=400,
            detail="you must acknowledge the risk disclosure",
        )

    ip = request.client.host if request.client else "unknown"
    if not _signup_rate_ok(ip):
        raise HTTPException(
            status_code=429,
            detail="too many signup attempts — try again in an hour",
        )

    # Look up any existing licence for this email first. Re-sending the
    # same key is much nicer UX than handing out fresh keys each time
    # someone re-submits the form.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, expires_at FROM licenses WHERE LOWER(email) = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (email,),
        )
        existing = cur.fetchone()

    if existing:
        key = existing["key"]
        expires = existing["expires_at"]
    else:
        key = _generate_license_key()
        expires = datetime.now(timezone.utc) + timedelta(days=365)
        with conn.cursor() as cur:
            password_hash: str | None = None
            if body.password:
                salt = secrets.token_hex(16)
                raw = hashlib.pbkdf2_hmac(
                    "sha256", body.password.encode(), salt.encode(), 260_000
                ).hex()
                password_hash = f"{salt}:{raw}"
            cur.execute(
                "INSERT INTO licenses (key, email, name, status, expires_at, password_hash) "
                "VALUES (%s, %s, %s, 'active', %s, %s)",
                (key, email, (body.name or "").strip(), expires, password_hash),
            )
        conn.commit()

    expires_iso = expires.strftime("%d %b %Y") if expires else "no expiry"
    # Route via the idempotent template registry so the mail is logged
    # in email_sent and dedup'd against any future ticks. Reason key is
    # the licence key itself — one welcome mail per licence, ever.
    ok, info = send_template_once(
        conn,
        "welcome_new_license",
        {
            "name": (body.name or "there").strip() or "there",
            "license_key": key,
            "download_url": DOWNLOAD_URL,
        },
        recipient=email,
        reason_key=f"issue:{key}",
    )
    sent = ok
    if not ok:
        logger.info("signup email skipped for %s (%s)", email, info)

    return {
        "status": "ok",
        "sent": sent,
        "email": email,
        # Only echo the key back on the API response when Resend was
        # skipped (dev mode). Production responses never expose the
        # key so a shoulder-surfer on the signup page can't farm it.
        "key": key if not RESEND_API_KEY else None,
    }


# ── Waitlist (coming-soon page — no access key) ─────────────────────────

def _render_waitlist_email_html() -> str:
    """Welcome email for waitlist subscribers. No access key — just hype."""
    return """\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#000;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#fff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000;">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
        <tr><td style="padding:0 0 32px 0;">
          <h1 style="margin:0;font-size:44px;font-weight:700;letter-spacing:-0.04em;color:#fff;">blank</h1>
          <p style="margin:6px 0 0 0;font-size:13px;color:rgba(255,255,255,0.5);letter-spacing:0.02em;">autonomous ai trading terminal</p>
        </td></tr>
        <tr><td style="padding:24px 20px;border:1px solid rgba(255,255,255,0.12);background:#050505;">
          <p style="margin:0 0 14px 0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:0.32em;text-transform:uppercase;color:#00ff87;">welcome to the waitlist</p>
          <p style="margin:0 0 16px 0;font-size:15px;line-height:1.65;color:rgba(255,255,255,0.85);">
            you're in. we're building something exciting &mdash; an ai that trades the stock market for you.
          </p>
          <p style="margin:0 0 16px 0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            blank is an autonomous trading terminal for windows. you download it, open it, and let it run.
            the ai watches prices, reads the news, and makes trades on its own. no experience needed.
          </p>
          <p style="margin:0 0 16px 0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            we're a small team called <strong style="color:#fff;font-weight:400;">certified random</strong>.
            we believe making money from the stock market shouldn't require years of experience or expensive tools.
            blank is our answer to that.
          </p>
          <p style="margin:0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            we'll send you <strong style="color:#fff;font-weight:400;">monthly updates</strong> on how development is going,
            what features we're adding, and when you can get your hands on it.
            launch day is <strong style="color:#00ff87;font-weight:400;">1 july 2026</strong>.
          </p>
        </td></tr>
        <tr><td style="padding:28px 0 0 0;" align="center">
          <p style="margin:0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:0.08em;color:#00ff87;">
            the journey to easy money starts here
          </p>
        </td></tr>
        <tr><td style="padding:40px 0 0 0;border-top:1px solid rgba(255,255,255,0.08);margin-top:40px;">
          <p style="margin:24px 0 0 0;font-size:10px;letter-spacing:0.1em;color:rgba(255,255,255,0.25);">certified random &middot; you joined the blank waitlist.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _send_waitlist_email(email: str) -> bool:
    """Send the waitlist welcome email via Resend."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY unset — skipping waitlist email to %s", email)
        return False

    payload = {
        "from": RESEND_FROM,
        "to": [email],
        "subject": "you're on the blank waitlist",
        "html": _render_waitlist_email_html(),
    }
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        logger.error("resend transport error for waitlist %s: %s", email, e)
        return False

    if r.status_code >= 300:
        logger.error("resend %s for waitlist %s: %s", r.status_code, email, r.text[:500])
        return False
    return True


def _render_waitlist_repeat_html() -> str:
    """Email for someone who's already on the waitlist and signed up again."""
    return """\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#000;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#fff;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000;">
    <tr><td align="center" style="padding:40px 20px;">
      <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
        <tr><td style="padding:0 0 32px 0;">
          <h1 style="margin:0;font-size:44px;font-weight:700;letter-spacing:-0.04em;color:#fff;">blank</h1>
          <p style="margin:6px 0 0 0;font-size:13px;color:rgba(255,255,255,0.5);letter-spacing:0.02em;">autonomous ai trading terminal</p>
        </td></tr>
        <tr><td style="padding:24px 20px;border:1px solid rgba(255,255,255,0.12);background:#050505;">
          <p style="margin:0 0 14px 0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:0.32em;text-transform:uppercase;color:#00ff87;">you're already on the list</p>
          <p style="margin:0 0 16px 0;font-size:15px;line-height:1.65;color:rgba(255,255,255,0.85);">
            we see you signed up again &mdash; love the enthusiasm, keep it up!
          </p>
          <p style="margin:0 0 16px 0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            you're already locked in for launch day. we've got your email and you'll be the first to know when blank is ready.
          </p>
          <p style="margin:0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.55);">
            keep this energy up and you might just get a personal email from our ceo.
          </p>
        </td></tr>
        <tr><td style="padding:28px 0 0 0;" align="center">
          <p style="margin:0;font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:11px;letter-spacing:0.08em;color:#00ff87;">
            1 july 2026 &mdash; it's coming
          </p>
        </td></tr>
        <tr><td style="padding:40px 0 0 0;border-top:1px solid rgba(255,255,255,0.08);margin-top:40px;">
          <p style="margin:24px 0 0 0;font-size:10px;letter-spacing:0.1em;color:rgba(255,255,255,0.25);">certified random &middot; you joined the blank waitlist.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


def _send_waitlist_repeat_email(email: str) -> bool:
    """Send the 'already signed up' email via Resend."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY unset — skipping waitlist repeat email to %s", email)
        return False

    payload = {
        "from": RESEND_FROM,
        "to": [email],
        "subject": "you're already on the blank waitlist!",
        "html": _render_waitlist_repeat_html(),
    }
    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        logger.error("resend transport error for waitlist repeat %s: %s", email, e)
        return False

    if r.status_code >= 300:
        logger.error("resend %s for waitlist repeat %s: %s", r.status_code, email, r.text[:500])
        return False
    return True


@app.post("/api/waitlist")
def public_waitlist(
    body: SignupRequest,
    request: Request,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Pre-launch waitlist: email only, no access key.

    First signup: stores the email and sends a welcome email.
    Repeat signup: sends the enthusiastic "we see you" email on every
    re-submission — no dedup, because the user clearly wants to hear
    from us. Always returns success so the form never shows an error.
    """
    email = (body.email or "").strip().lower()
    if not _is_valid_email(email):
        raise HTTPException(status_code=400, detail="please enter a valid email address")

    if not body.agreed_terms:
        raise HTTPException(
            status_code=400,
            detail="you must agree to the terms of service and privacy policy",
        )

    ip = request.client.host if request.client else "unknown"
    if not _signup_rate_ok(ip):
        raise HTTPException(
            status_code=429,
            detail="too many attempts — try again in an hour",
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM waitlist WHERE LOWER(email) = %s", (email,))
        existing = cur.fetchone()

    launch_date = "01 July 2026"

    if existing:
        # Always send on re-signup — no idempotency, so they get the
        # eager email every time they re-submit the form.
        from server.email_templates import render as render_tpl
        sent = False
        try:
            subject, html, text = render_tpl(
                "waitlist_repeat",
                {"name": "there", "launch_date": launch_date},
                recipient=email,
            )
            _send_email_raw(email, subject, html, text)
            sent = bool(RESEND_API_KEY)
        except Exception:
            logger.error("waitlist_repeat render error for %s", email)
        return {"status": "ok", "sent": sent, "already_joined": True}

    with conn.cursor() as cur:
        cur.execute("INSERT INTO waitlist (email) VALUES (%s)", (email,))
    conn.commit()

    ok, _info = send_template_once(
        conn,
        "waitlist_joined",
        {"name": "there", "launch_date": launch_date},
        recipient=email,
        reason_key="joined",
    )
    return {"status": "ok", "sent": ok, "already_joined": False}


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


@app.post("/api/telemetry/snapshot", status_code=204)
def telemetry_snapshot_push(
    body: TelemetrySnapshotRequest,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> None:
    """Desktop pushes a state snapshot keyed by its license. Admin-only readable."""
    key = (body.license_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="license_key required")
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM licenses WHERE key = %s", (key,))
        if not cur.fetchone():
            raise HTTPException(status_code=403, detail="invalid license key")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO telemetry_events (license_key, snapshot) VALUES (%s, %s)",
            (key, json.dumps(body.snapshot)),
        )
        cur.execute(
            """
            DELETE FROM telemetry_events
            WHERE license_key = %s
              AND id NOT IN (
                SELECT id FROM telemetry_events
                WHERE license_key = %s
                ORDER BY uploaded_at DESC
                LIMIT 50
              )
            """,
            (key, key),
        )
    conn.commit()


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
    # Same welcome mail as the public signup path, same idempotency
    # semantics — reason_key is the licence key.
    if body.email:
        send_template_once(
            conn,
            "welcome_new_license",
            {
                "name": (body.name or "there").strip() or "there",
                "license_key": key,
                "download_url": DOWNLOAD_URL,
            },
            recipient=body.email,
            reason_key=f"issue:{key}",
        )
    return {"key": key, "email": body.email, "expires_at": expires.isoformat()}


@app.put("/api/admin/licenses/{license_key}")
def admin_update_license(
    license_key: str,
    body: LicenseUpdateRequest,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, name FROM licenses WHERE key = %s",
            (license_key,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="license not found")

    new_expires: Optional[datetime] = None
    with conn.cursor() as cur:
        if body.status:
            cur.execute("UPDATE licenses SET status = %s WHERE key = %s", (body.status, license_key))
        if body.email:
            cur.execute("UPDATE licenses SET email = %s WHERE key = %s", (body.email, license_key))
        if body.name:
            cur.execute("UPDATE licenses SET name = %s WHERE key = %s", (body.name, license_key))
        if body.days:
            new_expires = datetime.now(timezone.utc) + timedelta(days=body.days)
            cur.execute(
                "UPDATE licenses SET expires_at = %s WHERE key = %s",
                (new_expires, license_key),
            )
    conn.commit()

    # If the days were extended, treat this as a renewal and mail the
    # licence holder. Uses (recipient, template, f"renew:{date}:{key}")
    # as the idempotency tuple so two admin clicks on the same day don't
    # double-send, but a second extension on a later date does.
    if new_expires is not None:
        recipient = (body.email or row["email"] or "").strip()
        display_name = ((body.name or row["name"] or "there")).strip() or "there"
        if recipient:
            send_template_once(
                conn,
                "license_renewed",
                {
                    "name": display_name,
                    "license_key": license_key,
                    "next_renewal": new_expires.strftime("%d %B %Y"),
                },
                recipient=recipient,
                reason_key=f"renew:{new_expires.date().isoformat()}:{license_key}",
            )
    return {"status": "updated"}


@app.delete("/api/admin/licenses/{license_key}")
def admin_revoke_license(
    license_key: str,
    body: LicenseRevokeRequest = Body(default=LicenseRevokeRequest()),
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email, name FROM licenses WHERE key = %s",
            (license_key,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="license not found")

    with conn.cursor() as cur:
        cur.execute("UPDATE licenses SET status = 'revoked' WHERE key = %s", (license_key,))
    conn.commit()

    recipient = (row["email"] or "").strip()
    if recipient:
        display_name = (row["name"] or "there").strip() or "there"
        prefilled = {"name": display_name, "contact_url": SUPPORT_URL}
        if body.reason.strip():
            prefilled["reason"] = body.reason.strip()
            send_template_once(
                conn,
                "license_revoked",
                prefilled,
                recipient=recipient,
                reason_key=f"revoke:{license_key}",
            )
        else:
            _queue_admin_fill(
                conn,
                "license_revoked",
                prefilled,
                recipient=recipient,
                reason_key=f"revoke:{license_key}",
            )
    return {"status": "revoked"}


@app.get("/api/admin/inspect/{license_key}")
def admin_inspect_license(
    license_key: str,
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> Dict[str, Any]:
    """Return license metadata + latest telemetry snapshot for the admin inspect panel."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE key = %s", (license_key,))
        lic = cur.fetchone()
    if not lic:
        raise HTTPException(status_code=404, detail="license not found")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT snapshot, uploaded_at FROM telemetry_events "
            "WHERE license_key = %s ORDER BY uploaded_at DESC LIMIT 1",
            (license_key,),
        )
        latest = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) AS c, MIN(uploaded_at) AS first_at, MAX(uploaded_at) AS last_at "
            "FROM telemetry_events WHERE license_key = %s",
            (license_key,),
        )
        stats = cur.fetchone()
        cur.execute(
            "SELECT level, message, created_at FROM logs "
            "WHERE license_key = %s ORDER BY created_at DESC LIMIT 20",
            (license_key,),
        )
        logs = cur.fetchall()

    lic_data = dict(lic)
    for k in ("created_at", "expires_at", "last_active"):
        if lic_data.get(k) is not None:
            lic_data[k] = lic_data[k].isoformat()

    snap: Optional[Dict[str, Any]] = None
    snap_at: Optional[str] = None
    if latest:
        raw = latest["snapshot"]
        snap = raw if isinstance(raw, dict) else json.loads(raw)
        snap_at = latest["uploaded_at"].isoformat()

    return {
        "license": lic_data,
        "snapshot": snap,
        "snapshot_at": snap_at,
        "event_count": int(stats["c"]) if stats else 0,
        "first_upload": stats["first_at"].isoformat() if stats and stats["first_at"] else None,
        "last_upload": stats["last_at"].isoformat() if stats and stats["last_at"] else None,
        "recent_logs": [
            {
                "level": r["level"],
                "message": r["message"],
                "at": r["created_at"].isoformat(),
            }
            for r in logs
        ],
    }


# ── Admin: training data export ─────────────────────────────────────────

@app.get("/api/admin/training-data/stats")
def admin_training_stats(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> Dict[str, Any]:
    """Return pending event count and last-export metadata for the admin UI."""
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM config WHERE key = 'last_export_at'")
        row = cur.fetchone()
        last_export_at_str: str = row["value"] if row else ""

        if last_export_at_str:
            cur.execute(
                "SELECT COUNT(*) AS c, MIN(uploaded_at) AS first_at, MAX(uploaded_at) AS last_at "
                "FROM telemetry_events WHERE uploaded_at > %s::timestamptz",
                (last_export_at_str,),
            )
        else:
            cur.execute(
                "SELECT COUNT(*) AS c, MIN(uploaded_at) AS first_at, MAX(uploaded_at) AS last_at "
                "FROM telemetry_events",
            )
        stats = cur.fetchone()

        cur.execute(
            "SELECT id, exported_at, event_count, file_size_bytes, date_range_start, date_range_end "
            "FROM training_exports ORDER BY exported_at DESC LIMIT 20"
        )
        history_rows = cur.fetchall()

    pending = int(stats["c"]) if stats else 0
    # rough estimate: ~2 KB per event after compression
    est_bytes = pending * 2048

    history = []
    for r in history_rows:
        history.append({
            "id": r["id"],
            "exported_at": r["exported_at"].isoformat() if r["exported_at"] else None,
            "event_count": r["event_count"],
            "file_size_bytes": r["file_size_bytes"],
            "date_range_start": r["date_range_start"].isoformat() if r["date_range_start"] else None,
            "date_range_end": r["date_range_end"].isoformat() if r["date_range_end"] else None,
        })

    return {
        "last_export_at": last_export_at_str or None,
        "pending_events": pending,
        "date_range_start": stats["first_at"].isoformat() if stats and stats["first_at"] else None,
        "date_range_end": stats["last_at"].isoformat() if stats and stats["last_at"] else None,
        "estimated_bytes": est_bytes,
        "history": history,
    }


@app.get("/api/admin/export-training-data")
def admin_export_training_data(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> Response:
    """Build and download a .json.gz training-data archive.

    Contains all telemetry snapshots since the last export (or all time on
    first run), grouped by licence key. Updates last_export_at and records
    an entry in training_exports after packaging the file.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM config WHERE key = 'last_export_at'")
        row = cur.fetchone()
        last_export_at_str: str = row["value"] if row else ""

    with conn.cursor() as cur:
        if last_export_at_str:
            cur.execute(
                "SELECT license_key, snapshot, uploaded_at FROM telemetry_events "
                "WHERE uploaded_at > %s::timestamptz ORDER BY uploaded_at ASC",
                (last_export_at_str,),
            )
        else:
            cur.execute(
                "SELECT license_key, snapshot, uploaded_at FROM telemetry_events "
                "ORDER BY uploaded_at ASC",
            )
        rows = cur.fetchall()

    exported_at = datetime.now(timezone.utc)
    total_events = len(rows)

    # Group snapshots by licence key and extract typed fields
    by_licence: Dict[str, Dict[str, List[Any]]] = {}
    date_range_start: Optional[datetime] = None
    date_range_end: Optional[datetime] = None

    for r in rows:
        key = r["license_key"]
        snap_raw = r["snapshot"]
        snap: Dict[str, Any] = snap_raw if isinstance(snap_raw, dict) else json.loads(snap_raw)
        ts: Optional[datetime] = r["uploaded_at"]

        if ts:
            if date_range_start is None or ts < date_range_start:
                date_range_start = ts
            if date_range_end is None or ts > date_range_end:
                date_range_end = ts

        if key not in by_licence:
            by_licence[key] = {
                "trades": [],
                "reasoning": [],
                "chat_transcripts": [],
                "research": [],
                "sentiment": [],
                "forecasts": [],
                "personality_snapshots": [],
                "errors": [],
            }
        bucket = by_licence[key]

        # trades — deduplicate by (side, ticker, ts)
        for t in (snap.get("trades") or []):
            sig = (t.get("side"), t.get("ticker"), t.get("ts"))
            if sig not in {(x.get("side"), x.get("ticker"), x.get("ts")) for x in bucket["trades"]}:
                bucket["trades"].append(t)

        # reasoning — agent journal lines
        for line in (snap.get("log") or []):
            s = str(line).strip()
            if s and s not in bucket["reasoning"]:
                bucket["reasoning"].append(s)

        # sentiment — store per-snapshot entry with timestamp
        sent = snap.get("sentiment")
        if sent:
            bucket["sentiment"].append({
                "ts": snap.get("ts") or (ts.isoformat() if ts else None),
                "scores": sent,
            })

        # personality — one snapshot per unique seed/state
        pers = snap.get("personality")
        if pers:
            bucket["personality_snapshots"].append({
                "ts": snap.get("ts") or (ts.isoformat() if ts else None),
                "data": pers,
            })

    # Fetch server-side error logs for each licence key in this range
    if rows and date_range_start:
        with conn.cursor() as cur:
            keys = list(by_licence.keys())
            placeholders = ",".join(["%s"] * len(keys))
            cur.execute(
                f"SELECT license_key, level, message, created_at FROM logs "
                f"WHERE license_key IN ({placeholders}) "
                f"AND created_at >= %s "
                f"ORDER BY created_at ASC",
                (*keys, date_range_start),
            )
            for lr in cur.fetchall():
                k = lr["license_key"]
                if k in by_licence and lr["level"] in ("error", "warning"):
                    by_licence[k]["errors"].append({
                        "level": lr["level"],
                        "message": lr["message"],
                        "at": lr["created_at"].isoformat() if lr["created_at"] else None,
                    })

    payload = {
        "export_meta": {
            "exported_at": exported_at.isoformat(),
            "date_range": [
                date_range_start.isoformat() if date_range_start else None,
                date_range_end.isoformat() if date_range_end else None,
            ],
            "total_events": total_events,
            "unique_keys": len(by_licence),
        },
        "by_licence": by_licence,
    }

    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
    gz_bytes = gzip.compress(json_bytes, compresslevel=6)
    file_size = len(gz_bytes)

    # Record the export before returning so a network failure during
    # download doesn't permanently lose the timestamp advance.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO training_exports "
            "(exported_at, event_count, file_size_bytes, date_range_start, date_range_end) "
            "VALUES (%s, %s, %s, %s, %s)",
            (exported_at, total_events, file_size, date_range_start, date_range_end),
        )
        cur.execute(
            "INSERT INTO config (key, value, updated_at) VALUES ('last_export_at', %s, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            (exported_at.isoformat(),),
        )
    conn.commit()

    filename = f"blank_training_{exported_at.strftime('%Y%m%d_%H%M%S')}.json.gz"
    return Response(
        content=gz_bytes,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


# ── Email auto-send: idempotent helper + scheduler ─────────────────────

def _reserve_email_slot(
    conn: psycopg2.extensions.connection,
    recipient: str,
    template_id: str,
    reason_key: str,
) -> bool:
    """Claim the (recipient, template_id, reason_key) slot in email_sent.

    Returns True if we got the slot (caller should send), False if the
    slot was already taken (already sent — skip). Claiming happens
    BEFORE the Resend call so two concurrent ticks can't both try to
    send. On Resend failure the caller deletes the row to re-arm the
    slot for the next tick.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO email_sent (recipient, template_id, reason_key) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
            (recipient.strip().lower(), template_id, reason_key),
        )
        got = cur.fetchone() is not None
    conn.commit()
    return got


def _release_email_slot(
    conn: psycopg2.extensions.connection,
    recipient: str,
    template_id: str,
    reason_key: str,
) -> None:
    """Undo a :func:`_reserve_email_slot` so the next tick can retry."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM email_sent WHERE recipient = %s AND template_id = %s "
            "AND reason_key = %s",
            (recipient.strip().lower(), template_id, reason_key),
        )
    conn.commit()


def send_template_once(
    conn: psycopg2.extensions.connection,
    template_id: str,
    ctx: Dict[str, Any],
    *,
    recipient: str,
    reason_key: str,
    unsubscribe_url: str = "",
) -> tuple[bool, str]:
    """Render + send one template idempotently.

    Returns ``(sent, info)`` — ``sent`` is True only if this call
    actually delivered the mail. ``info`` is a short reason ("ok",
    "already_sent", "render:…", "resend:…", "no_api_key") for logging
    and the admin status line.
    """
    from server.email_templates import render

    addr = recipient.strip()
    if not addr:
        return False, "empty_recipient"

    if not _reserve_email_slot(conn, addr, template_id, reason_key):
        return False, "already_sent"

    try:
        subject, html, text = render(
            template_id, dict(ctx),
            recipient=addr,
            unsubscribe_url=unsubscribe_url,
        )
    except Exception as e:
        _release_email_slot(conn, addr, template_id, reason_key)
        return False, f"render: {e}"

    if not RESEND_API_KEY:
        # Release the slot so the mail is retried the first time a
        # real API key is present — claiming and abandoning it would
        # permanently suppress delivery.
        _release_email_slot(conn, addr, template_id, reason_key)
        logger.warning(
            "RESEND_API_KEY unset — skipping %s to %s (%s)",
            template_id, addr, reason_key,
        )
        return False, "no_api_key"

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json={
                "from": RESEND_FROM,
                "to": [addr],
                "subject": subject,
                "html": html,
                "text": text,
            },
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
    except requests.RequestException as e:
        _release_email_slot(conn, addr, template_id, reason_key)
        return False, f"resend: {e}"

    if r.status_code >= 300:
        _release_email_slot(conn, addr, template_id, reason_key)
        return False, f"resend_{r.status_code}: {r.text[:200]}"

    return True, "ok"


def _send_email_raw(to: str, subject: str, html: str, text: str) -> None:
    """Fire-and-forget Resend call with no idempotency ledger."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY unset — would have sent to %s: %s", to, subject)
        return
    try:
        requests.post(
            "https://api.resend.com/emails",
            json={"from": RESEND_FROM, "to": [to], "subject": subject, "html": html, "text": text},
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send admin notification to %s", to)


def _queue_admin_fill(
    conn: "psycopg2.extensions.connection",
    template_id: str,
    prefilled_vars: Dict[str, Any],
    recipient: str,
    reason_key: str,
) -> None:
    """Store an email draft and notify the admin to fill in missing vars.

    If the template has no admin_vars the call falls through to a normal
    send_template_once so callers don't need to branch.
    """
    from server.email_templates import _spec as get_spec, render as render_tpl

    spec = get_spec(template_id)
    if not spec.admin_vars:
        send_template_once(conn, template_id, prefilled_vars, recipient=recipient, reason_key=reason_key)
        return

    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO email_drafts "
            "(id, template_id, recipient, prefilled_vars, admin_vars, reason_key, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                token, template_id, recipient,
                json.dumps(prefilled_vars),
                json.dumps(spec.admin_vars),
                reason_key,
                expires,
            ),
        )
    conn.commit()

    fill_url = f"{SITE_URL.rstrip('/')}/fill/{token}"
    try:
        subj, html, text = render_tpl(
            "admin_fill_request",
            {
                "template_label": spec.label,
                "draft_recipient": recipient,
                "admin_fields": spec.admin_vars,
                "fill_url": fill_url,
            },
            recipient=ADMIN_EMAIL,
        )
        _send_email_raw(ADMIN_EMAIL, subj, html, text)
    except Exception:
        logger.exception("Failed to send fill-request notification for draft %s", token)


# ── Fill-form page (public, token-gated) ─────────────────────────────────

_FILL_CSS = """
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #000;
    color: #fff;
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
}
.card {
    width: 100%;
    max-width: 520px;
    border: 1px solid rgba(255,255,255,0.1);
    background: #050505;
    padding: 2rem 2rem 2.25rem;
}
.brand {
    font-family: 'Outfit', monospace;
    font-size: 10px;
    letter-spacing: 0.28em;
    text-transform: uppercase;
    color: #00ff87;
    margin-bottom: 1.5rem;
}
h1 { font-size: 1.25rem; font-weight: 300; color: #fff; margin-bottom: 0.5rem; }
.meta {
    font-size: 0.8125rem;
    color: rgba(255,255,255,0.4);
    margin-bottom: 2rem;
    line-height: 1.6;
}
.field { margin-bottom: 1.375rem; }
label {
    display: block;
    font-size: 0.6875rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.4);
    margin-bottom: 0.5rem;
}
textarea {
    width: 100%;
    background: #000;
    border: 1px solid rgba(255,255,255,0.15);
    color: #fff;
    font-family: inherit;
    font-size: 0.9375rem;
    line-height: 1.6;
    padding: 0.75rem 1rem;
    resize: vertical;
    outline: none;
    min-height: 4rem;
    transition: border-color 0.2s;
}
textarea:focus { border-color: #00ff87; }
.error {
    background: rgba(255,60,60,0.07);
    border: 1px solid rgba(255,60,60,0.25);
    color: #ff7070;
    font-size: 0.8125rem;
    padding: 0.75rem 1rem;
    margin-bottom: 1.375rem;
}
button {
    width: 100%;
    background: #00ff87;
    color: #000;
    border: none;
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    padding: 1rem;
    cursor: pointer;
    margin-top: 0.25rem;
    transition: opacity 0.2s;
}
button:hover { opacity: 0.85; }
.icon { font-size: 2rem; margin-bottom: 1rem; color: #00ff87; }
"""


def _fill_page_form(
    token: str,
    template_id: str,
    recipient: str,
    admin_vars: List[str],
    error: str = "",
) -> str:
    from server.email_templates import _spec
    try:
        label = _spec(template_id).label
    except KeyError:
        label = template_id

    error_html = f'<div class="error">{error}</div>' if error else ""
    fields_html = "".join(
        f'<div class="field"><label for="f_{v}">{v.replace("_", " ")}</label>'
        f'<textarea id="f_{v}" name="{v}" rows="3" placeholder="enter {v.replace("_", " ")}..." required></textarea></div>'
        for v in admin_vars
    )
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>fill in — blank</title><style>{_FILL_CSS}</style></head>'
        f'<body><div class="card"><div class="brand">blank</div>'
        f'<h1>fill in before sending</h1>'
        f'<p class="meta">template: {label}<br>to: {recipient}</p>'
        f'{error_html}'
        f'<form method="POST" action="/fill/{token}">{fields_html}'
        f'<button type="submit">send email &rarr;</button></form>'
        f'</div></body></html>'
    )


def _fill_page_done(template_id: str, recipient: str, sent: bool) -> str:
    from server.email_templates import _spec
    try:
        label = _spec(template_id).label
    except KeyError:
        label = template_id
    if sent:
        body = f'<div class="icon">✓</div><h1>email sent</h1><p class="meta">{label}<br>{recipient}</p>'
    else:
        body = '<h1>already sent</h1><p class="meta">this draft was already submitted.</p>'
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>done — blank</title><style>{_FILL_CSS}</style></head>'
        f'<body><div class="card"><div class="brand">blank</div>{body}</div></body></html>'
    )


def _fill_page_error(msg: str) -> str:
    return (
        f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>error — blank</title><style>{_FILL_CSS}</style></head>'
        f'<body><div class="card"><div class="brand">blank</div>'
        f'<h1>something went wrong</h1><p class="meta">{msg}</p>'
        f'</div></body></html>'
    )


@app.get("/fill/{token}", response_class=HTMLResponse)
def fill_form_get(
    token: str,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> HTMLResponse:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT template_id, recipient, admin_vars, filled_at, expires_at "
            "FROM email_drafts WHERE id = %s",
            (token,),
        )
        draft = cur.fetchone()
    if not draft:
        return HTMLResponse(_fill_page_error("link not found or already expired"), status_code=404)
    if draft["filled_at"]:
        return HTMLResponse(_fill_page_done(draft["template_id"], draft["recipient"], sent=False))
    if draft["expires_at"] < datetime.now(timezone.utc):
        return HTMLResponse(_fill_page_error("this link has expired"), status_code=410)
    admin_vars: List[str] = json.loads(draft["admin_vars"])
    return HTMLResponse(_fill_page_form(token, draft["template_id"], draft["recipient"], admin_vars))


@app.post("/fill/{token}", response_class=HTMLResponse)
async def fill_form_post(
    token: str,
    request: Request,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> HTMLResponse:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT template_id, recipient, prefilled_vars, admin_vars, reason_key, "
            "filled_at, expires_at FROM email_drafts WHERE id = %s",
            (token,),
        )
        draft = cur.fetchone()
    if not draft:
        return HTMLResponse(_fill_page_error("link not found or already expired"), status_code=404)
    if draft["filled_at"]:
        return HTMLResponse(_fill_page_done(draft["template_id"], draft["recipient"], sent=False))
    if draft["expires_at"] < datetime.now(timezone.utc):
        return HTMLResponse(_fill_page_error("this link has expired"), status_code=410)

    form_data = await request.form()
    admin_vars: List[str] = json.loads(draft["admin_vars"])

    filled: Dict[str, str] = {}
    missing: List[str] = []
    for v in admin_vars:
        val = str(form_data.get(v, "")).strip()
        if val:
            filled[v] = val
        else:
            missing.append(v)

    if missing:
        return HTMLResponse(
            _fill_page_form(
                token, draft["template_id"], draft["recipient"], admin_vars,
                error=f"please fill in: {', '.join(missing)}",
            )
        )

    full_ctx = {**json.loads(draft["prefilled_vars"]), **filled}
    ok, info = send_template_once(
        conn, draft["template_id"], full_ctx,
        recipient=draft["recipient"],
        reason_key=draft["reason_key"],
    )

    with conn.cursor() as cur:
        cur.execute("UPDATE email_drafts SET filled_at = NOW() WHERE id = %s", (token,))
    conn.commit()

    if ok or info == "already_sent":
        return HTMLResponse(_fill_page_done(draft["template_id"], draft["recipient"], sent=ok))
    return HTMLResponse(_fill_page_error(f"send failed: {info}"), status_code=500)


# ── Admin: email template library ────────────────────────────────────────

class _EmailPreviewBody(BaseModel):
    template_id: str
    vars: Dict[str, Any] = {}
    recipient: str = "preview@example.com"


class _EmailSendBody(BaseModel):
    template_id: str
    vars: Dict[str, Any] = {}
    recipients: List[str]


@app.get("/api/admin/email-templates")
def admin_email_templates_list(_: str = Depends(require_admin)) -> Dict[str, Any]:
    from server.email_rules import trigger_for
    from server.email_templates import list_templates
    templates = list_templates()
    for t in templates:
        spec = trigger_for(t["id"])
        t["trigger"] = {"kind": spec.kind, "rule": spec.rule}
    return {"templates": templates}


@app.post("/api/admin/email-templates/preview")
def admin_email_templates_preview(
    body: _EmailPreviewBody,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    from server.email_templates import render
    try:
        subject, html, text = render(
            body.template_id, dict(body.vars), recipient=body.recipient,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"render error: {e}")
    return {"subject": subject, "html": html, "text": text}


@app.post("/api/admin/email-templates/send")
def admin_email_templates_send(
    body: _EmailSendBody,
    _: str = Depends(require_admin),
) -> Dict[str, Any]:
    from server.email_templates import render

    if not body.recipients:
        raise HTTPException(status_code=400, detail="no recipients")

    # Expand audience sentinels ("all_licensed" / "all_waitlist") into
    # real email addresses by querying the DB. Anything else is taken
    # verbatim, so individual emails still work.
    addresses: list[str] = []
    for entry in body.recipients:
        if entry == "all_licensed":
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT email FROM licenses WHERE status = 'active' AND email IS NOT NULL"
                )
                addresses.extend(row["email"] for row in cur.fetchall() if row.get("email"))
        elif entry == "all_waitlist":
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("SELECT email FROM waitlist WHERE email IS NOT NULL")
                addresses.extend(row["email"] for row in cur.fetchall() if row.get("email"))
        else:
            addresses.append(entry)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    recipients: list[str] = []
    for addr in addresses:
        key = addr.strip().lower()
        if key and key not in seen:
            seen.add(key)
            recipients.append(addr.strip())

    if not recipients:
        return {"sent": [], "errors": [{"recipient": "-", "error": "no recipients resolved"}]}

    sent: list[str] = []
    errors: list[Dict[str, str]] = []
    for addr in recipients:
        try:
            subject, html, text = render(
                body.template_id, dict(body.vars), recipient=addr,
            )
        except Exception as e:
            errors.append({"recipient": addr, "error": f"render: {e}"})
            continue
        if not RESEND_API_KEY:
            errors.append({"recipient": addr, "error": "RESEND_API_KEY unset"})
            continue
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                json={
                    "from": RESEND_FROM,
                    "to": [addr],
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if r.status_code >= 300:
                errors.append({"recipient": addr, "error": f"resend {r.status_code}"})
                continue
        except requests.RequestException as e:
            errors.append({"recipient": addr, "error": str(e)})
            continue
        sent.append(addr)
    return {"sent": sent, "errors": errors}


# ── Scheduled email sweeps ───────────────────────────────────────────────

_ONBOARDING_TIPS: list[str] = [
    "Start in paper mode. £100 GBP sandbox, no real money at risk.",
    "Let a few 45-second cycles run before you touch anything — early "
    "decisions read calmer in context.",
    "The information panel is where the agent explains itself. Open it "
    "whenever a trade surprises you.",
    "The agent journal logs every iteration, so you can always scroll "
    "back and see what the brain was thinking.",
]

_WEEKLY_HIGHLIGHTS: list[str] = [
    "Markets closed — the agent paused automation over the weekend.",
    "Catch up on the week's changelog inside the desktop app's "
    "releases panel.",
]


def _run_sweep(
    conn: psycopg2.extensions.connection,
    template_id: str,
    rows: list[dict[str, Any]],
    build_ctx,
    build_reason_key,
) -> dict[str, int]:
    """Iterate candidate rows through ``send_template_once``.

    ``build_ctx`` and ``build_reason_key`` are callables taking the row
    and returning the template context / ledger key. Each sweep owns its
    own shape so we don't try to push a one-size-fits-all contract on
    four different templates.
    """
    counts = {"candidates": len(rows), "sent": 0, "skipped": 0, "errors": 0}
    for row in rows:
        recipient = (row.get("email") or "").strip()
        if not recipient:
            counts["errors"] += 1
            continue
        try:
            ctx = build_ctx(row)
            reason_key = build_reason_key(row)
        except Exception as e:
            logger.error("_run_sweep build error for %s/%s: %s", template_id, recipient, e)
            counts["errors"] += 1
            continue
        ok, info = send_template_once(
            conn, template_id, ctx,
            recipient=recipient,
            reason_key=reason_key,
        )
        if ok:
            counts["sent"] += 1
        elif info in ("already_sent", "no_api_key"):
            counts["skipped"] += 1
        else:
            logger.warning("_run_sweep send error for %s/%s: %s", template_id, recipient, info)
            counts["errors"] += 1
    return counts


@app.post("/api/admin/emails/tick")
def admin_emails_tick(
    _: str = Depends(require_admin),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> Dict[str, Any]:
    """Run all four scheduled email sweeps in one call.

    Idempotent via the ``email_sent`` ledger — safe to call hourly from
    an external cron (Render cron job, systemd timer, curl from a
    watcher). The endpoint does not schedule itself; it just runs when
    asked. Duplicate reason keys return ``skipped``, not ``sent``.
    """
    ran_at = datetime.now(timezone.utc)
    out: Dict[str, Dict[str, int]] = {}

    # license_expiring — 7-day window, ±1 day wiggle so a late cron run
    # still catches yesterday's candidates.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, email, name, expires_at FROM licenses "
            "WHERE status = 'active' AND email IS NOT NULL "
            "AND expires_at BETWEEN NOW() + INTERVAL '6 days' "
            "                   AND NOW() + INTERVAL '8 days'"
        )
        rows = [dict(r) for r in cur.fetchall()]
    out["license_expiring"] = _run_sweep(
        conn, "license_expiring", rows,
        build_ctx=lambda r: {
            "name": (r.get("name") or "there").strip() or "there",
            "license_key": r["key"],
            "expires_at": r["expires_at"].strftime("%d %B %Y"),
            "renew_url": SUPPORT_URL,
        },
        build_reason_key=lambda r: f"expire:{r['key']}:{r['expires_at'].date().isoformat()}",
    )

    # first_time_tips — roughly 24 hours after the first heartbeat.
    # The ~20–30 hour window lets hourly ticks catch everyone without
    # depending on exact clock alignment.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, email, name, last_active FROM licenses "
            "WHERE status = 'active' AND email IS NOT NULL "
            "AND last_active BETWEEN NOW() - INTERVAL '30 hours' "
            "                    AND NOW() - INTERVAL '20 hours'"
        )
        rows = [dict(r) for r in cur.fetchall()]
    out["first_time_tips"] = _run_sweep(
        conn, "first_time_tips", rows,
        build_ctx=lambda r: {
            "name": (r.get("name") or "there").strip() or "there",
            "tips": list(_ONBOARDING_TIPS),
        },
        build_reason_key=lambda r: f"tips:{r['key']}",
    )

    # feedback_request — 14 days after issue.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT key, email, name, created_at FROM licenses "
            "WHERE status = 'active' AND email IS NOT NULL "
            "AND created_at BETWEEN NOW() - INTERVAL '15 days' "
            "                   AND NOW() - INTERVAL '13 days'"
        )
        rows = [dict(r) for r in cur.fetchall()]
    out["feedback_request"] = _run_sweep(
        conn, "feedback_request", rows,
        build_ctx=lambda r: {
            "name": (r.get("name") or "there").strip() or "there",
            "form_url": SUPPORT_URL,
        },
        build_reason_key=lambda r: f"feedback:{r['key']}",
    )

    # holiday_check_in — weekly digest, Sunday only. ISO week in the
    # reason key means one send per licence per ISO week even if the
    # tick fires multiple times on Sunday.
    if ran_at.weekday() == 6:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, email, name FROM licenses "
                "WHERE status = 'active' AND email IS NOT NULL"
            )
            rows = [dict(r) for r in cur.fetchall()]
        iso_year, iso_week, _ = ran_at.isocalendar()
        period_end = ran_at
        period_start = period_end - timedelta(days=6)
        out["holiday_check_in"] = _run_sweep(
            conn, "holiday_check_in", rows,
            build_ctx=lambda r: {
                "name": (r.get("name") or "there").strip() or "there",
                "period_start": period_start.strftime("%d %B %Y"),
                "period_end": period_end.strftime("%d %B %Y"),
                "highlights": list(_WEEKLY_HIGHLIGHTS),
            },
            build_reason_key=lambda r: f"weekly:{iso_year}-W{iso_week:02d}:{r['key']}",
        )
    else:
        out["holiday_check_in"] = {
            "candidates": 0, "sent": 0, "skipped": 0, "errors": 0,
        }

    return {"ran_at": ran_at.isoformat(), "counts": out}


# ── Dev monitor (dev-only, in-memory snapshot store) ─────────────────────
# Auth is password-only: the desktop POSTs with "Bearer <password>" and the
# server stores the password alongside the snapshot. The browser GET must
# supply the same password. No server-side env var is required — the password
# lives entirely in the desktop's config.json under dev_monitor.password.

_monitor_snapshot: Dict[str, Any] = {}
_monitor_password: str = ""
_monitor_lock = Lock()


@app.post("/api/dev/agent-status", status_code=204)
async def dev_agent_status_push(
    request: Request,
    authorization: str = Header(default=""),
) -> None:
    """Desktop pushes its current agent state snapshot here."""
    pw = authorization[7:] if authorization.startswith("Bearer ") else ""
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    global _monitor_password
    with _monitor_lock:
        _monitor_password = pw
        _monitor_snapshot.clear()
        _monitor_snapshot.update(body)


@app.get("/api/dev/agent-status")
def dev_agent_status_get(
    authorization: str = Header(default=""),
) -> Dict[str, Any]:
    """Browser dashboard polls this to get the latest snapshot."""
    with _monitor_lock:
        if not _monitor_snapshot:
            raise HTTPException(status_code=503, detail="no snapshot yet")
        stored = _monitor_password
        if stored:
            pw = authorization[7:] if authorization.startswith("Bearer ") else ""
            if not secrets.compare_digest(pw, stored):
                raise HTTPException(status_code=403, detail="forbidden")
        return dict(_monitor_snapshot)


@app.get("/monitor", response_class=HTMLResponse)
def monitor_page() -> HTMLResponse:
    path = os.path.join(WEBSITE_DIR, "monitor.html")
    try:
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="monitor page not found")


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)
