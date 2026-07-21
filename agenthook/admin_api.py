"""Management API — the control-plane over HTTP (``/admin/*``).

A thin HTTP shell over the same business logic the CLI uses: instance CRUD and
configuration (repos, webhook auth, verify, mcp, CLAUDE.md context, request
templates, guardrails, skills), encrypted env vars, global config, and read-only
observability (jobs/sessions/usage/audit). Guarded router-wide by
:func:`admin_auth.require_admin` (bearer token + loopback-by-default).

Secrets are never returned in cleartext: env values flagged ``secret`` are
masked, and the global config masks ``admin_token``/``approval_secret``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from . import config as config_mod
from . import instances, secrets, serde, store
from .admin_auth import require_admin
from .api_models import (
    BodyIn,
    ConfigPatch,
    DictIn,
    EnvVarIn,
    GuardrailsIn,
    InstanceCreate,
    InstancePatch,
    LoginCodeIn,
    RepoIn,
    RunIn,
)
from .instances import Instance, InstanceError

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/ping")
def ping():
    """Cheap authenticated whoami: a 200 means the network + credential gates
    passed. The Workspace uses it to test a server's base_url + token/JWT."""
    return {"ok": True}


# --- helpers ----------------------------------------------------------------


def _get(name: str) -> Instance:
    try:
        return instances.load(name)
    except InstanceError:
        raise HTTPException(status_code=404, detail=f"instance {name!r} not found")


def _save(inst: Instance) -> None:
    try:
        instances.save(inst)
    except InstanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _summary(inst: Instance) -> dict:
    return {
        "name": inst.name,
        "engine": inst.engine,
        "deliverable": inst.deliverable,
        "repos": inst.repo_names(),
        "paused": inst.paused,
    }


# --- engines ----------------------------------------------------------------


@router.get("/engines")
def list_engines():
    """Available engines, for the UI's selector and auth-mode hints."""
    from dataclasses import asdict

    from .engines import registry

    out = []
    for name, cls in registry().items():
        eng = cls()
        out.append(
            {
                "name": name,
                "supports_subscription": bool(eng.login_argv("/tmp/_agenthook_probe")),
                "capabilities": asdict(eng.capabilities),
            }
        )
    return out


# --- instances: CRUD --------------------------------------------------------


@router.get("/instances")
def list_instances():
    return [_summary(i) for i in instances.list_all()]


@router.post("/instances", status_code=201)
def create_instance(body: InstanceCreate):
    data = body.model_dump(exclude_unset=True)
    name = data.pop("name")
    if instances.exists(name):
        raise HTTPException(status_code=409, detail=f"instance {name!r} already exists")
    try:
        inst = Instance(name=name, **data)
    except TypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _save(inst)
    key, fp = secrets.generate_key(inst)
    inst.key_fingerprint = fp
    _save(inst)
    # The encryption key is shown ONCE — the caller must store it.
    return {"instance": inst.to_dict(), "encryption_key": key, "fingerprint": fp}


@router.get("/instances/{name}")
def get_instance(name: str):
    return _get(name).to_dict()


@router.patch("/instances/{name}")
def patch_instance(name: str, body: InstancePatch):
    inst = _get(name)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(inst, k, v)
    _save(inst)
    return inst.to_dict()


@router.delete("/instances/{name}", status_code=204)
def delete_instance(name: str):
    try:
        instances.delete(name)
    except InstanceError:
        raise HTTPException(status_code=404, detail=f"instance {name!r} not found")
    return Response(status_code=204)


@router.post("/instances/{name}/pause")
def pause_instance(name: str, body: Optional[dict] = None):
    _get(name)
    reason = (body or {}).get("reason") if isinstance(body, dict) else None
    instances.set_paused(name, True, reason)
    return _summary(_get(name))


@router.post("/instances/{name}/resume")
def resume_instance(name: str):
    _get(name)
    instances.set_paused(name, False)
    return _summary(_get(name))


@router.post("/instances/{name}/run", status_code=202)
def run_instance(name: str, body: RunIn, request: Request):
    """Ad-hoc control-plane run against an instance (the console playground).

    Enqueues a job exactly like ``/hook`` would, but authenticated by the admin
    credential — no webhook secret needed, so it works regardless of the instance's
    ``webhook_auth``. Follow the returned ``stream_url`` (``GET /admin/jobs/{id}/stream``)
    for the live SSE feed. Honors an explicit ``deliverable``/``mode`` (operator authority).
    """
    from .models import Deliverable, Mode  # local import to avoid a load-time cycle
    from .server import _create_and_dispatch

    inst = _get(name)
    payload = body.model_dump(exclude_unset=True)
    try:
        deliverable = Deliverable(payload.get("deliverable", inst.deliverable))
        mode = Mode(payload.get("mode", inst.default_mode))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    job, err = _create_and_dispatch(request.app, inst, payload, deliverable, mode)
    if err:
        raise HTTPException(status_code=err[0], detail=err[1])

    base = str(request.base_url).rstrip("/")
    return {
        "job_id": job.id,
        "status": job.status.value,
        "session_id": job.session_id,
        "stream_url": f"{base}/admin/jobs/{job.id}/stream",
    }


