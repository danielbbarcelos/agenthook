"""Egress broker — the only peer a job container can reach.

The job container runs on an ``internal`` Docker network (no route to the
internet), so *every* outbound packet either goes to this broker or is dropped
by the kernel. That is the fail-closed guarantee: egress control comes from the
network topology, not from anything inside the container that a subverted agent
could tamper with.

Two planes, two ports, run by one process (stdlib only, so the image stays a
bare ``python:slim``):

* **Data plane** (``GW_PORT``, reachable from the job as ``egress:<port>``)
  - *Gateway*: ``/<token>/<rest>`` reverse-proxies to the token's registered
    upstream, injecting the real credential header. The container holds only a
    dummy key, so a prompt-injected agent has nothing worth exfiltrating — and
    could not exfiltrate it anyway (see fail-closed above). Streams responses
    (SSE) chunk-by-chunk.
  - *Forward proxy*: ``CONNECT host:port`` is tunneled only if ``host`` is on the
    token's allowlist (token carried in ``Proxy-Authorization: Basic <token>:``).
* **Control plane** (``CTRL_PORT``, published to host loopback only) — the host
  runner registers/deregisters a job's token→(upstream, key, allowlist) mapping.
  Never reachable from the job network.

The credential and allowlist therefore live only here on the host side; the job
never sees either. Tokens are per-job and revoked when the job finalizes.
"""

from __future__ import annotations

import base64
import fnmatch
import http.client
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

GW_PORT = int(os.environ.get("AGENTHOOK_EGRESS_GW_PORT", "8080"))
CTRL_PORT = int(os.environ.get("AGENTHOOK_EGRESS_CTRL_PORT", "8079"))

# token -> {"upstream": "https://api.anthropic.com", "header": "x-api-key",
#           "value": "<real key>", "allow": ["api.anthropic.com", ...]}
_REG: dict[str, dict] = {}
_REG_LOCK = threading.Lock()

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


def _host_allowed(host: str, allow: list[str]) -> bool:
    host = (host or "").lower()
    return any(fnmatch.fnmatch(host, pat.lower()) for pat in allow)


class _DataHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silence default stderr logging
        pass

    # ---- forward proxy (HTTPS via CONNECT) --------------------------------
    def do_CONNECT(self):  # noqa: N802
        token = self._proxy_token()
        reg = _lookup(token)
        host, _, port = self.path.partition(":")
        if not reg or not _host_allowed(host, reg["allow"]):
            self.send_error(403, "egress host not allowed")
            return
        try:
            upstream = socket.create_connection((host, int(port or 443)), timeout=30)
        except OSError:
            self.send_error(502, "upstream connect failed")
            return
        self.send_response(200, "Connection Established")
        self.end_headers()
        _tunnel(self.connection, upstream)

    # ---- gateway (reverse proxy with credential injection) ----------------
    def do_GET(self):  # noqa: N802
        self._gateway()

    def do_POST(self):  # noqa: N802
        self._gateway()

    def do_PUT(self):  # noqa: N802
        self._gateway()

    def do_DELETE(self):  # noqa: N802
        self._gateway()

    def _gateway(self):
        # path is /<token>/<rest...>
        parts = self.path.lstrip("/").split("/", 1)
        token = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        reg = _lookup(token)
        if not reg:
            self.send_error(403, "unknown egress token")
            return
        up = urlsplit(reg["upstream"])
        host = up.hostname or ""
        if not _host_allowed(host, reg["allow"]):
            self.send_error(403, "upstream host not allowed")
            return
        body = self._read_body()
        conn_cls = http.client.HTTPSConnection if up.scheme == "https" else http.client.HTTPConnection
        port = up.port or (443 if up.scheme == "https" else 80)
        try:
            conn = conn_cls(host, port, timeout=600)
            headers = self._forward_headers(host)
            # Inject the real credential for api-key engines. For subscription
            # (empty value) we forward the CLI's own auth header untouched.
            if reg["value"]:
                headers[reg["header"]] = reg["value"]
            target = "/" + rest
            if up.path and up.path != "/":
                target = up.path.rstrip("/") + target
            conn.request(self.command, target, body=body, headers=headers)
            resp = conn.getresponse()
            self._relay_response(resp)
        except Exception as exc:  # noqa: BLE001
            self.send_error(502, f"upstream error: {exc}")

    # ---- helpers ----------------------------------------------------------
    def _proxy_token(self) -> str:
        h = self.headers.get("Proxy-Authorization", "")
        if h.startswith("Basic "):
            try:
                raw = base64.b64decode(h[6:]).decode("utf-8", "replace")
                return raw.split(":", 1)[0]
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def _read_body(self) -> bytes | None:
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else None

    def _forward_headers(self, host: str) -> dict:
        out = {}
        for k, v in self.headers.items():
            if k.lower() in _HOP_BY_HOP:
                continue
            out[k] = v
        out["Host"] = host
        return out

    def _relay_response(self, resp):
        self.send_response(resp.status)
        streamed = False
        for k, v in resp.getheaders():
            lk = k.lower()
            if lk in _HOP_BY_HOP or lk == "content-length":
                continue
            self.send_header(k, v)
        # stream with chunked transfer so SSE flows token-by-token
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        streamed = True
        while True:
            chunk = resp.read(8192)
            if not chunk:
                break
            self.wfile.write(b"%X\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        if streamed:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()


class _CtrlHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "registered": len(_REG)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "bad json"})
            return
        if self.path == "/register":
            tok = data.get("token")
            if not tok:
                self._json(400, {"error": "token required"})
                return
            with _REG_LOCK:
                _REG[tok] = {
                    "upstream": data.get("upstream", ""),
                    "header": data.get("header", "authorization"),
                    "value": data.get("value", ""),
                    "allow": list(data.get("allow", [])),
                }
            self._json(200, {"ok": True})
        elif self.path == "/deregister":
            with _REG_LOCK:
                _REG.pop(data.get("token", ""), None)
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _lookup(token: str) -> dict | None:
    with _REG_LOCK:
        reg = _REG.get(token)
        return dict(reg) if reg else None


def _tunnel(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional blind relay between two sockets until either closes."""
    def pipe(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    t = threading.Thread(target=pipe, args=(b, a), daemon=True)
    t.start()
    pipe(a, b)
    t.join(timeout=1)


def main() -> None:
    data_srv = ThreadingHTTPServer(("0.0.0.0", GW_PORT), _DataHandler)
    ctrl_srv = ThreadingHTTPServer(("0.0.0.0", CTRL_PORT), _CtrlHandler)
    threading.Thread(target=ctrl_srv.serve_forever, daemon=True).start()
    print(f"egress broker: gateway :{GW_PORT}  control :{CTRL_PORT}", flush=True)
    data_srv.serve_forever()


if __name__ == "__main__":
    main()
