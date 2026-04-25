# Account Auth — Replace Licence Keys with OAuth-Style Sign-In

**Goal:** Replace the licence-key gate with browser-based account auth. Download/install is free; the app opens without sign-in (UI visible, interactive features disabled) and users sign in through the website via a localhost callback.

**Architecture:**
- Server exposes JWT-based `/api/auth/login` and `/api/auth/me`. Internally each user row is still the existing `licenses` record (key becomes an internal ID, users never see it).
- Website gains a `/auth/login` page that accepts a `callback_port` query param; on successful login the browser redirects to `http://127.0.0.1:<port>/auth/callback?token=<jwt>`.
- Desktop spins up a one-shot `http.server` on a random loopback port, opens the browser to `/auth/login?callback_port=<port>`, receives the token, stores it at `~/.blank/session.token`, and keeps a global `AuthState` that widgets consult.
- Every interactive action funnels through `auth_gate.require_auth(...)`; when not signed in a subtle toast replaces the action and a persistent "sign in to start trading" banner is visible. No payment logic.

**Tech Stack:** FastAPI · PyJWT · PySide6 · stdlib `http.server`, `secrets`, `webbrowser`.

---

## File Structure

**New files:**
- `desktop/auth.py` — token storage, HTTP client for `/api/auth/*`
- `desktop/auth_callback_server.py` — loopback HTTP listener for the token handoff
- `desktop/auth_state.py` — `AuthState` dataclass + process-wide singleton with Qt signal
- `desktop/dialogs/signin.py` — startup sign-in prompt (with Skip button)
- `desktop/widgets/profile_button.py` — top-right profile corner widget
- `desktop/widgets/signin_banner.py` — persistent "sign in to start trading" banner
- `desktop/auth_gate.py` — `require_auth()` helper + "sign in to use blank" inline toast

**Modified files:**
- `server/app.py` — add auth endpoints, switch signup to require password, issue JWT on signup, stop emailing the key to users
- `server/requirements.txt` — add `PyJWT`
- `server/email_templates.py` — drop the key from user-facing welcome template body (key stays in admin-facing templates)
- `server/templates/emails/welcome_new_license.html.j2` / `.txt.j2` — rewrite without key
- `website/index.html` — remove public key display, change signup success copy, add "sign in" link
- `website/auth_login.html` *(new)* — login form served at `/auth/login`
- `desktop/main.py` — drop licence gate, add auth bootstrap
- `desktop/app.py` — wire profile button into menu bar corner + banner into central layout + pass auth state into panels
- `desktop/license.py` — reduce to a thin shim that `heartbeat`/`send_logs` still import; keep `_machine_id`; stop being the source of truth
- `desktop/panels/agent_log.py` — gate start button
- `desktop/panels/chat.py` — gate the input field
- `desktop/dialogs/trade.py` — block submission when signed-out
- `desktop/dialogs/license.py` — deleted

**Deleted files:**
- `desktop/dialogs/license.py`

---

## Task 1: Server — JWT dependency + helpers

**Files:**
- Modify: `server/requirements.txt`
- Modify: `server/app.py` (top, `# ── Config ──` and `# ── Auth ──` blocks)

- [ ] **Step 1:** add `PyJWT` to `server/requirements.txt`.

Append exactly:

```
PyJWT
```

- [ ] **Step 2:** in `server/app.py`, add after the existing `ADMIN_KEY = ...` line:

```python
# JWT secret used to sign user auth tokens. When unset (dev), we fall
# back to a deterministic-but-obviously-fake value so local testing
# works; production MUST set this or tokens become trivially forgeable
# once an attacker reads the source.
JWT_SECRET = os.environ.get("BLANK_JWT_SECRET", "dev-jwt-secret-do-not-ship")
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30
```

- [ ] **Step 3:** add `import jwt` alongside the other imports at the top of `server/app.py` (after `import requests`).

- [ ] **Step 4:** below the existing `require_admin` helper in the `# ── Auth ──` block, add:

```python
def _issue_jwt(license_row: dict[str, Any]) -> str:
    """Mint a 30-day JWT for a licence row. ``sub`` is the licence key
    (our internal user id — never shown to the user)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": license_row["key"],
        "email": license_row["email"],
        "name": license_row.get("name") or "",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict[str, Any]:
    """Raise HTTPException(401) on any failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="session expired — please sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid session token")


def require_auth(
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """FastAPI dependency: accept ``Authorization: Bearer <jwt>`` and
    return the decoded payload, or 401."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    return _decode_jwt(token)
```

- [ ] **Step 5:** commit.

---

## Task 2: Server — password hashing helper

**Files:**
- Modify: `server/app.py` (after the JWT helpers)

- [ ] **Step 1:** add these helpers to `server/app.py`:

```python
def _hash_password(raw: str) -> str:
    """Return ``salt:hex`` with 260k PBKDF2-SHA256 iterations. Matches
    the format already produced by the signup endpoint, so existing
    hashes keep working."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", raw.encode(), salt.encode(), 260_000,
    ).hex()
    return f"{salt}:{digest}"


def _verify_password(raw: str, stored: str) -> bool:
    if not stored or ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    candidate = hashlib.pbkdf2_hmac(
        "sha256", raw.encode(), salt.encode(), 260_000,
    ).hex()
    return secrets.compare_digest(candidate, expected)
```

- [ ] **Step 2:** replace the inline hashing block in the existing signup endpoint so both code paths go through `_hash_password`. In `public_signup`, find:

