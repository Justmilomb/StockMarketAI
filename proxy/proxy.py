"""Simple HTTP/HTTPS proxy that chains through an upstream Spanish proxy."""

import socket
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import http.client
import ssl


# ── Config ──────────────────────────────────────────────────────────────
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8080

# Spanish proxies (Madrid) — ordered by speed
UPSTREAM_PROXIES: list[tuple[str, int]] = [
    ("185.18.250.112", 80),   # 780ms
    ("185.18.250.167", 80),   # 801ms
    ("185.18.250.32", 80),    # 811ms
    ("185.18.250.206", 80),   # 836ms
    ("185.18.250.142", 80),   # 847ms
    ("185.18.250.127", 80),   # 849ms
    ("185.18.250.164", 80),   # 863ms
    ("185.18.250.168", 80),   # 864ms
    ("185.18.250.161", 80),   # 871ms
    ("185.18.250.66", 80),    # 886ms
    ("185.18.250.214", 80),   # 895ms
    ("185.18.250.237", 80),   # 898ms
    ("185.18.250.48", 80),    # 902ms
    ("185.18.250.78", 80),    # 910ms
    ("185.18.250.57", 80),    # 941ms
    ("185.18.250.179", 80),   # 945ms
    ("185.18.250.34", 80),    # 965ms
    ("185.18.250.10", 80),    # 1017ms
    ("185.18.250.47", 80),    # 1025ms
]

# Active upstream — set by _find_working_proxy() at startup
UPSTREAM_HOST = ""
UPSTREAM_PORT = 0
# ────────────────────────────────────────────────────────────────────────


def has_upstream() -> bool:
    return bool(UPSTREAM_HOST) and UPSTREAM_PORT > 0


def _find_working_proxy() -> tuple[str, int] | None:
    """Test proxies in order and return the first one that responds."""
    global UPSTREAM_HOST, UPSTREAM_PORT
    print("Testing Spanish proxies...")
    for host, port in UPSTREAM_PROXIES:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            UPSTREAM_HOST = host
            UPSTREAM_PORT = port
            print(f"  OK  {host}:{port}")
            return (host, port)
        except (OSError, TimeoutError):
            print(f"  FAIL {host}:{port}")
    return None


class ProxyHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests and CONNECT tunnels."""

    def do_CONNECT(self) -> None:
        """HTTPS tunnelling via CONNECT method."""
        host, port = self._parse_host_port(self.path, default_port=443)

        try:
            remote = None

            # Try upstream CONNECT first, fall back to direct if it refuses
            if has_upstream():
                try:
                    remote = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=10)
                    remote.sendall(f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
                    response = remote.recv(4096)
                    if b"200" not in response.split(b"\r\n")[0]:
                        remote.close()
                        remote = None
                        print(f"[proxy] Upstream refused CONNECT for {host}:{port} — going direct")
                except (OSError, TimeoutError):
                    if remote:
                        remote.close()
                    remote = None
                    print(f"[proxy] Upstream unreachable for CONNECT {host}:{port} — going direct")

            if remote is None:
                remote = socket.create_connection((host, port), timeout=10)

            self.send_response(200, "Connection Established")
            self.end_headers()

            self._tunnel(self.connection, remote)
        except Exception as e:
            self.send_error(502, f"Tunnel failed: {e}")

    def do_GET(self) -> None:
        self._proxy_request("GET")

    def do_POST(self) -> None:
        self._proxy_request("POST")

    def do_PUT(self) -> None:
        self._proxy_request("PUT")

    def do_DELETE(self) -> None:
        self._proxy_request("DELETE")

    def do_HEAD(self) -> None:
        self._proxy_request("HEAD")

    def _proxy_request(self, method: str) -> None:
        """Forward an HTTP request, optionally via upstream proxy."""
        url = urlparse(self.path)
        host = url.hostname or ""
        port = url.port or (443 if url.scheme == "https" else 80)
        path = url.path + (f"?{url.query}" if url.query else "")

        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            body = self.rfile.read(int(content_length))

        try:
            if has_upstream():
                # Send full URL to upstream proxy
                conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=15)
                conn.request(method, self.path, body=body, headers=dict(self.headers))
            else:
                if url.scheme == "https":
                    ctx = ssl.create_default_context()
                    conn = http.client.HTTPSConnection(host, port, timeout=15, context=ctx)
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=15)
                conn.request(method, path, body=body, headers=dict(self.headers))

            resp = conn.getresponse()
            self.send_response(resp.status)
            for header, value in resp.getheaders():
                if header.lower() not in ("transfer-encoding",):
                    self.send_header(header, value)
            self.end_headers()
            self.wfile.write(resp.read())
            conn.close()
        except Exception as e:
            self.send_error(502, f"Request failed: {e}")

    def _tunnel(self, client: socket.socket, remote: socket.socket) -> None:
        """Bidirectional byte shuttle for CONNECT tunnels."""
        def forward(src: socket.socket, dst: socket.socket) -> None:
            try:
                while True:
                    data = src.recv(8192)
                    if not data:
                        break
                    dst.sendall(data)
            except (OSError, ConnectionError):
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t1 = threading.Thread(target=forward, args=(client, remote), daemon=True)
        t2 = threading.Thread(target=forward, args=(remote, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        remote.close()

    def _parse_host_port(self, address: str, default_port: int = 80) -> tuple[str, int]:
        if ":" in address:
            host, port_str = address.rsplit(":", 1)
            return host, int(port_str)
        return address, default_port

    def log_message(self, format: str, *args) -> None:
        print(f"[proxy] {self.address_string()} — {format % args}")


def main() -> None:
    result = _find_working_proxy()
    if not result:
        print("\nWARNING: No working Spanish proxy found — running as direct proxy (no Spanish IP).\n")

    server = HTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    print(f"\nProxy listening on {LISTEN_HOST}:{LISTEN_PORT}")
    if has_upstream():
        print(f"Chaining through {UPSTREAM_HOST}:{UPSTREAM_PORT} (Madrid, Spain)")
    print("Configure your browser to use 127.0.0.1:8080 as HTTP proxy.")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
