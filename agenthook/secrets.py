"""Pluggable secret backends (DESIGN.md §7, §27).

The default ``local-encrypted`` backend gives every instance an immutable
Fernet key (shown once at creation, kept on disk for auto-decrypt) and stores
all env vars in an encrypted ``env.enc`` blob. A second built-in ``env`` backend
reads values straight from the process environment (12-factor / containers).
Third-party backends (Vault, KMS, sops) plug in via the
``agenthook.secrets_backends`` entry point group.

The ``secret`` flag only controls *display* (obfuscation on list/get) — on disk
every value is encrypted regardless.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken

from . import paths
from .instances import Instance


@dataclass
class EnvVar:
    name: str
    value: str
    secret: bool = False


def obfuscate(value: str) -> str:
    """Mask a secret value, keeping a short suffix for recognizability."""
    if not value:
        return ""
    tail = value[-4:] if len(value) > 8 else ""
    return "••••••" + tail


# --- Backend protocol -------------------------------------------------------


@runtime_checkable
class SecretsBackend(Protocol):
    name: str

    def get(self, inst: Instance, key: str) -> str | None: ...
    def set(self, inst: Instance, key: str, value: str, secret: bool) -> None: ...
    def delete(self, inst: Instance, key: str) -> None: ...
    def items(self, inst: Instance) -> list[EnvVar]: ...


# --- local-encrypted --------------------------------------------------------


class LocalEncryptedBackend:
    name = "local-encrypted"

    def _key_path(self, inst: Instance):
        return paths.instance_dir(inst.name) / "instance.key"

    def _env_path(self, inst: Instance):
        return paths.instance_dir(inst.name) / "env.enc"

    def _fernet(self, inst: Instance) -> Fernet:
        kp = self._key_path(inst)
        if not kp.exists():
            raise SecretsError(
                f"encryption key for instance {inst.name!r} is missing ({kp})"
            )
        return Fernet(kp.read_bytes())

    def _load(self, inst: Instance) -> dict[str, dict]:
        ep = self._env_path(inst)
        if not ep.exists():
            return {}
        try:
            data = self._fernet(inst).decrypt(ep.read_bytes())
        except InvalidToken as exc:  # wrong key / corrupted blob
            raise SecretsError(
                f"could not decrypt env for instance {inst.name!r}: wrong key?"
            ) from exc
        return json.loads(data.decode())

    def _store(self, inst: Instance, mapping: dict[str, dict]) -> None:
        blob = self._fernet(inst).encrypt(json.dumps(mapping).encode())
        ep = self._env_path(inst)
        ep.write_bytes(blob)
        os.chmod(ep, 0o600)

    def get(self, inst: Instance, key: str) -> str | None:
        entry = self._load(inst).get(key)
        return entry["value"] if entry else None

    def set(self, inst: Instance, key: str, value: str, secret: bool) -> None:
        mapping = self._load(inst)
        mapping[key] = {"value": value, "secret": bool(secret)}
        self._store(inst, mapping)

    def delete(self, inst: Instance, key: str) -> None:
        mapping = self._load(inst)
        if key in mapping:
            del mapping[key]
            self._store(inst, mapping)

    def items(self, inst: Instance) -> list[EnvVar]:
        return [
            EnvVar(name=k, value=v["value"], secret=v.get("secret", False))
            for k, v in sorted(self._load(inst).items())
        ]


# --- env (process environment) ----------------------------------------------


class EnvBackend:
    """Read-only backend that resolves values from the process environment.

    Looks up ``AGENTHOOK_<INSTANCE>_<KEY>`` first, then a bare ``<KEY>`` — so a
    deployment can inject secrets via the orchestrator instead of disk.
    """

    name = "env"

    def _candidates(self, inst: Instance, key: str) -> list[str]:
        prefix = f"AGENTHOOK_{inst.name.upper().replace('-', '_')}_"
        return [prefix + key, key]

    def get(self, inst: Instance, key: str) -> str | None:
        for cand in self._candidates(inst, key):
            if cand in os.environ:
                return os.environ[cand]
        return None

    def set(self, inst: Instance, key: str, value: str, secret: bool) -> None:
        raise SecretsError("env backend is read-only; export the variable in the environment")

    def delete(self, inst: Instance, key: str) -> None:
        raise SecretsError("env backend is read-only")

    def items(self, inst: Instance) -> list[EnvVar]:
        prefix = f"AGENTHOOK_{inst.name.upper().replace('-', '_')}_"
        out: list[EnvVar] = []
        for k, v in os.environ.items():
            if k.startswith(prefix):
                out.append(EnvVar(name=k[len(prefix):], value=v, secret=True))
        return sorted(out, key=lambda e: e.name)


class SecretsError(Exception):
    pass


# --- Key management & factory ----------------------------------------------

_BUILTINS: dict[str, type] = {
    LocalEncryptedBackend.name: LocalEncryptedBackend,
    EnvBackend.name: EnvBackend,
}


def get_backend(inst: Instance) -> SecretsBackend:
    cls = _BUILTINS.get(inst.secrets_backend)
    if cls is None:
        from .plugins import load_secrets_backend

        cls = load_secrets_backend(inst.secrets_backend)
    if cls is None:
        raise SecretsError(f"unknown secrets backend {inst.secrets_backend!r}")
    return cls()  # type: ignore[call-arg]


def generate_key(inst: Instance) -> tuple[str, str]:
    """Create the instance's immutable encryption key. Returns (key, fingerprint).

    Refuses to overwrite an existing key (keys are immutable for the life of the
    instance, DESIGN.md §7).
    """
    kp = paths.instance_dir(inst.name) / "instance.key"
    if kp.exists():
        raise SecretsError(f"instance {inst.name!r} already has an encryption key")
    key = Fernet.generate_key()
    paths.instance_dir(inst.name).mkdir(parents=True, exist_ok=True)
    kp.write_bytes(key)
    os.chmod(kp, 0o600)
    return key.decode(), fingerprint(key)


def fingerprint(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


# agenthook's own control-plane secrets live in env.enc under this reserved
# namespace (e.g. webhook auth headers, AGENTHOOK_HEADER_*). They are read by
# agenthook itself (auth.py) but must NEVER be injected into the agent's runtime.
RESERVED_PREFIX = "AGENTHOOK_"


def is_agent_visible(name: str) -> bool:
    """False for control-plane secrets that must never reach the agent runtime
    (the reserved AGENTHOOK_* namespace)."""
    return not name.upper().startswith(RESERVED_PREFIX)


def resolve_env(inst: Instance) -> dict[str, str]:
    """Env vars (decrypted, real values) injected into the agent's runtime.
    Excludes the reserved AGENTHOOK_* control-plane namespace (e.g. webhook auth
    secrets), which the agent must never see."""
    backend = get_backend(inst)
    return {ev.name: ev.value for ev in backend.items(inst) if is_agent_visible(ev.name)}


def get_control_secret(inst: Instance, name: str) -> str | None:
    """Read a control-plane secret (reserved AGENTHOOK_* namespace) host-side.
    These are read by agenthook itself and never reach the agent runtime."""
    if is_agent_visible(name):
        raise SecretsError(f"{name!r} is not a control-plane secret (missing {RESERVED_PREFIX} prefix)")
    try:
        return get_backend(inst).get(inst, name)
    except Exception:
        return None
