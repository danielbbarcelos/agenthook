"""Optional SMTP email recovery: mailer, reset tokens, /ui/recover[/confirm]."""

import re
import time

import pytest
from fastapi.testclient import TestClient

from agenthook import admin_users, config, mailer
from agenthook.server import create_app


# --- mailer -----------------------------------------------------------------


def test_mailer_unconfigured_raises():
    cfg = config.load_config()  # no smtp_* set
    assert not mailer.is_configured(cfg)
    with pytest.raises(RuntimeError):
        mailer.send("a@b", "s", "body", cfg=cfg)


def test_mailer_builds_message(monkeypatch):
    cfg = config.load_config()
    cfg.smtp_host = "smtp.test"
    cfg.smtp_from = "bot@test"
    cfg.smtp_starttls = False
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            captured["host"], captured["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    mailer.send("to@x", "Subj", "Body", cfg=cfg)
    assert captured["host"] == "smtp.test"
    assert captured["msg"]["To"] == "to@x" and captured["msg"]["Subject"] == "Subj"


# --- reset tokens -----------------------------------------------------------


def test_reset_token_single_use_and_expiry():
    admin_users.create_user("u", "pw")
    t = admin_users.create_reset_token("u", ttl_seconds=900)
    assert admin_users.consume_reset_token(t) == "u"
    assert admin_users.consume_reset_token(t) is None  # single-use
    t2 = admin_users.create_reset_token("u", ttl_seconds=900)
    assert admin_users.consume_reset_token(t2, now=time.time() + 1000) is None  # expired


# --- recover endpoints ------------------------------------------------------


@pytest.fixture
def smtp_client(monkeypatch):
    cfg = config.load_config()
    cfg.use_docker = False
    cfg.native_ui = True
    cfg.smtp_host = "smtp.test"
    cfg.smtp_from = "bot@test"
    config.save_config(cfg)
    admin_users.create_user("boss", "old-pw", "boss@example.com")
    sent: list = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, body, cfg=None: sent.append((to, subject, body)))
    return TestClient(create_app()), sent


def _token(body: str) -> str:
    return re.search(r"Token: (\S+)", body).group(1)


def test_recover_sends_and_confirm_resets(smtp_client):
    c, sent = smtp_client
    assert c.post("/ui/recover", json={"username": "boss"}).status_code == 200
    assert len(sent) == 1 and sent[0][0] == "boss@example.com"
    r = c.post("/ui/recover/confirm", json={"token": _token(sent[0][2]), "password": "new-pw"})
    assert r.status_code == 200
    assert admin_users.authenticate("boss", "new-pw")
    assert not admin_users.authenticate("boss", "old-pw")


def test_recover_no_user_enumeration(smtp_client):
    c, sent = smtp_client
    assert c.post("/ui/recover", json={"username": "ghost"}).status_code == 200
    assert sent == []  # no mail for an unknown user, but still a 200


def test_confirm_bad_token(smtp_client):
    c, _ = smtp_client
    assert c.post("/ui/recover/confirm", json={"token": "nope", "password": "x"}).status_code == 400
    assert c.post("/ui/recover/confirm", json={"token": "", "password": ""}).status_code == 400


def test_confirm_revokes_sessions(smtp_client):
    c, sent = smtp_client
    c.post("/ui/login", json={"username": "boss", "password": "old-pw"})
    assert c.get("/ui/session").status_code == 200
    c.post("/ui/recover", json={"username": "boss"})
    c.post("/ui/recover/confirm", json={"token": _token(sent[0][2]), "password": "new-pw"})
    assert c.get("/ui/session").status_code == 401  # the reset revoked the session
