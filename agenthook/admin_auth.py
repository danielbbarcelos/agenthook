"""Management API protection (control-plane, ``/admin/*``).

The management surface exposes sensitive configuration (instances, secrets,
auth, guardrails), so it is guarded by two independent gates:

1. **Network** — by default it only answers loopback clients. Remote access is
   an explicit opt-in (``admin_remote: true`` in ``config.yaml``).
2. **Token** — a bearer token (``AGENTHOOK_ADMIN_TOKEN`` env, else the
   auto-generated ``config.admin_token``), compared in constant time.

Both must pass. Wire it as a router-wide dependency:
``APIRouter(dependencies=[Depends(require_admin)])``.
"""

from __future__ import annotations

import hmac
import ipaddress
import os

from fastapi import HTTPException, Request

from .config import load_config

_LOOPBACK_HOSTS = {"localhost", "testclient"}


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


def require_admin(request: Request) -> None:
    """FastAPI dependency: enforce the network + token gates for ``/admin/*``.

    Raises 403 from a disallowed network, 401 on a missing/invalid token.
    """
    cfg = load_config()
    client_ip = request.client.host if request.client else None
    if not cfg.admin_remote and not _is_loopback(client_ip):
        raise HTTPException(status_code=403, detail="admin API is loopback-only")

    expected = _admin_token()
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or not expected:
        raise HTTPException(status_code=401, detail="missing or invalid admin token")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="missing or invalid admin token")
