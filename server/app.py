"""blank admin server — FastAPI backend for license validation, telemetry, config, and logs."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Deque, Dict, Generator, Optional

import psycopg2
import psycopg2.extras
import requests
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

# Resend email — used by the public signup flow to email each new user
# their access key. When RESEND_API_KEY is unset (dev), the signup
# endpoint still creates the license row but skips the outbound call and
# logs a warning instead so local testing doesn't need a live key.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "blank <blank@resend.dev>")
DOWNLOAD_URL = os.environ.get(
    "BLANK_DOWNLOAD_URL",
    "https://github.com/Justmilomb/StockMarketAI/releases/latest/download/BlankSetup.exe",
)

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
            # Landing page mode: "coming_soon" serves the pre-launch
            # teaser with the countdown timer, "live" serves the normal
            # landing page with download + update log. Defaults to
            # coming_soon because v1 ships 2026-07-01 and pre-launch
            # visitors must not see a broken download link.
            ("landing_mode", "coming_soon"),
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
                "https://github.com/Justmilomb/StockMarketAI/releases/download/v1.0.0/BlankSetup.exe",
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
    """Public self-serve signup from the live landing page.

    Only an email is collected; we auto-generate the licence key and
    mail it out via Resend. ``name`` is optional but captured if the
    form ever grows a second field.
    """
    email: str
    name: str = ""


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
    """Static privacy policy — linked from the landing page footer."""
    with open(os.path.join(WEBSITE_DIR, "privacy.html"), encoding="utf-8") as f:
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
            <li>run BlankSetup.exe and let it install (no admin rights needed).</li>
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
            cur.execute(
                "INSERT INTO licenses (key, email, name, status, expires_at) "
                "VALUES (%s, %s, %s, 'active', %s)",
                (key, email, (body.name or "").strip(), expires),
            )
        conn.commit()

    expires_iso = expires.strftime("%d %b %Y") if expires else "no expiry"
    sent = _send_signup_email(email, key, expires_iso)

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

    Stores the email in the waitlist table and sends a welcome email
    about monthly updates and who we are. If the email is already on
    the list we just return success without re-sending.
    """
    email = (body.email or "").strip().lower()
    if not _is_valid_email(email):
        raise HTTPException(status_code=400, detail="please enter a valid email address")

    ip = request.client.host if request.client else "unknown"
    if not _signup_rate_ok(ip):
        raise HTTPException(
            status_code=429,
            detail="too many attempts — try again in an hour",
        )

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM waitlist WHERE LOWER(email) = %s", (email,))
        existing = cur.fetchone()

    if existing:
        _send_waitlist_repeat_email(email)
        return {"status": "ok", "sent": True, "already_joined": True}

    with conn.cursor() as cur:
        cur.execute("INSERT INTO waitlist (email) VALUES (%s)", (email,))
    conn.commit()

    sent = _send_waitlist_email(email)
    return {"status": "ok", "sent": sent, "already_joined": False}


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
