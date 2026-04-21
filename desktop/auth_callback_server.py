"""One-shot localhost HTTP server that receives the token the website
sends back after a successful sign-in.

Runs on a random loopback port (picked by the OS). The website redirects
the browser to ``http://127.0.0.1:<port>/auth/callback?token=<jwt>``.
The handler captures the token, renders a tiny success page, then
signals the caller so it can stop the server.
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
    def log_message(self, fmt: str, *args: object) -> None:
        return  # silence stdout

    def do_GET(self) -> None:  # noqa: N802 — stdlib name
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
    allocated_port: int = 0


def _pick_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(timeout_seconds: int = 180) -> tuple[int, threading.Thread, threading.Event, CallbackServer]:
    """Start the callback server in the background and return
    ``(port, thread, done_event, server)``.

    The caller opens the browser, polls ``server.captured_token``
    (Qt-friendly) or waits on ``done_event`` (blocking-friendly), and
    calls ``server.server_close()`` when finished.
    """
    port = _pick_port()
    srv = CallbackServer(("127.0.0.1", port), _Handler)
    srv.allocated_port = port
    done = threading.Event()

    def _serve() -> None:
        try:
            # ``timeout`` lets ``handle_request`` exit periodically so
            # we can check the done flag and not hang the thread when
            # the user closes the dialog before the browser posts back.
            srv.timeout = 1.0
            while not done.is_set():
                srv.handle_request()
                if srv.captured_token is not None:
                    done.set()
        except Exception as exc:
            logger.info("callback server stopped: %s", exc)
            done.set()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return port, thread, done, srv
