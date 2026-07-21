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
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse

from . import approval, auth, instances, ratelimit, store
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

    # ---- management API (control-plane, /admin/*) -----------------------
    from .admin_api import router as admin_router

    app.include_router(admin_router)

    # ---- native UI (human plane): login routes + panel, gated by config --
    if load_config().native_ui:
        _register_ui_auth(app)
        _mount_panel(app)

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
        cfg = load_config()
        if cfg.use_docker and getattr(cfg, "egress_enabled", False):
            # Informational: the broker is brought up lazily per job, so a "down"
            # here isn't fatal — it just means no job has needed it yet.
            detail["egress_broker"] = _broker_healthy(cfg.egress_ctrl_port)
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

    # Approval is a two-step: a chat "Approve" button is a URL (browser GET), so
    # GET renders a confirm page and the actual state change happens on POST. This
    # keeps a link prefetch / Referer leak from silently approving a job, and
    # keeps the token out of the acting request's URL (it rides the POST body).
    @app.get("/jobs/{job_id}/approve")
    async def approve_confirm(job_id: str, token: str = ""):
        return _confirm_page(job_id, "approve", token)

    @app.get("/jobs/{job_id}/reject")
    async def reject_confirm(job_id: str, token: str = ""):
        return _confirm_page(job_id, "reject", token)

    @app.post("/jobs/{job_id}/approve")
    async def approve(job_id: str, request: Request):
        return _decide(app, job_id, "approve", await _decision_token(request), request)

    @app.post("/jobs/{job_id}/reject")
    async def reject(job_id: str, request: Request):
        return _decide(app, job_id, "reject", await _decision_token(request), request)

    return app


def _register_ui_auth(app: FastAPI) -> None:
    """Native-UI human login: password (+ TOTP) → server-side session cookie with
    a CSRF token. Registered only when ``config.native_ui`` is on. The machine
    plane (Workspace/API) does not use these — it authenticates via bearer."""
    from . import admin_sessions, admin_users, ratelimit

    @app.post("/ui/login")
    async def ui_login(request: Request):
        ip = request.client.host if request.client else "?"
        ok, retry = ratelimit.check(f"login:{ip}", ratelimit.Limit(10, 5))
        if not ok:
            return _rate_limited(retry)
        payload = _json(await request.body())
        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
        totp = payload.get("totp")
        if not admin_users.authenticate(username, password, totp):
            u = admin_users.get_user(username)
            if u and u.totp_enabled and not totp and admin_users.verify_password(password, u.pw_hash):
                return JSONResponse({"error": "totp_required"}, status_code=401)
            return JSONResponse({"error": "invalid credentials"}, status_code=401)
        cfg = load_config()
        idle = cfg.admin_session_idle_min * 60
        sess = admin_sessions.create(username, idle_seconds=idle)
        resp = JSONResponse({"username": username, "csrf": sess.csrf})
        resp.set_cookie(
            admin_sessions.COOKIE_NAME, sess.id, max_age=idle, path="/",
            httponly=True, samesite="strict", secure=(request.url.scheme == "https"),
        )
        return resp

    @app.post("/ui/logout")
    async def ui_logout(request: Request):
        sid = request.cookies.get(admin_sessions.COOKIE_NAME)
        if sid:
            admin_sessions.delete(sid)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(admin_sessions.COOKIE_NAME, path="/")
        return resp

    @app.get("/ui/session")
    async def ui_session(request: Request):
        cfg = load_config()
        sid = request.cookies.get(admin_sessions.COOKIE_NAME)
        sess = admin_sessions.get(sid, idle_seconds=cfg.admin_session_idle_min * 60) if sid else None
        if sess is None:
            return JSONResponse({"authenticated": False}, status_code=401)
        return {"authenticated": True, "username": sess.username, "csrf": sess.csrf}

    @app.post("/ui/recover")
    async def ui_recover(request: Request):
        ip = request.client.host if request.client else "?"
        ok, retry = ratelimit.check(f"recover:{ip}", ratelimit.Limit(5, 3))
        if not ok:
            return _rate_limited(retry)
        username = str(_json(await request.body()).get("username", ""))
        cfg = load_config()
        # Best-effort and constant-shape: never reveal whether the user/email/SMTP
        # exists. Emails only when SMTP is configured and the user has an address.
        try:
            from . import mailer

            u = admin_users.get_user(username)
            if u and u.email and mailer.is_configured(cfg):
                token = admin_users.create_reset_token(username)
                link = f"{cfg.public_base_url.rstrip('/')}/ui/#reset?token={token}"
                mailer.send(
                    u.email,
                    "agenthook password reset",
                    f"Reset your password (valid 15 min):\n{link}\n\nToken: {token}",
                    cfg=cfg,
                )
        except Exception:  # noqa: BLE001 - never leak send/lookup failures
            pass
        return JSONResponse({"ok": True})

    @app.post("/ui/recover/confirm")
    async def ui_recover_confirm(request: Request):
        payload = _json(await request.body())
        token = str(payload.get("token", ""))
        password = str(payload.get("password", ""))
        if not token or not password:
            return JSONResponse({"error": "token and password required"}, status_code=400)
        username = admin_users.consume_reset_token(token)
        if not username:
            return JSONResponse({"error": "invalid or expired token"}, status_code=400)
        admin_users.set_password(username, password)
        admin_sessions.delete_for_user(username)  # a reset revokes existing sessions
        return JSONResponse({"ok": True})


