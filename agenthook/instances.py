"""Instance registry — persisted as YAML (DESIGN.md §2, §3).

An *instance* is the reusable configuration that ties a repository (optional),
an engine, auth, a default deliverable and assorted sub-blocks (verify, mcp,
schedules) together. Instances live at
``~/.agenthook/instances/<name>/instance.yaml``; their encrypted env lives next
to it (see :mod:`agenthook.secrets`).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml

from . import paths

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class InstanceError(Exception):
    pass


def _derive_repo_name(url: str) -> str:
    """A logical, filesystem-safe name from a git URL's last path segment."""
    tail = url.rstrip("/").split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    tail = re.sub(r"[^a-z0-9_-]+", "-", tail.lower()).strip("-")
    return tail or "repo"


@dataclass
class RepoRef:
    """A single repository a job may check out (DESIGN.md §2). Multi-checkout:
    an instance declares a *pool* of these; each job selects 0..N of them."""

    name: str
    url: str
    branch_base: str = "main"


@dataclass
class Instance:
    name: str
    engine: str = "claude"
    repo: str | None = None  # legacy single-repo (still honored); prefer `repos`
    repos: list[dict[str, Any]] = field(default_factory=list)  # pool: {name,url,branch_base?}
    branch_base: str = "main"
    engine_auth: str = "api-key"  # api-key | subscription
    webhook_auth: dict[str, Any] = field(default_factory=dict)  # §12
    model: str | None = None
    default_prompt: str | None = None
    deliverable: str = "analysis"
    on_result: list[str] = field(default_factory=lambda: ["logs"])
    callback_url: str | None = None
    pr_branch: str = "agenthook/job-{id}"
    allow_overrides: list[str] = field(default_factory=list)
    limits: dict[str, Any] = field(default_factory=dict)  # timeout, max_turns, concurrency, retry
    verify: dict[str, Any] = field(default_factory=dict)  # §18
    mcp: dict[str, Any] = field(default_factory=dict)  # §25
    schedules: list[dict[str, Any]] = field(default_factory=list)  # §28
    secrets_backend: str = "local-encrypted"  # §27
    context_template: str | None = None  # §13 (inline template body)
    templates: dict[str, str] = field(default_factory=dict)  # §14, request_type -> body
    guardrails: dict[str, Any] = field(default_factory=dict)  # append-only over the global baseline
    skills: dict[str, str] = field(default_factory=dict)  # name -> SKILL.md body
    paused: bool = False  # circuit breaker (§17)
    paused_reason: str | None = None
    key_fingerprint: str | None = None

    # ---- validation / convenience ----------------------------------------

    def validate(self) -> None:
        if not _NAME_RE.match(self.name):
            raise InstanceError(
                f"invalid instance name {self.name!r}: use lowercase letters, digits, '-' or '_'"
            )
        from .models import Deliverable, Mode  # local import to avoid cycle

        if self.deliverable not in {d.value for d in Deliverable}:
            raise InstanceError(f"unknown deliverable {self.deliverable!r}")
        if self.engine_auth not in {"api-key", "subscription"}:
            raise InstanceError(f"unknown engine_auth {self.engine_auth!r}")
        mode = self.limits.get("mode")
        if mode and mode not in {m.value for m in Mode}:
            raise InstanceError(f"unknown default mode {mode!r}")
        seen: set[str] = set()
        for r in self.repos:
            if not r.get("url"):
                raise InstanceError(f"repo entry missing 'url': {r!r}")
            rname = r.get("name") or _derive_repo_name(r["url"])
            if not _NAME_RE.match(rname):
                raise InstanceError(f"invalid repo name {rname!r}")
            if rname in seen:
                raise InstanceError(f"duplicate repo name {rname!r}")
            seen.add(rname)
        self._validate_guardrails()
        for sname in self.skills:
            if not _NAME_RE.match(sname):
                raise InstanceError(f"invalid skill name {sname!r}")

    # Guardrails are append-only / hardening-only: the global baseline is an
    # inviolable floor. An instance may *add* rules or *harden*, never disable a
    # safety block — so only this closed set of keys is allowed.
    _GUARDRAIL_KEYS = {"extra", "force_read_only"}

    def _validate_guardrails(self) -> None:
        g = self.guardrails
        if not g:
            return
        if not isinstance(g, dict):
            raise InstanceError("guardrails must be a mapping")
        unknown = set(g) - self._GUARDRAIL_KEYS
        if unknown:
            raise InstanceError(
                f"unknown guardrails key(s) {sorted(unknown)} — guardrails are "
                f"append-only; allowed: {sorted(self._GUARDRAIL_KEYS)}"
            )
        if "extra" in g and not isinstance(g["extra"], str):
            raise InstanceError("guardrails.extra must be a string")
        if "force_read_only" in g and not isinstance(g["force_read_only"], bool):
            raise InstanceError("guardrails.force_read_only must be a boolean")

    @property
    def default_mode(self) -> str:
        return self.limits.get("mode", "default")

    # ---- repo pool (DESIGN.md §2 — multi-checkout) -----------------------

    def resolved_repos(self) -> list["RepoRef"]:
        """The full declared pool as :class:`RepoRef`, normalizing the legacy
        single ``repo`` field when ``repos`` is empty."""
        if self.repos:
            return [
                RepoRef(
                    name=r.get("name") or _derive_repo_name(r["url"]),
                    url=r["url"],
                    branch_base=r.get("branch_base") or self.branch_base,
                )
                for r in self.repos
            ]
        if self.repo:
            return [RepoRef(_derive_repo_name(self.repo), self.repo, self.branch_base)]
        return []

    def repo_names(self) -> list[str]:
        return [r.name for r in self.resolved_repos()]

    def select_repos(self, names: list[str] | None) -> list["RepoRef"]:
        """Resolve a per-job selection against the declared pool.

        ``None`` (key absent) -> all declared repos; ``[]`` -> none (0 repos);
        a list -> that subset. Unknown names raise (the job can only reach
        pre-authorized repos)."""
        pool = self.resolved_repos()
        if names is None:
            return pool
        if not isinstance(names, list):
            raise InstanceError("'repos' selection must be a list of repo names")
        by_name = {r.name: r for r in pool}
        out: list[RepoRef] = []
        for n in names:
            ref = by_name.get(n)
            if ref is None:
                raise InstanceError(
                    f"repo {n!r} is not declared on instance {self.name!r} "
                    f"(available: {', '.join(by_name) or 'none'})"
                )
            out.append(ref)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instance":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# --- Persistence ------------------------------------------------------------


