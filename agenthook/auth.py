"""Webhook endpoint protection (DESIGN.md §12).

An instance's ``webhook_auth`` selects one or more schemes (all must pass):
``bearer``, ``header``, ``hmac``, ``ip-allow``. Secrets/tokens are read from the
instance's encrypted env (reserved variable names by default).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress

from .instances import Instance
from .secrets import get_backend

DEFAULTS = {
    "token_env": "AGENTHOOK_WEBHOOK_TOKEN",
    "secret_env": "AGENTHOOK_WEBHOOK_SECRET",
    "header_value_env": "AGENTHOOK_HEADER_VALUE",
}


def _secret(inst: Instance, key: str) -> str | None:
    try:
        return get_backend(inst).get(inst, key)
    except Exception:
        return None


def check_auth(
    inst: Instance, headers: dict[str, str], body: bytes, client_ip: str | None
) -> tuple[bool, str]:
    """Return (ok, reason). ``reason`` is safe to log but not leaked verbatim."""
    cfg = inst.webhook_auth or {}
    schemes = cfg.get("schemes") or ([cfg["scheme"]] if cfg.get("scheme") else [])
    if not schemes:
        return True, "open"  # no auth configured

    headers = {k.lower(): v for k, v in headers.items()}

    for scheme in schemes:
        ok, reason = _check_one(scheme, inst, cfg, headers, body, client_ip)
        if not ok:
            return False, reason
    return True, "ok"


def _check_one(scheme, inst, cfg, headers, body, client_ip) -> tuple[bool, str]:
    if scheme == "bearer":
        token = _secret(inst, cfg.get("token_env", DEFAULTS["token_env"]))
        got = headers.get("authorization", "")
        if got.startswith("Bearer "):
            got = got[len("Bearer "):]
        if token and hmac.compare_digest(got, token):
            return True, "bearer ok"
        return False, "bearer mismatch"

    if scheme == "header":
        name = (cfg.get("header_name") or "X-API-Key").lower()
        value = _secret(inst, cfg.get("header_value_env", DEFAULTS["header_value_env"]))
        if value and hmac.compare_digest(headers.get(name, ""), value):
            return True, "header ok"
        return False, "header mismatch"

    if scheme == "hmac":
        secret = _secret(inst, cfg.get("secret_env", DEFAULTS["secret_env"]))
        sig = headers.get("x-agenthook-signature", "")
        if secret:
            expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(sig, expected):
                return True, "hmac ok"
        return False, "hmac mismatch"

    if scheme == "ip-allow":
        allow = cfg.get("ip_allow") or []
        if client_ip and _ip_allowed(client_ip, allow):
            return True, "ip ok"
        return False, "ip not allowed"

    return False, f"unknown scheme {scheme}"


def _ip_allowed(ip: str, cidrs: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
