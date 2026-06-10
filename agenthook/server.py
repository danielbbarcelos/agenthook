"""FastAPI webhook server (DESIGN.md §10, §12, §19, §29, §31).

Exposes the per-instance webhook, session routing, job status/SSE logs, signed
approval endpoints and infra endpoints. Inbound requests are persisted before
they are acked (durability) and deduplicated by ``Idempotency-Key``.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from . import approval, auth, instances, store
from .config import load_config
from .engines import get_engine
from .models import Deliverable, Job, JobStatus, Mode
from .worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    worker = Worker(max_parallel=max(1, load_config().default_concurrency * 4))
    worker.start()
    from .scheduler import Scheduler

    scheduler = Scheduler(worker)
    scheduler.start()
    app.state.worker = worker
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.stop()
        worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="agenthook", lifespan=lifespan)

    # ---- infra ----------------------------------------------------------

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        ready = True
        detail = {}
        try:
            instances.list_names()
            detail["instances"] = True
        except Exception as exc:  # noqa: BLE001
            ready = False
            detail["instances"] = str(exc)
        return JSONResponse({"ready": ready, **detail}, status_code=200 if ready else 503)

    @app.get("/metrics")
    async def metrics():
        lines = ["# agenthook metrics"]
        for st in JobStatus:
            n = len(store.list_jobs(status=st.value, limit=100000))
            lines.append(f'agenthook_jobs{{status="{st.value}"}} {n}')
        return PlainTextResponse("\n".join(lines) + "\n")

    # ---- webhook --------------------------------------------------------

    @app.post("/hook/{name}")
    async def hook(name: str, request: Request):
        return await _handle_hook(app, name, request, session_id=None)

    @app.post("/hook/{name}/sessions")
    async def open_session(name: str, request: Request):
        inst, body, err = await _authed_instance(name, request)
        if err:
            return err
        payload = _json(body)
        thread_key = payload.get("thread_key") or f"adhoc-{int(time.time()*1000)}"
        sess = store.find_or_create_session(name, thread_key)
        base = str(request.base_url).rstrip("/")
        return {
            "session_id": sess.id,
            "thread_key": sess.thread_key,
            "post_url": f"{base}/hook/{name}/sessions/{sess.id}",
        }

    @app.post("/hook/{name}/sessions/{session_id}")
    async def hook_session(name: str, session_id: str, request: Request):
        return await _handle_hook(app, name, request, session_id=session_id)

    # ---- jobs -----------------------------------------------------------

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            return JSONResponse({"error": "not found"}, status_code=404)
        return _job_view(job)

    @app.get("/jobs/{job_id}/stream")
    async def stream_job(job_id: str):
        job = store.get_job(job_id)
        if not job:
            return JSONResponse({"error": "not found"}, status_code=404)
        return StreamingResponse(_log_stream(job_id), media_type="text/event-stream")

    @app.post("/jobs/{job_id}/approve")
    async def approve(job_id: str, token: str):
        return _decide(app, job_id, "approve", token)

    @app.post("/jobs/{job_id}/reject")
    async def reject(job_id: str, token: str):
        return _decide(app, job_id, "reject", token)

    return app


# --- request handling -------------------------------------------------------


async def _authed_instance(name: str, request: Request):
    try:
        inst = instances.load(name)
    except Exception:
        return None, b"", JSONResponse({"error": "instance not found"}, status_code=404)
    body = await request.body()
    cfg = load_config()
    if len(body) > cfg.payload_max_kb * 1024:
        return None, body, JSONResponse({"error": "payload too large"}, status_code=413)
    client_ip = request.client.host if request.client else None
    ok, reason = auth.check_auth(inst, dict(request.headers), body, client_ip)
    if not ok:
        return None, body, JSONResponse({"error": "unauthorized"}, status_code=401)
    if inst.paused:
        return None, body, JSONResponse(
            {"error": "instance paused", "reason": inst.paused_reason}, status_code=409
        )
    return inst, body, None


async def _handle_hook(app: FastAPI, name: str, request: Request, session_id: str | None):
    inst, body, err = await _authed_instance(name, request)
    if err:
        return err
    payload = _json(body)

    # Idempotency.
    idem = request.headers.get("idempotency-key")
    if idem:
        existing = store.find_by_idempotency(name, idem)
        if existing:
            return JSONResponse(_ack(existing, request), status_code=200)

    # Resolve deliverable/mode honoring the override whitelist.
    deliverable, mode, perr = _resolve_params(inst, payload)
    if perr:
        return JSONResponse({"error": perr}, status_code=422)

    # Validate the per-job repo selection against the declared pool (§2).
    if "repos" in payload:
        from .instances import InstanceError

        try:
            inst.select_repos(payload.get("repos"))
        except InstanceError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    # Session: explicit id, or find-or-create by thread_key.
    sess = None
    thread_key = payload.get("thread_key")
    if session_id:
        sess = store.get_session(session_id)
        if not sess:
            return JSONResponse({"error": "session not found"}, status_code=404)
        thread_key = sess.thread_key
    elif thread_key:
        sess = store.find_or_create_session(name, thread_key)

    job = Job(
        instance=name,
        deliverable=deliverable,
        mode=mode,
        prompt=payload.get("prompt", ""),
        request=payload,
        thread_key=thread_key,
        session_id=sess.id if sess else None,
        idempotency_key=idem,
    )
    # Persist-before-ack (durability, §31).
    store.create_job(job)
    app.state.worker.notify()

    if request.query_params.get("wait") in ("1", "true", "yes"):
        job = await _wait_for(job.id, timeout=float(request.query_params.get("timeout", 300)))
    return JSONResponse(_ack(job, request), status_code=202)


def _resolve_params(inst, payload):
    allow = set(inst.allow_overrides or [])
    deliverable_val = inst.deliverable
    if "deliverable" in payload and "deliverable" in allow:
        deliverable_val = payload["deliverable"]
    overrides = payload.get("overrides") or {}
    mode_val = inst.default_mode
    if "mode" in overrides and "mode" in allow:
        mode_val = overrides["mode"]

    try:
        deliverable = Deliverable(deliverable_val)
        mode = Mode(mode_val)
    except ValueError as exc:
        return None, None, f"invalid params: {exc}"

    # Capability validation (§16).
    engine = get_engine(inst.engine)
    if mode is Mode.PLAN and not engine.capabilities.plan_mode:
        return None, None, f"engine {inst.engine!r} does not support plan mode"
    return deliverable, mode, None


def _decide(app: FastAPI, job_id: str, action: str, token: str):
    cfg = load_config()
    if not approval.verify_token(cfg.approval_secret, job_id, action, token):
        return JSONResponse({"error": "invalid or expired token"}, status_code=403)
    job = store.get_job(job_id)
    if not job or job.status is not JobStatus.AWAITING_APPROVAL:
        return JSONResponse({"error": "job not awaiting approval"}, status_code=409)

    if action == "reject":
        job.status = JobStatus.REJECTED
        store.save_job(job)
        return {"job_id": job_id, "status": "rejected"}

    # Approve: spawn an apply job that resumes the plan with mode=auto.
    job.status = JobStatus.SUCCESS
    store.save_job(job)
    apply_job = Job(
        instance=job.instance,
        deliverable=job.deliverable,
        mode=Mode.AUTO,
        prompt=job.prompt or "Apply the approved plan.",
        request=job.request,
        thread_key=job.thread_key,
        session_id=job.session_id,
        metadata={"approved_from": job.id},
    )
    store.create_job(apply_job)
    app.state.worker.notify()
    return {"job_id": job_id, "status": "approved", "apply_job_id": apply_job.id}


# --- helpers ----------------------------------------------------------------


def _json(body: bytes) -> dict:
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {}


def _ack(job: Job, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {
        "job_id": job.id,
        "status": job.status.value,
        "session_id": job.session_id,
        "stream_url": f"{base}/jobs/{job.id}/stream",
    }


def _job_view(job: Job) -> dict:
    return {
        "job_id": job.id,
        "instance": job.instance,
        "status": job.status.value,
        "deliverable": job.deliverable.value,
        "mode": job.mode.value,
        "session_id": job.session_id,
        "thread_key": job.thread_key,
        "error_class": job.error_class,
        "error_message": job.error_message,
        "pr_url": job.pr_url,
        "result": job.result.text if job.result else None,
        "usage": job.usage.to_dict(),
        "attempts": job.attempts,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


async def _wait_for(job_id: str, timeout: float) -> Job:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = store.get_job(job_id)
        if job and job.status.terminal:
            return job
        await asyncio.sleep(0.5)
    return store.get_job(job_id)


async def _log_stream(job_id: str):
    from . import paths

    job = store.get_job(job_id)
    if not job:
        return
    path = paths.job_log(job.instance, job_id)
    pos = 0
    for _ in range(1200):  # ~10 min cap
        if path.exists():
            with path.open() as fh:
                fh.seek(pos)
                for line in fh:
                    yield f"data: {line.rstrip()}\n\n"
                pos = fh.tell()
        job = store.get_job(job_id)
        if job and job.status.terminal:
            yield f"event: done\ndata: {job.status.value}\n\n"
            return
        await asyncio.sleep(0.5)


app = create_app()