def _mount_panel(app: FastAPI) -> None:
    """Serve the built React panel at ``/ui`` when present.

    The build is produced by ``web/`` into ``agenthook/static/panel`` (inside the
    package, so it ships in the wheel). Mounting at ``/ui`` keeps it same-origin
    with ``/admin`` — no CORS — while leaving the API routes (registered above)
    untouched, since those take precedence over the mount. ``html=True`` lets the
    SPA's hash routes resolve to ``index.html``.
    """
    from pathlib import Path

    panel = Path(__file__).parent / "static" / "panel"
    if (panel / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/ui", StaticFiles(directory=str(panel), html=True), name="panel")


# --- request handling -------------------------------------------------------


def _broker_healthy(ctrl_port: int) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{ctrl_port}/healthz", timeout=1) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _rate_limited(retry_after: int) -> JSONResponse:
    return JSONResponse(
        {"error": "rate limited", "retry_after": retry_after},
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )


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
    ip_key = client_ip or "unknown"

    # Tier A: pre-auth per-IP flood guard — throttle credential-stuffing before
    # spending HMAC/secret work on the request.
    okA, retryA = ratelimit.check(
        f"ip:{ip_key}", ratelimit.Limit(cfg.webhook_ip_rpm, cfg.webhook_ip_rpm)
    )
    if not okA:
        return None, body, _rate_limited(retryA)

    ok, reason = auth.check_auth(inst, dict(request.headers), body, client_ip)
    if not ok:
        return None, body, JSONResponse({"error": "unauthorized"}, status_code=401)

    # Tier B: per-(instance, ip) budget — after auth, so a legit high-volume
    # integration and an attacker are distinguished by instance. Override via
    # ``instance.limits.rate`` = {rpm, burst}.
    rate = inst.limits.get("rate") if isinstance(inst.limits, dict) else None
    rate = rate if isinstance(rate, dict) else {}
    okB, retryB = ratelimit.check(
        f"inst:{inst.name}:{ip_key}",
        ratelimit.Limit(rate.get("rpm", cfg.webhook_rate_rpm), rate.get("burst", cfg.webhook_rate_burst)),
    )
    if not okB:
        return None, body, _rate_limited(retryB)

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

    job, err = _create_and_dispatch(app, inst, payload, deliverable, mode, idem=idem, session_id=session_id)
    if err:
        return JSONResponse({"error": err[1]}, status_code=err[0])

    if request.query_params.get("wait") in ("1", "true", "yes"):
        job = await _wait_for(job.id, timeout=float(request.query_params.get("timeout", 300)))
    return JSONResponse(_ack(job, request), status_code=202)


def _create_and_dispatch(app, inst, payload, deliverable, mode, *, idem=None, session_id=None):
    """Create and enqueue a job on ``inst`` from an already-parsed payload.

    Shared by the webhook handler and the admin run endpoint (playground). Returns
    ``(job, None)`` on success or ``(None, (status_code, message))`` on a client error,
    so each caller can shape it into its own response type.
    """
    name = inst.name

    # Validate the per-job repo selection against the declared pool (§2).
    if "repos" in payload:
        from .instances import InstanceError

        try:
            inst.select_repos(payload.get("repos"))
        except InstanceError as exc:
            return None, (422, str(exc))

    # Session: explicit id, or find-or-create by thread_key.
    sess = None
    thread_key = payload.get("thread_key")
    if session_id:
        sess = store.get_session(session_id)
        if not sess:
            return None, (404, "session not found")
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
    return job, None


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

    # Least-privilege: a code-mutating deliverable must go through plan->apply
    # (human approval) unless the instance explicitly opts into auto-apply. This
    # is enforced regardless of allow_overrides — a webhook caller must never be
    # able to request a direct, unreviewed push.
    engine = get_engine(inst.engine)
    if deliverable.mutates_code and mode is not Mode.PLAN and not inst.allow_auto_apply:
        if not engine.capabilities.plan_mode:
            return None, None, (
                f"engine {inst.engine!r} cannot enforce plan->apply for a "
                f"code-mutating deliverable; set allow_auto_apply to bypass"
            )
        mode = Mode.PLAN

    # Capability validation (§16).
    if mode is Mode.PLAN and not engine.capabilities.plan_mode:
        return None, None, f"engine {inst.engine!r} does not support plan mode"
    return deliverable, mode, None


async def _decision_token(request: Request) -> str:
    """Read the approval token from the POST form body (the confirm page) or,
    for backward-compatible/programmatic callers, the query string. The body is
    parsed manually (urlencoded) to avoid a python-multipart dependency."""
    from urllib.parse import parse_qs

    token = request.query_params.get("token", "")
    try:
        raw = (await request.body()).decode("utf-8", "replace")
        if raw:
            vals = parse_qs(raw).get("token")
            if vals:
                token = vals[0]
    except Exception:  # noqa: BLE001 — no/oversized body; fall back to query param
        pass
    return token


def _confirm_page(job_id: str, action: str, token: str) -> HTMLResponse:
    """A minimal confirm page whose button POSTs the decision (token in the body).
    GET is safe/idempotent, so a link prefetch never changes state."""
    import html

    verb = "Approve" if action == "approve" else "Reject"
    jid = html.escape(job_id)
    tok = html.escape(token)
    body = (
        f"<!doctype html><meta charset=utf-8><title>{verb} job {jid}</title>"
        "<div style='font:16px system-ui;max-width:32rem;margin:4rem auto;text-align:center'>"
        f"<h1>{verb} job <code>{jid}</code>?</h1>"
        f"<form method='post' action='/jobs/{jid}/{action}'>"
        f"<input type='hidden' name='token' value='{tok}'>"
        f"<button style='font:600 16px system-ui;padding:.6rem 1.4rem;cursor:pointer'>"
        f"Confirm {verb.lower()}</button></form></div>"
    )
    return HTMLResponse(body)


def _decide(app: FastAPI, job_id: str, action: str, token: str, request: Request | None = None):
    cfg = load_config()
    if not approval.verify_token(cfg.approval_secret, job_id, action, token):
        return JSONResponse({"error": "invalid or expired token"}, status_code=403)
    job = store.get_job(job_id)
    if not job or job.status is not JobStatus.AWAITING_APPROVAL:
        return JSONResponse({"error": "job not awaiting approval"}, status_code=409)

    approver_ip = request.client.host if (request and request.client) else "unknown"

    if action == "reject":
        job.status = JobStatus.REJECTED
        store.save_job(job)
        store.record_audit(job, output_full=f"approval:reject from {approver_ip}")
        return {"job_id": job_id, "status": "rejected"}

    # Approve: spawn an apply job that resumes the plan with mode=auto.
    job.status = JobStatus.SUCCESS
    store.save_job(job)
    store.record_audit(job, output_full=f"approval:approve from {approver_ip}")
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


def _sse(event: str | None, payload: str) -> str:
    """Format an SSE message; multi-line payloads become one data: line each
    (EventSource rejoins them with newlines, preserving the text)."""
    head = f"event: {event}\n" if event else ""
    body = "".join(f"data: {ln}\n" for ln in payload.split("\n"))
    return head + body + "\n"


async def _log_stream(job_id: str):
    """SSE feed for a job: runner progress lines as plain ``data:`` events
    (back-compat) and live engine text deltas as ``event: text``, ending with
    ``event: done``."""
    from . import paths

    job = store.get_job(job_id)
    if not job:
        return
    log_path = paths.job_log(job.instance, job_id)
    text_path = paths.job_stream(job.instance, job_id)
    log_pos = text_pos = 0

    def drain() -> list[str]:
        nonlocal log_pos, text_pos
        out: list[str] = []
        if log_path.exists():
            with log_path.open() as fh:
                fh.seek(log_pos)
                out.extend(_sse(None, line.rstrip()) for line in fh)
                log_pos = fh.tell()
        if text_path.exists():
            with text_path.open() as fh:
                fh.seek(text_pos)
                delta = fh.read()
                text_pos = fh.tell()
            if delta:
                out.append(_sse("text", delta))
        return out

    for _ in range(1200):  # ~10 min cap
        # Check terminal *before* draining so the final read happens after the
        # job stopped writing — otherwise last deltas could slip past us.
        job = store.get_job(job_id)
        done = job is not None and job.status.terminal
        for msg in drain():
            yield msg
        if done:
            yield _sse("done", job.status.value)
            return
        await asyncio.sleep(0.5)


app = create_app()