def _path(name: str):
    return paths.instance_dir(name) / "instance.yaml"


def exists(name: str) -> bool:
    return _path(name).exists()


def save(inst: Instance) -> None:
    inst.validate()
    d = paths.instance_dir(inst.name)
    d.mkdir(parents=True, exist_ok=True)
    _path(inst.name).write_text(yaml.safe_dump(inst.to_dict(), sort_keys=False, allow_unicode=True))


def load(name: str) -> Instance:
    p = _path(name)
    if not p.exists():
        raise InstanceError(f"instance {name!r} not found")
    data = yaml.safe_load(p.read_text()) or {}
    return Instance.from_dict(data)


def list_names() -> list[str]:
    base = paths.instances_dir()
    return sorted(d.name for d in base.iterdir() if (d / "instance.yaml").exists())


def list_all() -> list[Instance]:
    return [load(n) for n in list_names()]


def delete(name: str) -> None:
    """Remove an instance and *all* its on-disk state.

    Critically this includes the isolated engine auth dir (the per-instance
    subscription login / api-key config): a fresh instance reusing the name must
    start unauthenticated, never inherit the old subscription. Repo mirrors and
    logs go too, so nothing leaks across a delete + re-create.
    """
    import shutil

    d = paths.instance_dir(name)
    if not d.exists():
        raise InstanceError(f"instance {name!r} not found")
    shutil.rmtree(d)
    for extra in (
        paths.home() / "auth" / name,
        paths.repos_dir() / name,
        paths.home() / "logs" / name,
    ):
        if extra.exists():
            shutil.rmtree(extra, ignore_errors=True)


def set_paused(name: str, paused: bool, reason: str | None = None) -> None:
    inst = load(name)
    inst.paused = paused
    inst.paused_reason = reason if paused else None
    save(inst)
