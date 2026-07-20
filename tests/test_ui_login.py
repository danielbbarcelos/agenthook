"""Native-UI login: session cookie + CSRF, TOTP, and the native_ui gate."""

import time

import pytest
from fastapi.testclient import TestClient

from agenthook import admin_sessions, admin_users, config
from agenthook.server import create_app


@pytest.fixture
def client():
    cfg = config.load_config()
    cfg.use_docker = False
    cfg.native_ui = True
    config.save_config(cfg)
    admin_users.create_user("boss", "pw")
    return TestClient(create_app())


def _login(c, **extra):
    return c.post("/ui/login", json={"username": "boss", "password": "pw", **extra})


def test_login_success_sets_session(client):
    r = _login(client)
    assert r.status_code == 200
    assert r.json()["username"] == "boss" and r.json()["csrf"]
    assert client.cookies.get(admin_sessions.COOKIE_NAME)


def test_login_wrong_password(client):
    assert client.post("/ui/login", json={"username": "boss", "password": "nope"}).status_code == 401


def test_session_endpoint_and_logout(client):
    assert client.get("/ui/session").status_code == 401
    _login(client)
    assert client.get("/ui/session").json()["username"] == "boss"
    client.post("/ui/logout")
    assert client.get("/ui/session").status_code == 401


def test_totp_required_then_ok(client):
    secret = admin_users.generate_totp_secret()
    admin_users.set_totp_secret("boss", secret)
    r = _login(client)
    assert r.status_code == 401 and r.json()["error"] == "totp_required"
    code = admin_users._totp(secret, int(time.time() // 30))
    assert _login(client, totp=code).status_code == 200


def test_admin_get_via_session(client):
    _login(client)
    assert client.get("/admin/ping").status_code == 200  # session authorizes a safe method


def test_admin_mutation_requires_csrf(client):
    csrf = _login(client).json()["csrf"]
    body = {"name": "viasession", "repos": [{"url": "git@github.com:me/app.git"}]}
    # cookie present but no CSRF header -> forbidden
    assert client.post("/admin/instances", json=body).status_code == 403
    # with the CSRF header -> created
    assert client.post("/admin/instances", headers={"X-Agenthook-CSRF": csrf}, json=body).status_code == 201


def test_native_ui_disabled(client):
    # rebuild with native_ui off: login route gone, session cookies not honored
    cfg = config.load_config()
    cfg.native_ui = False
    config.save_config(cfg)
    c = TestClient(create_app())
    assert c.post("/ui/login", json={"username": "boss", "password": "pw"}).status_code == 404
    sess = admin_sessions.create("boss", idle_seconds=600)
    c.cookies.set(admin_sessions.COOKIE_NAME, sess.id)
    assert c.get("/admin/ping").status_code == 401
