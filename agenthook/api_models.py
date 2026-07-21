"""Pydantic request models for the Management API (``/admin/*``).

Per the design note in ``models.py``, the domain stays plain dataclasses and the
FastAPI layer defines its own pydantic models on top. These validate inbound
shapes; the authoritative business validation still runs in
``Instance.validate()`` before persistence.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class InstanceFields(BaseModel):
    """Writable instance configuration. All optional; ``None``/unset means
    'leave as default' (create) or 'leave unchanged' (patch)."""

    model_config = {"extra": "forbid"}

    engine: Optional[str] = None
    repo: Optional[str] = None
    repos: Optional[list[dict[str, Any]]] = None
    branch_base: Optional[str] = None
    engine_auth: Optional[str] = None
    webhook_auth: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    default_prompt: Optional[str] = None
    deliverable: Optional[str] = None
    on_result: Optional[list[str]] = None
    callback_url: Optional[str] = None
    pr_branch: Optional[str] = None
    allow_overrides: Optional[list[str]] = None
    limits: Optional[dict[str, Any]] = None
    verify: Optional[dict[str, Any]] = None
    mcp: Optional[dict[str, Any]] = None
    schedules: Optional[list[dict[str, Any]]] = None
    secrets_backend: Optional[str] = None
    context_template: Optional[str] = None
    templates: Optional[dict[str, str]] = None
    guardrails: Optional[dict[str, Any]] = None
    skills: Optional[dict[str, str]] = None


class InstanceCreate(InstanceFields):
    name: str = Field(..., description="instance slug (lowercase, digits, '-' or '_')")


class InstancePatch(InstanceFields):
    """Partial update — only the fields present are applied."""


class RepoIn(BaseModel):
    model_config = {"extra": "forbid"}
    url: str
    name: Optional[str] = None
    branch_base: Optional[str] = None


class EnvVarIn(BaseModel):
    model_config = {"extra": "forbid"}
    value: str
    secret: bool = False


class RunIn(BaseModel):
    """Ad-hoc control-plane run against an instance (the console playground).

    Bypasses the webhook auth — the admin JWT already proves control-plane
    authority — and, unlike ``/hook``, honors an explicit ``deliverable``/``mode``
    regardless of ``allow_overrides`` (the operator has full authority here).
    ``repos`` is the per-job selection: unset = all declared, ``[]`` = none.
    """

    model_config = {"extra": "forbid"}
    prompt: str = ""
    thread_key: Optional[str] = None
    deliverable: Optional[str] = None
    mode: Optional[str] = None
    repos: Optional[list[str]] = None


class BodyIn(BaseModel):
    """A raw text body (CLAUDE.md context, a request template, a SKILL.md)."""

    model_config = {"extra": "forbid"}
    body: str


class DictIn(BaseModel):
    """An arbitrary config mapping (webhook_auth, verify, mcp)."""

    model_config = {"extra": "allow"}


class GuardrailsIn(BaseModel):
    """Append-only / hardening-only guardrail overlay over the global baseline."""

    model_config = {"extra": "forbid"}
    extra: Optional[str] = None
    force_read_only: Optional[bool] = None


class LoginCodeIn(BaseModel):
    """The pasted OAuth code for an in-progress headless subscription login."""

    model_config = {"extra": "forbid"}
    session: str
    code: str


class ConfigPatch(BaseModel):
    model_config = {"extra": "forbid"}
    host: Optional[str] = None
    port: Optional[int] = None
    workers: Optional[int] = None
    default_concurrency: Optional[int] = None
    attachment_max_mb: Optional[int] = None
    attachment_total_mb: Optional[int] = None
    payload_max_kb: Optional[int] = None
    retention: Optional[str] = None
    truncate_chars: Optional[int] = None
    approval_ttl_s: Optional[int] = None
    public_base_url: Optional[str] = None
    callback_max_attempts: Optional[int] = None
    use_docker: Optional[bool] = None
    docker_image: Optional[str] = None
    admin_remote: Optional[bool] = None