# --- repos ------------------------------------------------------------------


@router.get("/instances/{name}/repos")
def list_repos(name: str):
    return [{"name": r.name, "url": r.url, "branch_base": r.branch_base} for r in _get(name).resolved_repos()]


@router.post("/instances/{name}/repos", status_code=201)
def add_repo(name: str, body: RepoIn):
    inst = _get(name)
    entry = {"url": body.url}
    if body.name:
        entry["name"] = body.name
    if body.branch_base:
        entry["branch_base"] = body.branch_base
    inst.repos = list(inst.repos) + [entry]
    _save(inst)
    return list_repos(name)


@router.delete("/instances/{name}/repos/{repo}")
def remove_repo(name: str, repo: str):
    inst = _get(name)
    kept = [r for r in inst.repos if (r.get("name") or "") != repo and r.get("url") != repo]
    if len(kept) == len(inst.repos):
        raise HTTPException(status_code=404, detail=f"repo {repo!r} not found")
    inst.repos = kept
    _save(inst)
    return list_repos(name)


# --- env / secrets (masked) -------------------------------------------------


@router.get("/instances/{name}/env")
def list_env(name: str):
    inst = _get(name)
    out = []
    for ev in secrets.get_backend(inst).items(inst):
        out.append(
            {
                "name": ev.name,
                "value": secrets.obfuscate(ev.value) if ev.secret else ev.value,
                "secret": ev.secret,
            }
        )
    return out


@router.put("/instances/{name}/env/{key}")
def set_env(name: str, key: str, body: EnvVarIn):
    inst = _get(name)
    secrets.get_backend(inst).set(inst, key, body.value, body.secret)
    return {"name": key, "secret": body.secret, "value": secrets.obfuscate(body.value) if body.secret else body.value}


@router.delete("/instances/{name}/env/{key}", status_code=204)
def delete_env(name: str, key: str):
    inst = _get(name)
    secrets.get_backend(inst).delete(inst, key)
    return Response(status_code=204)


# --- config blocks (whole-field replace) ------------------------------------


@router.put("/instances/{name}/auth")
def set_auth(name: str, body: DictIn):
    inst = _get(name)
    inst.webhook_auth = body.model_dump()
    _save(inst)
    return inst.webhook_auth


# --- engine auth (the coding engine's own login, NOT the webhook auth above) --
#
# The actual subscription login is interactive (OAuth/TTY) and stays in the CLI
# (`agenthook login <name>`); over HTTP we only expose status and logout. The
# auth *mode* (api-key | subscription) is set via PATCH /instances/{name}.


def _has_token_secret(inst: Instance, eng) -> bool:
    """True when the engine's OAuth-token secret is stored for this instance."""
    key = eng.token_env_name()
    if not key:
        return False
    return any(ev.name == key for ev in secrets.get_backend(inst).items(inst))


@router.get("/instances/{name}/engine-auth")
def get_engine_auth(name: str):
    from . import engine_auth
    from .engines import get_engine

    inst = _get(name)
    eng = get_engine(inst.engine)
    # Authenticated when a dir credential exists OR the headless token secret is set.
    authed = engine_auth.is_authenticated(inst)
    if authed is not True and _has_token_secret(inst, eng):
        authed = True
    return {
        "mode": inst.engine_auth,  # api-key | subscription
        "authenticated": authed,  # True/False/None (None p/ api-key sem token)
        "supports_subscription": bool(eng.login_argv("/tmp/_agenthook_probe")),
        "supports_token_login": bool(eng.setup_token_argv()),
        "login_command": f"agenthook login {name}",
    }


@router.post("/instances/{name}/engine-auth/login/start")
def engine_login_start(name: str):
    """Begin the headless subscription login; returns an OAuth URL to authorize."""
    from . import engine_login

    inst = _get(name)
    try:
        session, url = engine_login.start(inst)
    except engine_login.LoginError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"session": session, "url": url}


@router.post("/instances/{name}/engine-auth/login/code")
def engine_login_code(name: str, body: LoginCodeIn):
    """Submit the pasted code; captures the token and stores it as a secret."""
    from . import engine_login
    from .engines import get_engine

    inst = _get(name)
    eng = get_engine(inst.engine)
    key = eng.token_env_name()
    if not key:
        raise HTTPException(status_code=400, detail="engine has no token-based login")
    try:
        token = engine_login.submit_code(body.session, body.code)
    except engine_login.LoginError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    secrets.get_backend(inst).set(inst, key, token, True)  # encrypted, masked, never echoed
    return {"authenticated": True}


@router.delete("/instances/{name}/engine-auth", status_code=204)
def logout_engine_auth(name: str):
    from . import engine_auth
    from .engines import get_engine

    inst = _get(name)
    engine_auth.logout(inst)
    # Also clear the headless token secret so the instance is truly disconnected.
    key = get_engine(inst.engine).token_env_name()
    if key and _has_token_secret(inst, get_engine(inst.engine)):
        secrets.get_backend(inst).delete(inst, key)
    return Response(status_code=204)


