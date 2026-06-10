import pytest
from fastapi.testclient import TestClient

from agenthook import config, secrets, store
from agenthook.instances import Instance, save
from agenthook.server import create_app


@pytest.fixture
def client():
    cfg = config.load_config()
    cfg.use_docker = False
    config.save_config(cfg)
    # concurrency 0 keeps jobs queued so no real engine runs during tests
    inst = Instance(
        name="api",
        engine="claude",
        engine_auth="subscription",
        deliverable="analysis",
        webhook_auth={"schemes": ["bearer"]},
        limits={"concurrency": 0},
        allow_overrides=["deliverable", "mode"],
    )
    save(inst)
    secrets.generate_key(inst)
    secrets.get_backend(inst).set(inst, "AGENTHOOK_WEBHOOK_TOKEN", "tok", True)
    with TestClient(create_app()) as c:
        yield c


AUTH = {"Authorization": "Bearer tok"}


def test_health_and_ready(client):
    assert client.get("/healthz").json()["ok"] is True
    assert client.get("/readyz").status_code == 200


def test_auth_required(client):
    assert client.post("/hook/api", json={"prompt": "x"}).status_code == 401
    assert client.post("/hook/api", json={"prompt": "x"}, headers={"Authorization": "Bearer no"}).status_code == 401


def test_enqueue_and_get(client):
    r = client.post("/hook/api", json={"prompt": "hi", "thread_key": "t1"}, headers=AUTH)
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert r.json()["session_id"]
    assert client.get(f"/jobs/{jid}").json()["status"] in ("queued", "running")


def test_idempotency(client):
    h = {**AUTH, "Idempotency-Key": "idem-1"}
    a = client.post("/hook/api", json={"prompt": "x"}, headers=h).json()["job_id"]
    b = client.post("/hook/api", json={"prompt": "x"}, headers=h).json()["job_id"]
    assert a == b


def test_bad_deliverable_422(client):
    r = client.post("/hook/api", json={"prompt": "x", "deliverable": "bogus"}, headers=AUTH)
    assert r.status_code == 422


def test_session_routing(client):
    client.post("/hook/api", json={"prompt": "x", "thread_key": "ticket-9"}, headers=AUTH)
    sessions = store.list_sessions("api")
    assert any(s.thread_key == "ticket-9" for s in sessions)
    # explicit open-then-post
    r = client.post("/hook/api/sessions", json={"thread_key": "ticket-9"}, headers=AUTH)
    assert "post_url" in r.json()


def test_payload_too_large(client):
    big = {"prompt": "x" * (513 * 1024)}
    assert client.post("/hook/api", json=big, headers=AUTH).status_code == 413
