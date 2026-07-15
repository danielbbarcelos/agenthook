"""Global config and declarative apply (DESIGN.md §10, §21).

Global config lives at ``~/.agenthook/config.yaml``. The declarative
``agenthook.yaml`` (committed to a repo, GitOps-style) is reconciled with
``apply_file`` — creating/updating instances; secrets never live in that file.
"""

from __future__ import annotations

import secrets as _pysecrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .instances import Instance, exists as instance_exists, list_names, load as load_instance, save as save_instance


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8080
    workers: int = 1
    default_concurrency: int = 2  # max parallel jobs per instance
    attachment_max_mb: int = 20
    attachment_total_mb: int = 50
    payload_max_kb: int = 512
    retention: str = "truncated"  # truncated | full | metadata (DESIGN.md §24)
    truncate_chars: int = 4000
    approval_ttl_s: int = 86400
    public_base_url: str = "http://localhost:8080"  # for approval links
    approval_secret: str = ""  # HMAC secret for approval/callback signing
    callback_max_attempts: int = 5
    use_docker: bool = True  # set False to run engines directly (dev/test)
    docker_image: str = "agenthook/runner:latest"
    # Webhook rate limiting (token bucket, per-process — see ratelimit.py). The
    # per-instance override lives in ``instance.limits.rate`` ({rpm, burst}).
    webhook_rate_rpm: int = 120  # default post-auth budget per (instance, ip)
    webhook_rate_burst: int = 40
    webhook_ip_rpm: int = 300  # pre-auth per-ip flood guard (all instances)
    # Egress lockdown (see agenthook/egress/). When on, job containers run on an
    # internal network (no internet) and reach only the broker; the model call is
    # routed through the broker's credential-injecting gateway.
    egress_enabled: bool = True
    egress_network: str = "agenthook-egress-net"
    egress_ctrl_port: int = 8079  # broker control plane, published to host loopback
    egress_allow_default: list[str] = field(default_factory=list)  # extra hosts every job may reach
    # Management API (control-plane, /admin/*). Protected by a bearer token and,
    # by default, bound to loopback only — remote access is an explicit opt-in.
    admin_token: str = ""  # bearer for /admin/*; auto-generated if empty
    admin_remote: bool = False  # allow /admin/* from non-loopback clients

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config() -> Config:
    p = paths.config_file()
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    data = data or {}
    known = set(Config.__dataclass_fields__)  # type: ignore[attr-defined]
    cfg = Config(**{k: v for k, v in data.items() if k in known})
    dirty = False
    if not cfg.approval_secret:
        cfg.approval_secret = _pysecrets.token_urlsafe(32)
        dirty = True
    if not cfg.admin_token:
        cfg.admin_token = _pysecrets.token_urlsafe(32)
        dirty = True
    if dirty:
        save_config(cfg)
    return cfg


def save_config(cfg: Config) -> None:
    paths.config_file().write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=False))


# --- Declarative apply ------------------------------------------------------


def apply_file(path: str | Path, *, prune: bool = False) -> dict[str, list[str]]:
    """Reconcile instances from a declarative ``agenthook.yaml``.

    Returns a report of created/updated/(pruned) instance names. New instances
    get an encryption key generated automatically.
    """
    from . import secrets as secrets_mod

    doc = yaml.safe_load(Path(path).read_text()) or {}
    desired = doc.get("instances", {}) or {}
    report: dict[str, list[str]] = {"created": [], "updated": [], "pruned": []}

    for name, spec in desired.items():
        spec = dict(spec or {})
        spec["name"] = name
        inst = Instance.from_dict(spec)
        if instance_exists(name):
            # preserve key fingerprint
            existing = load_instance(name)
            inst.key_fingerprint = existing.key_fingerprint
            save_instance(inst)
            report["updated"].append(name)
        else:
            save_instance(inst)
            _, fp = secrets_mod.generate_key(inst)
            inst.key_fingerprint = fp
            save_instance(inst)
            report["created"].append(name)

    if prune:
        for name in list_names():
            if name not in desired:
                from .instances import delete as delete_instance

                delete_instance(name)
                report["pruned"].append(name)
    return report