@router.put("/instances/{name}/verify")
def set_verify(name: str, body: DictIn):
    inst = _get(name)
    inst.verify = body.model_dump()
    _save(inst)
    return inst.verify


@router.put("/instances/{name}/mcp")
def set_mcp(name: str, body: DictIn):
    inst = _get(name)
    inst.mcp = body.model_dump()
    _save(inst)
    return inst.mcp


@router.get("/instances/{name}/context")
def get_context(name: str):
    return {"body": _get(name).context_template or ""}


@router.put("/instances/{name}/context")
def set_context(name: str, body: BodyIn):
    inst = _get(name)
    inst.context_template = body.body or None
    _save(inst)
    return {"body": inst.context_template or ""}


@router.put("/instances/{name}/templates/{request_type}")
def set_template(name: str, request_type: str, body: BodyIn):
    inst = _get(name)
    inst.templates = {**inst.templates, request_type: body.body}
    _save(inst)
    return {"request_type": request_type, "body": body.body}


@router.delete("/instances/{name}/templates/{request_type}", status_code=204)
def delete_template(name: str, request_type: str):
    inst = _get(name)
    if request_type not in inst.templates:
        raise HTTPException(status_code=404, detail=f"template {request_type!r} not found")
    inst.templates = {k: v for k, v in inst.templates.items() if k != request_type}
    _save(inst)
    return Response(status_code=204)


# --- guardrails (append-only) -----------------------------------------------


@router.get("/instances/{name}/guardrails")
def get_guardrails(name: str):
    return _get(name).guardrails or {}


@router.put("/instances/{name}/guardrails")
def set_guardrails(name: str, body: GuardrailsIn):
    inst = _get(name)
    inst.guardrails = body.model_dump(exclude_none=True)
    _save(inst)  # Instance.validate() rejects any relaxation/unknown keys
    return inst.guardrails


# --- skills -----------------------------------------------------------------


@router.get("/instances/{name}/skills")
def list_skills(name: str):
    return sorted(_get(name).skills)


@router.get("/instances/{name}/skills/{skill}")
def get_skill(name: str, skill: str):
    inst = _get(name)
    if skill not in inst.skills:
        raise HTTPException(status_code=404, detail=f"skill {skill!r} not found")
    return {"name": skill, "body": inst.skills[skill]}


@router.put("/instances/{name}/skills/{skill}")
def set_skill(name: str, skill: str, body: BodyIn):
    inst = _get(name)
    inst.skills = {**inst.skills, skill: body.body}
    _save(inst)  # validates the skill name
    return {"name": skill, "body": body.body}


@router.delete("/instances/{name}/skills/{skill}", status_code=204)
def delete_skill(name: str, skill: str):
    inst = _get(name)
    if skill not in inst.skills:
        raise HTTPException(status_code=404, detail=f"skill {skill!r} not found")
    inst.skills = {k: v for k, v in inst.skills.items() if k != skill}
    _save(inst)
    return Response(status_code=204)


# --- global config ----------------------------------------------------------

_MASKED_CONFIG = ("admin_token", "approval_secret")


def _config_view(cfg: config_mod.Config) -> dict:
    d = cfg.to_dict()
    for k in _MASKED_CONFIG:
        if d.get(k):
            d[k] = secrets.obfuscate(d[k])
    return d


@router.get("/config")
def get_config():
    return _config_view(config_mod.load_config())


@router.patch("/config")
def patch_config(body: ConfigPatch):
    cfg = config_mod.load_config()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(cfg, k, v)
    config_mod.save_config(cfg)
    return _config_view(cfg)


# --- observability (read-only) ----------------------------------------------


@router.get("/jobs")
def list_jobs(
    instance: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000),
):
    return [serde.job_to_dict(j) for j in store.list_jobs(instance=instance, status=status, limit=limit)]


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return serde.job_to_dict(job)


@router.get("/jobs/{job_id}/stream")
def stream_job(job_id: str):
    """Admin-authed SSE feed for a job (runner progress + live engine text deltas).

    Mirrors the public ``/jobs/{id}/stream`` but under ``/admin/*`` so the Workspace
    console can reach it through the same channel it already uses (the public ``/jobs``
    routes are typically kept off the internet by the reverse proxy)."""
    from .server import _log_stream  # local import to avoid a load-time cycle

    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(_log_stream(job_id), media_type="text/event-stream")


@router.get("/sessions")
def list_sessions(instance: Optional[str] = None):
    return [serde.session_to_dict(s) for s in store.list_sessions(instance=instance)]


@router.get("/usage")
def usage(instance: Optional[str] = None, requester: Optional[str] = None, since: Optional[float] = None):
    return store.usage_summary(instance=instance, requester=requester, since=since)


@router.get("/audit")
def audit(
    instance: Optional[str] = None,
    requester: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
):
    return store.audit_rows(instance=instance, requester=requester, limit=limit)
