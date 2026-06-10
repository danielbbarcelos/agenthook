"""Prompt / context-file / MCP templating (DESIGN.md §13, §14, §25).

Templates are rendered with a sandboxed Jinja2 environment. The render context
exposes the request fields (requester, request_type, language, …) plus the
instance's **non-secret** env vars under ``env`` (secret values are deliberately
excluded from rendered text). MCP config interpolation, by contrast, runs at
container build time with the real decrypted values.
"""

from __future__ import annotations

from typing import Any

from jinja2.sandbox import SandboxedEnvironment

from .instances import Instance

_env = SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


def render(template: str, context: dict[str, Any]) -> str:
    return _env.from_string(template).render(**context)


def build_context(request: dict[str, Any], env_nonsecret: dict[str, str]) -> dict[str, Any]:
    """Assemble the render context from a webhook request payload."""
    ctx = dict(request or {})
    ctx.setdefault("requester", {})
    ctx.setdefault("request_type", "custom")
    ctx.setdefault("language", "en")
    ctx.setdefault("metadata", {})
    ctx.setdefault("subject_ref", {})
    ctx["env"] = dict(env_nonsecret)
    return ctx


def resolve_prompt(inst: Instance, request: dict[str, Any], context: dict[str, Any]) -> str:
    """Determine and render the final prompt (DESIGN.md §14).

    Precedence: explicit ``prompt`` in the request > per-request_type template >
    instance ``default_prompt``.
    """
    explicit = request.get("prompt")
    if explicit:
        return render(explicit, context)

    rtype = request.get("request_type")
    if rtype and rtype in inst.templates:
        return render(inst.templates[rtype], context)

    if inst.default_prompt:
        return render(inst.default_prompt, context)

    raise ValueError(
        "no prompt: request has no 'prompt', no template for its request_type, "
        "and the instance has no default_prompt"
    )


def render_context_file(inst: Instance, context: dict[str, Any]) -> str | None:
    if not inst.context_template:
        return None
    return render(inst.context_template, context)


def render_mcp(inst: Instance, env_all: dict[str, str]) -> dict[str, Any]:
    """Interpolate ``{{ env.X }}`` in the MCP config with real (decrypted) values.

    Returns a ``.mcp.json``-shaped dict. Runs only at container build time so
    secrets never appear in logged/rendered text elsewhere.
    """
    if not inst.mcp:
        return {}
    ctx = {"env": dict(env_all)}

    def _walk(obj: Any) -> Any:
        if isinstance(obj, str):
            return render(obj, ctx)
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        return obj

    return {"mcpServers": _walk(inst.mcp)}
