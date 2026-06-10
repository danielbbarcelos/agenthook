"""Per-instance *engine* authentication — isolated login / logout / status.

Distinct from ``auth.py`` (which guards the webhook endpoint). Here each instance
authenticates its coding engine on its own, under ``~/.agenthook/auth/<instance>/``;
the host's ambient login (``~/.claude``) is never used. Shared by the CLI
(``agenthook login``) and the guided TUI (instance › autenticação).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import paths
from .engines import get_engine
from .instances import Instance


def auth_dir_for(inst: Instance) -> Path:
    d = paths.auth_dir(inst.name) / get_engine(inst.engine).name
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_authenticated(inst: Instance) -> bool | None:
    """True/False for dir-credential engines; None when auth isn't dir-based
    (e.g. api-key, which lives in the instance's secrets)."""
    engine = get_engine(inst.engine)
    files = engine.credential_files(paths.auth_dir(inst.name) / engine.name)
    if not files:
        return None
    return any(Path(f).exists() for f in files)


def login_env(inst: Instance) -> tuple[list[str], dict[str, str]]:
    """argv + env to interactively log this instance in, isolated from the host."""
    engine = get_engine(inst.engine)
    auth_dir = auth_dir_for(inst)
    argv = engine.login_argv(auth_dir)
    if not argv:
        raise RuntimeError(f"engine {engine.name!r} não tem login interativo; use api-key.")
    env = dict(os.environ)
    env.update(engine.auth_config_env(inst, auth_dir))
    return argv, env


def login(inst: Instance, *, exec_replace: bool = False) -> int | None:
    """Run the isolated interactive login. ``exec_replace`` hands the terminal
    over via execvpe (CLI); otherwise run as a child and return its exit code."""
    argv, env = login_env(inst)
    if exec_replace:
        os.execvpe(argv[0], argv, env)  # never returns
    return subprocess.run(argv, env=env).returncode


def logout(inst: Instance) -> bool:
    """Wipe the instance's isolated auth/config dir (logout + clear all state)."""
    d = paths.auth_dir(inst.name) / get_engine(inst.engine).name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False
