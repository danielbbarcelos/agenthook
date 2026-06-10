from agenthook import store
from agenthook.models import Deliverable, Job, JobStatus, Usage


def _job(**kw):
    return Job(instance="demo", **kw)


def test_job_roundtrip_and_idempotency(instance):
    job = _job(prompt="hi", deliverable=Deliverable.PR, idempotency_key="k1")
    job.usage = Usage(cost_usd=0.5)
    store.create_job(job)
    loaded = store.get_job(job.id)
    assert loaded.prompt == "hi"
    assert loaded.deliverable is Deliverable.PR
    assert loaded.usage.cost_usd == 0.5
    assert store.find_by_idempotency("demo", "k1").id == job.id


def test_session_find_or_create(instance):
    s1 = store.find_or_create_session("demo", "ticket-1")
    s2 = store.find_or_create_session("demo", "ticket-1")
    assert s1.id == s2.id
    s3 = store.find_or_create_session("demo", "ticket-2")
    assert s3.id != s1.id


def test_claim_job_is_atomic(instance):
    job = _job()
    store.create_job(job)
    assert store.claim_job(job.id) is True
    assert store.claim_job(job.id) is False  # already running


def test_recovery_readonly_vs_code(instance):
    ro = _job(deliverable=Deliverable.ANALYSIS, status=JobStatus.RUNNING)
    code = _job(deliverable=Deliverable.PR, status=JobStatus.RUNNING)
    store.create_job(ro)
    store.create_job(code)
    res = store.recover_interrupted()
    assert res == {"requeued": 1, "interrupted": 1}
    assert store.get_job(ro.id).status is JobStatus.QUEUED
    assert store.get_job(code.id).status is JobStatus.INTERRUPTED


def test_audit_and_usage(instance):
    job = _job(deliverable=Deliverable.ANALYSIS, status=JobStatus.SUCCESS)
    job.usage = Usage(cost_usd=0.25)
    job.request = {"requester": {"name": "Daniel"}, "request_type": "ticket"}
    store.create_job(job)
    store.record_audit(job)
    assert store.usage_summary(instance="demo") == {"jobs": 1, "cost_usd": 0.25}
    assert store.usage_summary(requester="Daniel")["jobs"] == 1
    assert len(store.audit_rows(instance="demo")) == 1