```python
            password_hash: str | None = None
            if body.password:
                salt = secrets.token_hex(16)
                raw = hashlib.pbkdf2_hmac(
                    "sha256", body.password.encode(), salt.encode(), 260_000
                ).hex()
                password_hash = f"{salt}:{raw}"
```

replace with:

```python
            password_hash: str | None = (
                _hash_password(body.password) if body.password else None
            )
```

- [ ] **Step 3:** commit.

---

## Task 3: Server — `/api/auth/login` and `/api/auth/me`

**Files:**
- Modify: `server/app.py` (new endpoints after the existing `validate_license` block)

- [ ] **Step 1:** add a new request model near the other Pydantic models:

```python
class LoginRequest(BaseModel):
    email: str
    password: str
```

- [ ] **Step 2:** add these endpoints in `server/app.py` after `validate_license` (around the existing `# ── Public signup` section — place them immediately before that comment):

```python
# ── Account auth (users never see the underlying licence key) ───────────

@app.post("/api/auth/login")
def auth_login(
    body: LoginRequest,
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Email + password → JWT. Returns 401 on any failure so the UI
    doesn't leak whether the email exists."""
    email = (body.email or "").strip().lower()
    password = body.password or ""
    if not email or not password:
        raise HTTPException(status_code=401, detail="invalid email or password")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM licenses WHERE LOWER(email) = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (email,),
        )
        row = cur.fetchone()

    if not row or not _verify_password(password, row.get("password_hash") or ""):
        raise HTTPException(status_code=401, detail="invalid email or password")

    if row["status"] in ("revoked", "expired"):
        raise HTTPException(status_code=403, detail=f"account {row['status']}")

    if row.get("expires_at"):
        expires = row["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            raise HTTPException(status_code=403, detail="account expired")

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE licenses SET last_active = NOW() WHERE key = %s",
            (row["key"],),
        )
    conn.commit()

    token = _issue_jwt(dict(row))
    return {
        "token": token,
        "email": row["email"],
        "name": row.get("name") or "",
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
    }


@app.get("/api/auth/me")
def auth_me(
    claims: dict[str, Any] = Depends(require_auth),
    conn: psycopg2.extensions.connection = Depends(db_dependency),
) -> dict[str, Any]:
    """Return the current user and the same remote-config blob the old
    ``/api/license/validate`` handed back, so the desktop app can keep
    honouring kill-switch / maintenance / force-update flags."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE key = %s", (claims["sub"],))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="account no longer exists")
    if row["status"] in ("revoked", "expired"):
        raise HTTPException(status_code=403, detail=f"account {row['status']}")

    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM config")
        cfg = {r["key"]: r["value"] for r in cur.fetchall()}

    return {
        "email": row["email"],
        "name": row.get("name") or "",
        "status": row["status"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "config": cfg,
    }
```

- [ ] **Step 3:** commit.

---

## Task 4: Server — signup returns JWT + email template drops key

**Files:**
- Modify: `server/app.py` — `public_signup` response
- Modify: `server/templates/emails/welcome_new_license.html.j2`
- Modify: `server/templates/emails/welcome_new_license.txt.j2`

- [ ] **Step 1:** require password at signup. In `public_signup` in `server/app.py`, directly after the existing `if not body.agreed_risk:` raise block, add:

```python
    if not body.password or len(body.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="please choose a password of at least 8 characters",
        )
```

- [ ] **Step 2:** issue a JWT as part of the signup response. In `public_signup`, replace the existing return block:

```python
    return {
        "status": "ok",
        "sent": sent,
        "email": email,
        # Only echo the key back on the API response when Resend was
        # skipped (dev mode). Production responses never expose the
        # key so a shoulder-surfer on the signup page can't farm it.
        "key": key if not RESEND_API_KEY else None,
    }
```

with:

```python
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM licenses WHERE key = %s", (key,))
        license_row = cur.fetchone()
    token = _issue_jwt(dict(license_row)) if license_row else None

    return {
        "status": "ok",
        "sent": sent,
        "email": email,
        "token": token,
    }
```

- [ ] **Step 3:** rewrite the welcome email so it no longer contains the licence key. Overwrite `server/templates/emails/welcome_new_license.html.j2` with:

```
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#000;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#fff;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000;">
      <tr><td align="center" style="padding:40px 20px;">
        <table width="520" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
          <tr><td style="padding:0 0 32px 0;">
            <h1 style="margin:0;font-size:44px;font-weight:700;letter-spacing:-0.04em;color:#fff;">blank</h1>
            <p style="margin:6px 0 0 0;font-size:13px;color:rgba(255,255,255,0.5);">autonomous trading terminal</p>
          </td></tr>
          <tr><td style="padding:24px 20px;border:1px solid rgba(255,255,255,0.12);background:#050505;">
            <p style="margin:0 0 12px 0;font-size:15px;color:#fff;">hi {{ name }},</p>
            <p style="margin:0 0 16px 0;font-size:13px;line-height:1.65;color:rgba(255,255,255,0.7);">
              your account is ready. download blank, sign in with the email + password you just chose, and you're off.
            </p>
          </td></tr>
          <tr><td style="padding:28px 0 0 0;" align="center">
            <a href="{{ download_url }}" style="display:inline-block;padding:14px 36px;font-size:13px;letter-spacing:0.08em;color:#00ff87;text-decoration:none;border:1px solid rgba(0,255,135,0.35);background:#000;">download for windows</a>
          </td></tr>
          <tr><td style="padding:40px 0 0 0;border-top:1px solid rgba(255,255,255,0.08);">
            <p style="margin:24px 0 0 0;font-size:10px;letter-spacing:0.1em;color:rgba(255,255,255,0.25);">certified random</p>
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
```

