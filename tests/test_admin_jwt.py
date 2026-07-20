"""Admin credential gate: short-lived HS256 JWT (jti anti-replay) + IP-allow,
alongside the legacy static token. Covers admin_auth.require_admin via /admin/ping.
"""

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from agenthook import admin_auth, config
from agenthook.server import create_app


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _mint(secret: str, *, exp=None, exp_in=120, jti="j1", include_jti=True, alg="HS256") -> str:
    header = {"alg": alg, "typ": "JWT"}
    payload = {"exp": exp if exp is not None else time.time() + exp_in}
    if include_jti:
        payload["jti"] = jti
    seg = _b64u(json.dumps(header).encode()) + "." + _b64u(json.dumps(payload).encode())
    sig = hmac.new(secret.encode(), seg.encode(), hashlib.sha256).digest()
    return seg + "." + _b64u(sig)


@pytest.fixture
def secret():
    cfg = config.load_config()
    cfg.use_docker = False
    cfg.admin_remote = False
    cfg.admin_ip_allow = []
    config.save_config(cfg)
    admin_auth._SEEN_JTI.clear()
    return cfg.admin_token


def _ping(c, tok):
    return c.get("/admin/ping", headers={"Authorization": f"Bearer {tok}"})


# --- static token (regression) ----------------------------------------------


def test_static_token_still_works(secret):
    with TestClient(create_app()) as c:
        assert _ping(c, secret).status_code == 200


def test_no_credential_401(secret):
    with TestClient(create_app()) as c:
        assert c.get("/admin/ping").status_code == 401


# --- short-lived JWT --------------------------------------------------------


def test_valid_jwt_accepted(secret):
    with TestClient(create_app()) as c:
        assert _ping(c, _mint(secret, jti="ok")).status_code == 200


def test_jwt_wrong_secret_rejected(secret):
    with TestClient(create_app()) as c:
        assert _ping(c, _mint("not-the-secret", jti="x")).status_code == 401


def test_jwt_expired_rejected(secret):
    with TestClient(create_app()) as c:
        assert _ping(c, _mint(secret, exp=time.time() - 1, jti="old")).status_code == 401


def test_jwt_ttl_too_long_rejected(secret):
    # exp far in the future defeats the point of short-lived tokens — capped.
    with TestClient(create_app()) as c:
        assert _ping(c, _mint(secret, exp_in=3600, jti="long")).status_code == 401


def test_jwt_without_jti_rejected(secret):
    # jti is mandatory: without it we can't guarantee anti-replay.
    with TestClient(create_app()) as c:
        assert _ping(c, _mint(secret, include_jti=False)).status_code == 401


def test_jwt_replay_rejected(secret):
    with TestClient(create_app()) as c:
        tok = _mint(secret, jti="once")
        assert _ping(c, tok).status_code == 200
        assert _ping(c, tok).status_code == 401  # same jti replayed


def test_jwt_wrong_alg_rejected(secret):
    with TestClient(create_app()) as c:
        assert _ping(c, _mint(secret, jti="alg", alg="none")).status_code == 401


# --- IP allowlist for remote admin ------------------------------------------


def test_ip_allow_permits_and_blocks(secret):
    cfg = config.load_config()
    cfg.admin_remote = True
    cfg.admin_ip_allow = ["203.0.113.0/24"]
    config.save_config(cfg)
    with TestClient(create_app(), client=("203.0.113.5", 9000)) as c:
        assert c.get("/admin/ping", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
    with TestClient(create_app(), client=("198.51.100.7", 9000)) as c:
        assert c.get("/admin/ping", headers={"Authorization": f"Bearer {secret}"}).status_code == 403


def test_ip_allow_loopback_bypass(secret):
    cfg = config.load_config()
    cfg.admin_remote = True
    cfg.admin_ip_allow = ["203.0.113.0/24"]
    config.save_config(cfg)
    with TestClient(create_app()) as c:  # loopback client bypasses the allowlist
        assert _ping(c, secret).status_code == 200
