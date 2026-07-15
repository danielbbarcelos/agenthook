"""M1 hardening: read-only tool lockdown, plan->apply coercion, approval
two-step (GET confirm / POST decide), and webhook rate limiting."""

import pytest
from fastapi.testclient import TestClient

from agenthook import approval, config, ratelimit, secrets, store
from agenthook.engines import get_engine
from agenthook.instances import Instance, save
from agenthook.models import Deliverable, Job, JobStatus, Mode
from agenthook.runner import _build_runspec
from agenthook.server import _resolve_params, create_app


# --- 1. read-only tool lockdown (Bash closed + enumerated allowlist) --------


def test_read_only_disallows_bash():
    eng = get_engine("claude")
    assert "Bash" in eng.read_only_disallowed_tools()
    assert set(["Read", "Grep", "Glob"]).issubset(set(eng.read_only_allowed_tools()))


def test_build_runspec_read_only_locks_bash_and_allowlists():
    eng = get_engine("claude")
    inst = Instance(name="ro", engine="claude", deliverable="analysis")
    job = Job(instance="ro", deliverable=Deliverable.ANALYSIS, mode=Mode.DEFAULT, prompt="x")
    argv = _build_runspec(inst, eng, job, "x", None, sandbox=True)
    joined = " ".join(argv)
    assert "--disallowedTools" in joined
    # the disallowed arg is the token right after the flag
    disallowed = argv[argv.index("--disallowedTools") + 1]
    assert "Bash" in disallowed
    allowed = argv[argv.index("--allowedTools") + 1]
    assert "Read" in allowed


# --- 2. plan->apply coercion for code-mutating deliverables -----------------


def test_mutating_deliverable_coerced_to_plan():
    inst = Instance(name="pr", engine="claude", deliverable="pr")
    deliverable, mode, err = _resolve_params(inst, {})
    assert err is None
    assert deliverable is Deliverable.PR
    assert mode is Mode.PLAN  # coerced away from the auto-applying default


def test_auto_apply_opt_in_keeps_auto():
    inst = Instance(
        name="pr2",
        engine="claude",
        deliverable="pr",
        allow_auto_apply=True,
        allow_overrides=["mode"],
    )
    _, mode, err = _resolve_params(inst, {"overrides": {"mode": "auto"}})
    assert err is None
    assert mode is Mode.AUTO


def test_analysis_not_coerced():
    inst = Instance(name="an", engine="claude", deliverable="analysis")
    deliverable, mode, err = _resolve_params(inst, {})
    assert err is None and deliverable is Deliverable.ANALYSIS


def test_mutating_without_plan_capable_engine_errors():
    # codex has no plan_mode; a mutating deliverable can't be safely coerced.
    if "codex" not in __import__("agenthook.engines", fromlist=["available"]).available():
        pytest.skip("codex engine not available")
    inst = Instance(name="cx", engine="codex", deliverable="pr")
    _, _, err = _resolve_params(inst, {})
    assert err is not None


# --- 3 & 4. approval two-step and rate limiting (HTTP) ----------------------


@pytest.fixture
def client():
    ratelimit.reset()
    cfg = config.load_config()
    cfg.use_docker = False
    config.save_config(cfg)
    inst = Instance(
        name="api",
        engine="claude",
        engine_auth="subscription",
        deliverable="analysis",
        webhook_auth={"schemes": ["bearer"]},
        limits={"concurrency": 0},
    )
    save(inst)
    secrets.generate_key(inst)
    secrets.get_backend(inst).set(inst, "AGENTHOOK_WEBHOOK_TOKEN", "tok", True)
    with TestClient(create_app()) as c:
        yield c


def _awaiting_job() -> str:
    job = Job(instance="api", deliverable=Deliverable.PR, mode=Mode.PLAN, prompt="plan")
    job.status = JobStatus.AWAITING_APPROVAL
    store.create_job(job)
    return job.id


def test_approve_get_is_confirm_page_not_decision(client):
    jid = _awaiting_job()
    cfg = config.load_config()
    tok = approval.make_token(cfg.approval_secret, jid, "approve", 600)
    r = client.get(f"/jobs/{jid}/approve?token={tok}")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # GET did NOT change state
    assert store.get_job(jid).status is JobStatus.AWAITING_APPROVAL


def test_approve_post_decides(client):
    jid = _awaiting_job()
    cfg = config.load_config()
    tok = approval.make_token(cfg.approval_secret, jid, "approve", 600)
    r = client.post(f"/jobs/{jid}/approve", data={"token": tok})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_approve_post_bad_token_403(client):
    jid = _awaiting_job()
    r = client.post(f"/jobs/{jid}/approve", data={"token": "0.deadbeef"})
    assert r.status_code == 403
    assert store.get_job(jid).status is JobStatus.AWAITING_APPROVAL


def test_webhook_rate_limited(client):
    ratelimit.reset()
    # tighten the per-instance budget for this instance
    inst = __import__("agenthook.instances", fromlist=["load"]).load("api")
    inst.limits["rate"] = {"rpm": 1, "burst": 2}
    save(inst)
    auth = {"Authorization": "Bearer tok"}
    codes = [
        client.post("/hook/api", json={"prompt": "x"}, headers=auth).status_code
        for _ in range(4)
    ]
    assert 429 in codes  # bucket of 2 is exhausted within 4 rapid requests
    assert codes[0] == 202  # first one gets through