- [ ] **Step 4:** overwrite the plain-text variant `server/templates/emails/welcome_new_license.txt.j2` with:

```
hi {{ name }},

your blank account is ready. download blank and sign in with the email + password you just chose.

download: {{ download_url }}

— certified random
```

- [ ] **Step 5:** commit.

---

## Task 5: Server — login page HTML

**Files:**
- Create: `website/auth_login.html`
- Modify: `server/app.py` — add route to serve it

- [ ] **Step 1:** create `website/auth_login.html` with the following content (small inline stylesheet so it shares the site's aesthetic without importing a full design system):

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>sign in · blank</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
:root { --fg:#fff; --dim:rgba(255,255,255,0.55); --mid:rgba(255,255,255,0.1); --accent:#00ff87; --alert:#ff5f57; }
* { box-sizing:border-box; }
html,body { margin:0; padding:0; background:#000; color:var(--fg); font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif; }
main { min-height:100vh; display:flex; align-items:center; justify-content:center; padding:40px 20px; }
.card { width:100%; max-width:420px; border:1px solid var(--mid); padding:36px 32px; background:#050505; }
h1 { margin:0 0 4px; font-size:40px; letter-spacing:-0.04em; font-weight:700; }
.kicker { margin:0 0 28px; font-family:ui-monospace,Menlo,monospace; font-size:10px; letter-spacing:0.28em; color:var(--dim); text-transform:uppercase; }
label { display:block; margin:16px 0 6px; font-size:11px; letter-spacing:0.18em; text-transform:uppercase; color:var(--dim); }
input { width:100%; background:transparent; border:none; border-bottom:1px solid var(--mid); color:var(--fg); font-size:15px; padding:8px 0; outline:none; }
input:focus { border-bottom-color:var(--accent); }
button { width:100%; margin-top:28px; padding:14px; background:#000; color:var(--accent); border:1px solid rgba(0,255,135,0.35); letter-spacing:0.12em; font-size:12px; text-transform:uppercase; cursor:pointer; }
button:disabled { opacity:0.4; cursor:default; }
.status { margin-top:14px; min-height:18px; font-family:ui-monospace,Menlo,monospace; font-size:11px; letter-spacing:0.12em; text-transform:uppercase; }
.status.err { color:var(--alert); }
.status.ok  { color:var(--accent); }
.small { margin-top:22px; font-size:12px; color:var(--dim); text-align:center; }
.small a { color:var(--fg); }
</style>
</head>
<body>
<main>
  <form class="card" id="loginForm" autocomplete="on">
    <h1>blank</h1>
    <p class="kicker">sign in</p>
    <label for="email">email</label>
    <input id="email" name="email" type="email" autocomplete="email" required />
    <label for="password">password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required minlength="8" />
    <button type="submit" id="submit">continue</button>
    <div id="status" class="status"></div>
    <p class="small">no account? <a href="/#signup">sign up here</a>.</p>
  </form>
</main>
<script>
(function () {
  const params = new URLSearchParams(window.location.search);
  const callbackPort = params.get("callback_port");
  const form = document.getElementById("loginForm");
  const status = document.getElementById("status");
  const submit = document.getElementById("submit");

  function setStatus(msg, cls) {
    status.textContent = msg;
    status.className = "status " + (cls || "");
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    submit.disabled = true;
    setStatus("authenticating…", "");
    try {
      const body = {
        email: document.getElementById("email").value.trim(),
        password: document.getElementById("password").value,
      };
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const j = await r.json().catch(function () { return {}; });
        throw new Error(j.detail || "sign in failed");
      }
      const data = await r.json();
      setStatus("signed in — handing off to the app…", "ok");
      if (callbackPort) {
        // Fire-and-forget GET so we don't need CORS pre-flight.
        window.location.replace(
          "http://127.0.0.1:" + encodeURIComponent(callbackPort)
          + "/auth/callback?token=" + encodeURIComponent(data.token)
        );
      } else {
        setStatus("signed in — you can close this tab.", "ok");
      }
    } catch (e) {
      setStatus((e && e.message) || "sign in failed", "err");
      submit.disabled = false;
    }
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 2:** in `server/app.py`, directly after the existing `/terms` route handler, add:

```python
@app.get("/auth/login", response_class=HTMLResponse)
def auth_login_page() -> HTMLResponse:
    with open(os.path.join(WEBSITE_DIR, "auth_login.html"), encoding="utf-8") as f:
        return HTMLResponse(content=f.read())
```

- [ ] **Step 3:** commit.

---

## Task 6: Website — drop public key display in signup

**Files:**
- Modify: `website/index.html`

- [ ] **Step 1:** locate the signup response handler in `website/index.html` (it currently reads `.key` from the response and shows it to the user). Open `website/index.html`, find the `signupForm` submit handler, and replace the block that displays the key on success (roughly between the existing `account created — check your inbox` success message and the download button reveal) so that the success state reads:

```
account created — check your inbox, then download blank and sign in with your email + password.
```

Do not touch the signup form fields themselves — the existing form already collects email, password, and agreements.

- [ ] **Step 2:** anywhere on the page currently rendering `resp.key` or `data.key` in the UI, delete that line. The server response no longer contains a key field for prod; for dev the key is still ignored.

- [ ] **Step 3:** add a sign-in entry link in the nav/hero so returning users can reach the login page. Add `<a href="/auth/login">sign in</a>` to the top nav (use the same link style as adjacent nav items).

- [ ] **Step 4:** commit.

---

## Task 7: Desktop — auth token storage + HTTP client

**Files:**
- Create: `desktop/auth.py`

- [ ] **Step 1:** create `desktop/auth.py` with:

```python
"""Account auth client — stores a server-issued JWT under ~/.blank/session.token
and exchanges it for user info via /api/auth/me.

Replaces the old licence-key gate. Users never see the licence key; the
server still tracks them in the ``licenses`` table but the app's side of
the wire is pure JWT.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import requests

from desktop.license import _read_server_url, _machine_id  # reuse shared helpers

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


def fetch_me(token: Optional[str] = None, server_url: Optional[str] = None) -> dict[str, Any]:
    """Return {'ok': bool, 'email'?, 'name'?, 'config'?, 'reason'?}.

    Network errors are not fatal — the app still opens signed-out when
    the server is unreachable, so a lost internet connection doesn't
    brick a stored session.
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
    if resp.status_code == 401 or resp.status_code == 403:
        return {"ok": False, "reason": resp.json().get("detail", "unauthorised")}
    if resp.status_code != 200:
        return {"ok": False, "reason": f"server returned {resp.status_code}"}
    body = resp.json()
    return {"ok": True, **body}
```

- [ ] **Step 2:** commit.

---

## Task 8: Desktop — loopback callback server

**Files:**
- Create: `desktop/auth_callback_server.py`

- [ ] **Step 1:** create `desktop/auth_callback_server.py` with:

```python
"""One-shot localhost HTTP server that receives the token the website
posts back after a successful sign-in.

Runs on a random loopback port (picked by the OS). The website redirects
the browser to ``http://127.0.0.1:<port>/auth/callback?token=<jwt>``.
The handler captures the token, renders a tiny success page, then signals
the caller so it can stop the server.
"""
from __future__ import annotations

import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("blank.auth.callback")

_SUCCESS_HTML = b"""\
<!DOCTYPE html><html><head><meta charset="utf-8"><title>signed in</title>
<style>body{margin:0;background:#000;color:#fff;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;height:100vh;display:flex;align-items:center;justify-content:center}
.card{border:1px solid rgba(255,255,255,0.12);padding:28px 32px;text-align:center}
h1{margin:0 0 6px;font-size:28px;letter-spacing:-0.03em}
p{margin:0;color:rgba(255,255,255,0.55);font-size:13px}</style></head>
<body><div class="card"><h1>signed in</h1><p>you can close this tab.</p></div></body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:  # silence stdout
        return

    def do_GET(self) -> None:  # noqa: N802 (stdlib name)
        parsed = urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = parse_qs(parsed.query)
        token = (qs.get("token") or [""])[0].strip()
        server: CallbackServer = self.server  # type: ignore[assignment]
        server.captured_token = token or None
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_SUCCESS_HTML)


class CallbackServer(HTTPServer):
    captured_token: Optional[str] = None


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run(timeout_seconds: int = 180) -> Optional[str]:
    """Start a callback server on a random port, return the captured
    token or None on timeout. Blocks the calling thread."""
    port = _pick_port()
    srv = CallbackServer(("127.0.0.1", port), _Handler)

    done = threading.Event()

    def _serve() -> None:
        try:
            while not done.is_set():
                srv.handle_request()
                if srv.captured_token is not None:
                    done.set()
        except Exception:
            done.set()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    # Expose the port via an attribute so callers can open the browser
    # at the right URL before we block on the token.
    srv.allocated_port = port  # type: ignore[attr-defined]
    done.wait(timeout=timeout_seconds)
    try:
        srv.server_close()
    except Exception:
        pass
    return srv.captured_token


def start(timeout_seconds: int = 180) -> tuple[int, "threading.Thread", "threading.Event", CallbackServer]:
    """Start the callback server in the background and return
    (port, thread, done_event, server). Caller opens the browser, then
    waits on ``done_event`` for the token, which is stored on
    ``server.captured_token``."""
    port = _pick_port()
    srv = CallbackServer(("127.0.0.1", port), _Handler)
    done = threading.Event()

    def _serve() -> None:
        try:
            while not done.is_set():
                srv.timeout = 1.0
                srv.handle_request()
                if srv.captured_token is not None:
                    done.set()
        except Exception:
            done.set()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return port, thread, done, srv
```

- [ ] **Step 2:** commit.

---

## Task 9: Desktop — AuthState singleton with Qt signal

**Files:**
- Create: `desktop/auth_state.py`

- [ ] **Step 1:** create `desktop/auth_state.py` with:

```python
"""Process-wide auth state — every widget that gates on sign-in reads
from and subscribes to this singleton.

Qt's signal/slot system is used so a widget can refresh itself the
instant the user signs in or out, without polling."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal


@dataclass
class AuthSnapshot:
    is_signed_in: bool = False
    email: str = ""
    name: str = ""


class AuthState(QObject):
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._snap = AuthSnapshot()

    @property
    def snapshot(self) -> AuthSnapshot:
        return self._snap

    @property
    def is_signed_in(self) -> bool:
        return self._snap.is_signed_in

    @property
    def email(self) -> str:
        return self._snap.email

    @property
    def name(self) -> str:
        return self._snap.name

    def set_signed_in(self, email: str, name: str = "") -> None:
        self._snap = AuthSnapshot(is_signed_in=True, email=email, name=name)
        self.changed.emit()

    def set_signed_out(self) -> None:
        self._snap = AuthSnapshot()
        self.changed.emit()


_singleton: Optional[AuthState] = None


def auth_state() -> AuthState:
    global _singleton
    if _singleton is None:
        _singleton = AuthState()
    return _singleton
```

- [ ] **Step 2:** commit.

---

## Task 10: Desktop — sign-in prompt dialog (with Skip)

**Files:**
- Create: `desktop/dialogs/signin.py`

- [ ] **Step 1:** create `desktop/dialogs/signin.py` with:

```python
"""Startup sign-in prompt — fully skippable.

Unlike the old licence dialog, this never blocks the app. The user can
skip and browse the UI; gated actions will nudge them to sign in later."""
from __future__ import annotations

import logging
import threading
import webbrowser
from typing import Optional
from urllib.parse import urlencode

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from desktop import tokens as T
from desktop.auth import fetch_me, save_token
from desktop.auth_state import auth_state
from desktop.auth_callback_server import start as start_callback_server
from desktop.license import _read_server_url
from desktop.widgets.primitives.button import apply_variant

logger = logging.getLogger("blank.auth.dialog")


class SignInDialog(QDialog):
    signed_in = Signal()

    def __init__(self, parent: object = None) -> None:
        super().__init__(parent)
        self.setFixedSize(480, 360)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG_0}; border: 1px solid {T.BORDER_0}; }}"
        )
        self._server_url = _read_server_url()
        self._poll_timer: Optional[QTimer] = None
        self._callback_server = None
        self._done_event: Optional[threading.Event] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(42, 40, 42, 34)

        wordmark = QLabel("blank")
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setStyleSheet(
            f"color: {T.FG_0}; font-family: {T.FONT_SANS};"
            f" font-size: 56px; font-weight: 500; letter-spacing: -0.04em;"
        )
        root.addWidget(wordmark)

        kicker = QLabel("SIGN IN")
        kicker.setAlignment(Qt.AlignCenter)
        kicker.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 3px; padding-top: 6px;"
        )
        root.addWidget(kicker)
        root.addSpacing(28)

        caption = QLabel("sign in to enable trading, chat, and the agent.\n"
                         "you can skip and explore the app first.")
        caption.setAlignment(Qt.AlignCenter)
        caption.setWordWrap(True)
        caption.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_SANS}; font-size: 13px;"
        )
        root.addWidget(caption)

        root.addStretch(1)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFixedHeight(22)
        self._status.setStyleSheet(
            f"color: {T.FG_2_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 10px; letter-spacing: 2px;"
        )
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        skip_btn = QPushButton("SKIP")
        apply_variant(skip_btn, "ghost")
        skip_btn.setCursor(Qt.PointingHandCursor)
        skip_btn.clicked.connect(self.reject)
        btn_row.addWidget(skip_btn, 1)

        self._signin_btn = QPushButton("SIGN IN")
        apply_variant(self._signin_btn, "primary")
        self._signin_btn.setCursor(Qt.PointingHandCursor)
        self._signin_btn.clicked.connect(self._start_browser_flow)
        btn_row.addWidget(self._signin_btn, 1)

        root.addLayout(btn_row)

    def _set_status(self, text: str) -> None:
        self._status.setText(text.upper() if text else "")

    def _start_browser_flow(self) -> None:
        self._signin_btn.setEnabled(False)
        self._set_status("waiting for sign-in in your browser...")
        port, _thread, done, srv = start_callback_server(timeout_seconds=180)
        self._callback_server = srv
        self._done_event = done

        qs = urlencode({"callback_port": str(port)})
        webbrowser.open(f"{self._server_url.rstrip('/')}/auth/login?{qs}")

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(250)
        self._poll_timer.timeout.connect(self._check_callback)
        self._poll_timer.start()

    def _check_callback(self) -> None:
        if not self._callback_server or not self._done_event:
            return
        token = self._callback_server.captured_token
        if token is None and not self._done_event.is_set():
            return

        if self._poll_timer:
            self._poll_timer.stop()

        if not token:
            self._set_status("sign-in cancelled or timed out")
            self._signin_btn.setEnabled(True)
            return

        save_token(token)
        result = fetch_me(token=token, server_url=self._server_url)
        if not result.get("ok"):
            self._set_status(result.get("reason", "sign-in failed"))
            self._signin_btn.setEnabled(True)
            return

        auth_state().set_signed_in(
            email=result.get("email", ""),
            name=result.get("name", ""),
        )
        self.signed_in.emit()
        self.accept()

    def run(self) -> bool:
        _show = getattr(self, "exec")
        return _show() == QDialog.Accepted
```

- [ ] **Step 2:** commit.

---

## Task 11: Desktop — persistent "sign in" banner widget

**Files:**
- Create: `desktop/widgets/signin_banner.py`

- [ ] **Step 1:** create `desktop/widgets/signin_banner.py` with:

```python
"""Persistent banner shown at the top of the main window while the user
is signed out. Reads the shared AuthState and hides itself once signed in."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from desktop import tokens as T
from desktop.auth_state import auth_state
from desktop.widgets.primitives.button import apply_variant


class SignInBanner(QWidget):
    signin_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget {{ background: {T.BG_1}; border-bottom: 1px solid {T.BORDER_1}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(12)

        msg = QLabel("sign in to start trading")
        msg.setStyleSheet(
            f"color: {T.FG_1_HEX}; font-family: {T.FONT_MONO};"
            f" font-size: 11px; letter-spacing: 2px; background: transparent;"
        )
        layout.addWidget(msg, 1)

        btn = QPushButton("SIGN IN")
        apply_variant(btn, "primary")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.signin_requested)
        layout.addWidget(btn, 0)

        auth_state().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.setVisible(not auth_state().is_signed_in)
```

- [ ] **Step 2:** commit.

---

## Task 12: Desktop — profile button corner widget

**Files:**
- Create: `desktop/widgets/profile_button.py`

- [ ] **Step 1:** create `desktop/widgets/profile_button.py` with:

```python
"""Top-right profile widget. Shows 'SIGN IN' when signed out and the
user's email + a dropdown (account / sign out) when signed in."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from desktop import tokens as T
from desktop.auth import clear_token
from desktop.auth_state import auth_state


class ProfileButton(QToolButton):
    signin_requested = Signal()
    signout_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setStyleSheet(
            f"QToolButton {{ color: {T.FG_0}; background: transparent;"
            f" border: 1px solid {T.BORDER_1}; padding: 4px 10px;"
            f" font-family: {T.FONT_MONO}; font-size: 10px; letter-spacing: 2px; }}"
            f"QToolButton:hover {{ border: 1px solid {T.ACCENT_HEX}; }}"
            f"QToolButton::menu-indicator {{ image: none; }}"
        )
        auth_state().changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        state = auth_state()
        if state.is_signed_in:
            label = state.email or state.name or "ACCOUNT"
            self.setText(label.upper())
            menu = QMenu(self)
            act_account = menu.addAction("account details")
            act_account.setEnabled(False)  # Placeholder — account page is TBD.
            act_out = menu.addAction("sign out")
            act_out.triggered.connect(self._on_signout)
            self.setMenu(menu)
        else:
            self.setText("SIGN IN")
            self.setMenu(None)
            try:
                self.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            self.clicked.connect(self._on_signin_click)

    def _on_signin_click(self) -> None:
        self.signin_requested.emit()

    def _on_signout(self) -> None:
        clear_token()
        auth_state().set_signed_out()
        self.signout_requested.emit()
```

- [ ] **Step 2:** commit.

---

## Task 13: Desktop — `auth_gate` helper for inline toasts

**Files:**
- Create: `desktop/auth_gate.py`

- [ ] **Step 1:** create `desktop/auth_gate.py` with:

```python
"""Central gating helper — every interactive action routes through
``require_auth(parent, action)``.

When signed in: runs the action.
When signed out: shows a small non-modal toast near the parent widget
saying 'sign in to use blank' and emits the global ``signin_requested``
signal so the main window can raise the sign-in dialog."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QWidget

from desktop import tokens as T
from desktop.auth_state import auth_state


class _AuthGateBus(QObject):
    signin_requested = Signal()


_bus = _AuthGateBus()


def bus() -> _AuthGateBus:
    return _bus


def _toast(parent: QWidget, text: str) -> None:
    lbl = QLabel(text.upper(), parent)
    lbl.setWindowFlags(Qt.ToolTip)
    lbl.setAttribute(Qt.WA_DeleteOnClose)
    lbl.setStyleSheet(
        f"QLabel {{ background: {T.BG_0}; border: 1px solid {T.ACCENT_HEX};"
        f" color: {T.ACCENT_HEX}; font-family: {T.FONT_MONO};"
        f" font-size: 10px; letter-spacing: 2px; padding: 8px 14px; }}"
    )
    pos = parent.mapToGlobal(parent.rect().center())
    lbl.adjustSize()
    lbl.move(pos.x() - lbl.width() // 2, pos.y() - lbl.height() // 2)
    lbl.show()
    QTimer.singleShot(2200, lbl.close)


def require_auth(parent: QWidget, action: Callable[[], None]) -> None:
    if auth_state().is_signed_in:
        action()
        return
    _toast(parent, "sign in to use blank")
    _bus.signin_requested.emit()
```

- [ ] **Step 2:** commit.

---

## Task 14: Desktop — main.py: drop licence gate, add auth bootstrap

**Files:**
- Modify: `desktop/main.py`

- [ ] **Step 1:** remove the licence gate. In `desktop/main.py`, delete the entire `# ── License gate ───` block (lines ~208-226 in the current file):

```python
    # ── License gate ─────────────────────────────────────────────────
    from desktop.dialogs.license import LicenseDialog

    stored_key = _read_stored_key()

    if stored_key:
        result = validate(server_url=server_url, key=stored_key)
        if not result.get("valid"):
            dialog = LicenseDialog(server_url=server_url)
            if not dialog.run():
                sys.exit(0)
            result = validate(server_url=server_url)
    else:
        dialog = LicenseDialog(server_url=server_url)
        if not dialog.run():
            sys.exit(0)
        result = validate(server_url=server_url)

    logger.info("License validated — launching app")
```

- [ ] **Step 2:** also delete the now-unused imports at line ~194:

```python
    from desktop.license import validate, _read_stored_key, _read_server_url
```

and replace with:

```python
    from desktop.license import _read_server_url
```

- [ ] **Step 3:** immediately after the wake-thread block, add:

```python
    # ── Auth bootstrap ──────────────────────────────────────────────
    # Try the stored session silently. If it's valid we go straight into
    # the app signed-in; otherwise we open the optional sign-in prompt
    # (the user can Skip and explore the UI signed-out).
    from desktop.auth import fetch_me
    from desktop.auth_state import auth_state
    from desktop.dialogs.signin import SignInDialog

    me = fetch_me(server_url=server_url)
    if me.get("ok"):
        auth_state().set_signed_in(
            email=me.get("email", ""),
            name=me.get("name", ""),
        )
        result = {"config": me.get("config", {})}
    else:
        # Optional prompt. Skip is a first-class choice — the app opens
        # signed-out and the individual gating sites nudge the user.
        dialog = SignInDialog()
        dialog.run()
        # Refresh state after the dialog closes regardless of outcome.
        me = fetch_me(server_url=server_url)
        if me.get("ok"):
            auth_state().set_signed_in(
                email=me.get("email", ""),
                name=me.get("name", ""),
            )
            result = {"config": me.get("config", {})}
        else:
            result = {"config": {}}
```

- [ ] **Step 4:** commit.

---

## Task 15: Desktop — wire profile button + banner into MainWindow

**Files:**
- Modify: `desktop/app.py`

- [ ] **Step 1:** add these imports near the other `from desktop.widgets` / `from desktop.panels` imports at the top of `desktop/app.py`:

```python
from desktop.widgets.profile_button import ProfileButton
from desktop.widgets.signin_banner import SignInBanner
from desktop.auth_gate import bus as auth_gate_bus
from desktop.auth_state import auth_state
```

- [ ] **Step 2:** in `_build_ui`, just before the `mode_str = ...` / `self._header_label = ...` block (where the menu-bar right corner widget is set), add:

```python
        # Profile corner widget — shows email + dropdown when signed in,
        # 'SIGN IN' otherwise.
        self._profile_button = ProfileButton(self)
        self._profile_button.signin_requested.connect(self._open_signin_dialog)
        self._profile_button.signout_requested.connect(self._on_signed_out)
```

Then replace:

```python
        menu_bar.setCornerWidget(self._header_label, Qt.TopRightCorner)
```

with a small container so both the header label and the profile button share the right corner:

```python
        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(8)
        corner_layout.addWidget(self._header_label)
        corner_layout.addWidget(self._profile_button)
        menu_bar.setCornerWidget(corner, Qt.TopRightCorner)
```

(Add `QHBoxLayout` to the import from `PySide6.QtWidgets` at the top of the file if it's not already imported.)

- [ ] **Step 3:** in the same `_build_ui` method, directly after `self.update_banner = UpdateBanner(self)` (around line 293), instantiate the sign-in banner and add it to `central_layout`:

```python
        self.signin_banner = SignInBanner(self)
        self.signin_banner.signin_requested.connect(self._open_signin_dialog)
        central_layout.addWidget(self.signin_banner)
```

- [ ] **Step 4:** at the end of `__init__` (right before `self._build_ui()` is called — or immediately after it; either is fine as long as it runs once), wire the gate bus:

```python
        auth_gate_bus().signin_requested.connect(self._open_signin_dialog)
        auth_state().changed.connect(self._on_auth_changed)
```

- [ ] **Step 5:** add new methods on `MainWindow`:

```python
    def _open_signin_dialog(self) -> None:
        from desktop.dialogs.signin import SignInDialog
        dlg = SignInDialog(self)
        dlg.run()

    def _on_signed_out(self) -> None:
        # Tearing down the agent pool on sign-out keeps the user's
        # unauthenticated session from quietly continuing to trade.
        try:
            if self.agent_pool is not None:
                self.agent_pool.stop_supervisor()
        except Exception:
            pass
        self._on_auth_changed()

    def _on_auth_changed(self) -> None:
        signed_in = auth_state().is_signed_in
        # Enable / disable agent controls based on auth.
        for attr in ("_agent_start_action", "_agent_stop_action", "_agent_kill_action"):
            action = getattr(self, attr, None)
            if action is not None:
                action.setEnabled(signed_in and attr != "_agent_start_action"
                                  if attr == "_agent_stop_action"
                                  else signed_in)
        # Ask every panel that cares to refresh its gated state.
        for panel_attr in ("agent_log_panel", "chat_panel", "watchlist_panel",
                           "positions_panel", "orders_panel"):
            panel = getattr(self, panel_attr, None)
            refresh = getattr(panel, "refresh_auth_state", None)
            if callable(refresh):
                try:
                    refresh(signed_in)
                except Exception:
                    pass
```

- [ ] **Step 6:** commit.

---

## Task 16: Desktop — gate `_on_agent_start` and `action_open_trade`

**Files:**
- Modify: `desktop/app.py`

- [ ] **Step 1:** in `desktop/app.py`, wrap `_on_agent_start` so it no-ops when signed-out. Replace the first line of the existing `_on_agent_start` body with an auth check:

```python
    def _on_agent_start(self) -> None:
        from desktop.auth_gate import require_auth
        require_auth(self, self._do_agent_start)

    def _do_agent_start(self) -> None:
```

Rename the existing body (currently under `_on_agent_start`) to `_do_agent_start`. The rest of the method is unchanged.

- [ ] **Step 2:** similarly wrap `action_open_trade`. Replace:

```python
    def action_open_trade(self) -> None:
```

with:

```python
    def action_open_trade(self) -> None:
        from desktop.auth_gate import require_auth
        require_auth(self, self._do_open_trade)

    def _do_open_trade(self) -> None:
```

Keep the existing body under the new `_do_open_trade` name.

- [ ] **Step 3:** also gate `_handle_chat_message` (the chat submission slot). Find the existing method signature `def _handle_chat_message(self, message: str) -> None:` and insert a guard at the top of the body:

```python
        if not auth_state().is_signed_in:
            from desktop.auth_gate import require_auth
            require_auth(self, lambda: None)
            return
```

- [ ] **Step 4:** commit.

---

## Task 17: Desktop — gate the agent log panel's Start button

**Files:**
- Modify: `desktop/panels/agent_log.py`

- [ ] **Step 1:** open `desktop/panels/agent_log.py`. Add an `auth_state` subscription in `__init__` so the Start button is disabled when signed out:

Add imports:

```python
from desktop.auth_state import auth_state
```

At the end of `__init__`, add:

```python
        auth_state().changed.connect(self._refresh_auth_state)
        self._refresh_auth_state()

    def _refresh_auth_state(self) -> None:
        signed_in = auth_state().is_signed_in
        # Keep existing enable/disable logic, but force-disable Start
        # when signed-out so the user doesn't even see it available.
        if hasattr(self, "_start_btn") and self._start_btn is not None:
            self._start_btn.setEnabled(signed_in and not self._is_running)

    def refresh_auth_state(self, signed_in: bool) -> None:
        self._refresh_auth_state()
```

Replace the `hasattr` line's reference `_start_btn` with the actual start button attribute used in the panel (use `Read` first to confirm the attribute name). If the panel uses a different name (e.g. `self.start_button`), adjust accordingly. If the panel tracks a running flag under a different name, use that one; otherwise fall back to checking `signed_in` alone.

- [ ] **Step 2:** commit.

---

## Task 18: Desktop — gate the chat panel's input

**Files:**
- Modify: `desktop/panels/chat.py`

- [ ] **Step 1:** open `desktop/panels/chat.py` and add an auth subscription so the input field is disabled with placeholder text "sign in to chat" when signed-out.

Add:

```python
from desktop.auth_state import auth_state
```

In `__init__`, at the end:

```python
        auth_state().changed.connect(self._refresh_auth_state)
        self._refresh_auth_state()

    def _refresh_auth_state(self) -> None:
        signed_in = auth_state().is_signed_in
        # Locate the chat input widget actually used by this panel. We
        # disable it and swap its placeholder so the user knows why.
        for attr in ("_input", "input_field", "input"):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "setEnabled"):
                widget.setEnabled(signed_in)
                if hasattr(widget, "setPlaceholderText"):
                    widget.setPlaceholderText(
                        "ask blank anything..." if signed_in
                        else "sign in to chat"
                    )
                break

    def refresh_auth_state(self, signed_in: bool) -> None:
        self._refresh_auth_state()
```

- [ ] **Step 2:** commit.

---

## Task 19: Desktop — delete the licence dialog

**Files:**
- Delete: `desktop/dialogs/license.py`
- Modify: `desktop/dialogs/__init__.py` if it re-exports the dialog

- [ ] **Step 1:** delete `desktop/dialogs/license.py`.

- [ ] **Step 2:** run `grep -r "from desktop.dialogs.license" E:/Coding/StockMarketAI/.claude/worktrees/sleepy-tesla-5726f4/` and remove or redirect any remaining imports. Expected hits: `desktop/main.py` (already removed in Task 14) and possibly `desktop/dialogs/__init__.py`.

- [ ] **Step 3:** commit.

---

## Task 20: Desktop — heartbeat stops sending the key as auth

**Files:**
- Modify: `desktop/license.py`

- [ ] **Step 1:** `desktop/license.py` currently lets the heartbeat send the licence key for identity. That still works server-side (the key is an internal ID). Leave the existing `_machine_id()` helper, `_read_server_url()`, and `send_logs()` functions intact — other modules still import them. Remove the `save_key`, `_read_stored_key`, `validate`, and `LICENSE_FILE` symbols from the file because nothing in the app uses them any more after Task 14.

After edit, `desktop/license.py` should contain only:
- `LICENSE_FILE` definition can remain if `send_logs` still reads the old key file; if you remove `_read_stored_key`, also remove the fallback in `send_logs` — it is now a dev-only endpoint.
- Simpler path: keep `_read_stored_key` and `save_key` as no-ops so stale imports don't break, and add a module-level comment explaining why they are stubs.

Concretely, replace the body of `desktop/license.py` after the existing `_machine_id()` function with:

```python
def _read_stored_key() -> Optional[str]:
    """Legacy shim — the app no longer stores a licence key. Returns
    None so callers that still check for one (heartbeat, send_logs)
    treat the request as anonymous."""
    return None


def save_key(key: str) -> None:  # noqa: ARG001 — legacy signature
    """Legacy shim. The app no longer prompts for licence keys."""
    return None


def send_logs(entries: list[dict[str, str]], server_url: Optional[str] = None) -> bool:
    """Best-effort log forwarding. Anonymous after the auth migration —
    the server accepts an empty key and simply files the logs under an
    unknown-licence bucket. Returns True on 2xx."""
    server_url = server_url or _read_server_url()
    try:
        resp = requests.post(
            f"{server_url.rstrip('/')}/api/logs",
            json={"license_key": "", "entries": entries},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception:
        return False
```

(Delete the old `validate()` function entirely.)

- [ ] **Step 2:** commit.

---

## Task 21: Desktop — signup form tidy on website (already in Task 6)

Nothing new here — Task 6 already covered website copy changes. Double-check visually before marking done.

---

## Task 22: End-to-end smoke test checklist

- [ ] App launches without any stored session → sign-in prompt appears, Skip closes it, main window opens, banner is visible, profile shows "SIGN IN", Agent → Start is disabled.
- [ ] Click "Sign in" (profile or banner) → browser opens to `/auth/login?callback_port=...`, logging in redirects to `127.0.0.1:<port>/auth/callback?token=...`, app receives token, profile flips to email, banner disappears, Agent → Start is enabled.
- [ ] Start agent now works; place trade dialog opens; chat input accepts text.
- [ ] Click profile → "sign out" → token file removed, UI greys out, banner returns, agent pool stopped.
- [ ] Restart app with stored token → bypasses the prompt, opens signed-in.
- [ ] Restart app with server unreachable → opens signed-out (no crash).
- [ ] No references to `BLK-XXXX-XXXX` or "licence key" remain in user-facing desktop text.

---

## Task 23: Commit remaining edits & push

- [ ] **Step 1:** run `git status` to review.
- [ ] **Step 2:** commit any stragglers.
- [ ] **Step 3:** push the branch to main per the user's instructions.
