"""Management API protection (control-plane, ``/admin/*``).

The management surface exposes sensitive configuration (instances, secrets,
auth, guardrails), so it is guarded by two independent gates:

1. **Network** — by default it only answers loopback clients. Remote access is
   an explicit opt-in (``admin_remote: true`` in ``config.yaml``), optionally
   narrowed to a CIDR allowlist (``admin_ip_allow``, e.g. the Workspace backend's
   egress IP). Loopback is always allowed.
2. **Credential** — a bearer, accepted in two forms against the same secret
   (``AGENTHOOK_ADMIN_TOKEN`` env, else ``config.admin_token``):
   - a **short-lived HS256 JWT** (``exp`` ≤ ~5 min, mandatory ``jti`` for
     anti-replay) — the machine plane (the Workspace mints these per request);
   - the **static token** itself (legacy / local operator), compared in
     constant time.

Both gates must pass. Wire it as a router-wide dependency:
``APIRouter(dependencies=[Depends(require_admin)])``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import threading
import time

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import _ip_allowed
from .config import load_config

# Declared security scheme so OpenAPI/Swagger renders an "Authorize" button for
# ``/admin/*``. ``auto_error=False`` keeps require_admin the sole owner of the
# 401 (and lets the network check run first); enforcement is unchanged — this
# only teaches Swagger to attach the bearer header.
_bearer = HTTPBearer(
    auto_error=False,
    description="admin token, or a short-lived HS256 JWT signed with it",
)

_LOOPBACK_HOSTS = {"localhost", "testclient"}

# Reject a JWT whose remaining lifetime exceeds this — caps a misconfigured or
# malicious long-lived token even if signed with the right secret (target ~5 min
# + clock-skew headroom).
_JWT_MAX_TTL_S = 600
# Seen jti -> exp, for anti-replay. Small and self-reaping (entries live only
# until the token they belong to would have expired anyway).
_SEEN_JTI: dict[str, float] = {}
_JTI_LOCK = threading.Lock()


def _is_loopback(host: str | None) -> bool:
    """True for loopback clients. ``testclient`` (FastAPI TestClient) and bare
    hostnames are treated as local; everything else is parsed as an IP."""
    if not host:
        return False
    if host in _LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _admin_token() -> str:
    return os.environ.get("AGENTHOOK_ADMIN_TOKEN") or load_config().admin_token


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _verify_hs256(token: str, secret: str, *, now: float) -> dict | None:
    """Validate a compact HS256 JWT signed with ``secret``. Returns the claims if
    the signature and ``exp`` are valid (and the remaining life is bounded), else
    None. Pure stdlib (HS256 == HMAC-SHA256) — no new dependency."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]))
        claims = json.loads(_b64url_decode(parts[1]))
        sig = _b64url_decode(parts[2])
    except Exception:  # noqa: BLE001 - any decode failure is just an invalid token
        return None
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        return None
    expected = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp <= now:
        return None
    if exp - now > _JWT_MAX_TTL_S:
        return None
    return claims


def _jti_fresh(jti: str, exp: float, now: float) -> bool:
    """True (and records it) if ``jti`` hasn't been seen; False on replay."""
    with _JTI_LOCK:
        for k in [k for k, e in _SEEN_JTI.items() if e <= now]:
            _SEEN_JTI.pop(k, None)
        if jti in _SEEN_JTI:
            return False
        _SEEN_JTI[jti] = exp
        return True


def _authenticate(token: str, secret: str, *, now: float | None = None) -> bool:
    """Accept a short-lived HS256 JWT (mandatory ``jti`` anti-replay) or the
    static token itself (constant-time)."""
    now = time.time() if now is None else now
    if token.count(".") == 2:  # shaped like a compact JWT (static tokens have no dots)
        claims = _verify_hs256(token, secret, now=now)
        if claims is None:
            return False
        jti = claims.get("jti")
        if not jti:  # anti-replay requires a jti; reject JWTs without one
            return False
        return _jti_fresh(str(jti), float(claims["exp"]), now)
    return hmac.compare_digest(token, secret)


def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """FastAPI dependency: enforce the network + credential gates for ``/admin/*``.

    Raises 403 from a disallowed network/IP, 401 on a missing/invalid credential.
    The credential is read from the declared bearer scheme (so Swagger's Authorize
    works); ``credentials`` is None when the header is absent or not ``Bearer``.
    """
    cfg = load_config()
    client_ip = request.client.host if request.client else None
    loopback = _is_loopback(client_ip)
    if not cfg.admin_remote and not loopback:
        raise HTTPException(status_code=403, detail="admin API is loopback-only")
    # Optional IP allowlist for remote admin (belt to the credential gate).
    # Loopback (the operator on the box) always bypasses it.
    allow = getattr(cfg, "admin_ip_allow", None) or []
    if cfg.admin_remote and allow and not loopback and not (client_ip and _ip_allowed(client_ip, allow)):
        raise HTTPException(status_code=403, detail="admin API: client IP not allowed")

    # Machine plane: bearer (short-lived JWT or the static token).
    secret = _admin_token()
    token = credentials.credentials if credentials else ""
    if token and secret and _authenticate(token, secret):
        return

    # Human plane: a valid native-UI session cookie (only when the UI is enabled).
    # Cookies are auto-sent, so unsafe methods must also carry the session's CSRF
    # token in a header — cross-site JS can't read it, which blocks forgery.
    if getattr(cfg, "native_ui", True):
        from . import admin_sessions

        sid = request.cookies.get(admin_sessions.COOKIE_NAME)
        if sid:
            idle = getattr(cfg, "admin_session_idle_min", 30) * 60
            sess = admin_sessions.get(sid, idle_seconds=idle)
            if sess is not None:
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    csrf = request.headers.get(admin_sessions.CSRF_HEADER, "")
                    if not csrf or not hmac.compare_digest(csrf, sess.csrf):
                        raise HTTPException(status_code=403, detail="missing or invalid CSRF token")
                return

    raise HTTPException(status_code=401, detail="missing or invalid admin credential")
