"""GitHub App installation tokens — short-lived, per-job git credentials.

A static ``GH_TOKEN`` is a standing push credential: it lives in the env for the
whole job and, being long-lived, is a fat target if exfiltrated. A GitHub App
installation token instead is minted per job, host-side, expires in ~1h, and is
scoped to the job's repositories — so even a leak is small and self-healing.

The App's private key never leaves the host: it is stored as a control-plane
secret (reserved ``AGENTHOOK_GH_APP_*`` namespace, invisible to the agent), and
minting happens in the runner's host process, never in the container. git/PR
operations are host-side already, so the container needs no git token at all.

Only stdlib + ``cryptography`` (already a dependency for Fernet) — no PyJWT.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"

# (app_id, installation_id) -> (token, expires_epoch)
_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_CACHE_LOCK = threading.Lock()
_REFRESH_SKEW_S = 300  # refresh 5 min before expiry


@dataclass
class AppConfig:
    app_id: str
    installation_id: str
    private_key_pem: str

    @classmethod
    def from_secrets(cls, get) -> "AppConfig | None":
        """Build from a ``get(name)`` accessor over control-plane secrets, or
        None if the App isn't fully configured."""
        app_id = get("AGENTHOOK_GH_APP_ID")
        inst_id = get("AGENTHOOK_GH_APP_INSTALLATION_ID")
        key = get("AGENTHOOK_GH_APP_PRIVATE_KEY")
        if app_id and inst_id and key:
            return cls(str(app_id), str(inst_id), str(key))
        return None


def _b64url(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def _app_jwt(app_id: str, private_key_pem: str, now: int) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": "RS256", "typ": "JWT"}
    # iat backdated 60s for clock skew; GitHub caps exp at 10 min.
    payload = {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + b"."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + _b64url(sig)).decode()


def _parse_expiry(s: str | None) -> float:
    if not s:
        return time.time() + 3600
    try:
        from datetime import datetime

        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except Exception:  # noqa: BLE001
        return time.time() + 3600


def mint(
    cfg: AppConfig,
    *,
    repositories: list[str] | None = None,
    permissions: dict | None = None,
    api: str = API,
    now: int | None = None,
) -> tuple[str, float]:
    """Mint an installation token. Returns ``(token, expires_epoch)``. Cached per
    (app, installation) until shortly before expiry (repo/permission scoping
    bypasses the cache since it narrows the token)."""
    now = int(time.time()) if now is None else now
    cache_key = (cfg.app_id, cfg.installation_id)
    scoped = bool(repositories or permissions)
    if not scoped:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and hit[1] - _REFRESH_SKEW_S > now:
                return hit

    jwt = _app_jwt(cfg.app_id, cfg.private_key_pem, now)
    body: dict = {}
    if repositories:
        body["repositories"] = repositories
    if permissions:
        body["permissions"] = permissions
    data = json.dumps(body).encode() if body else b"{}"
    req = urllib.request.Request(
        f"{api}/app/installations/{cfg.installation_id}/access_tokens",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310
        resp = json.load(r)
    token = resp["token"]
    exp = _parse_expiry(resp.get("expires_at"))
    if not scoped:
        with _CACHE_LOCK:
            _CACHE[cache_key] = (token, exp)
    return token, exp


def revoke(token: str, *, api: str = API) -> None:
    """Best-effort revocation of an installation token (DELETE /installation/token)."""
    req = urllib.request.Request(
        f"{api}/installation/token",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)  # noqa: S310
    except Exception:  # noqa: BLE001
        pass


def auth_extraheader(token: str) -> str:
    """The ``http.<host>.extraheader`` value that authenticates git over HTTPS
    with an installation token (username ``x-access-token``)."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {basic}"
