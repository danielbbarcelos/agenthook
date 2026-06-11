"""Interactive isolated sessions for an instance (DESIGN.md §5, decision #7).

The instance *is* the container: ``shell``/``login`` drop you INTO an ephemeral
container (``docker run --rm -it``) with a distinct hostname, the repo pool checked
out at ``/workspace`` and the instance's own auth mounted — so it's visually obvious
where you are, and nothing leaks from the host. Auth persists across the ephemeral
containers via the per-instance auth dir (bind-mounted), so a ``login`` sticks.

When ``use_docker`` is off there's a host fallback (a plain bash/login in a prepared
workspace) — convenient, but not the full isolation the container gives.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from . import git_ops, instances, paths, secrets
from .config import load_config
from .engines import get_engine
from .models import Deliverable, Job
from .runner import RunContext, _nonsecret_env, _prepare_workspace, _process_env

_AUTH_MOUNT = "/agenthook-auth"


def login(inst_name: str, *, exec_replace: bool = False) -> int | None:
    inst = instances.load(inst_name)
    cfg = load_config()
    if cfg.use_docker:
        return _docker_session(inst, cfg, kind="login", exec_replace=exec_replace)
    from . import engine_auth

    return engine_auth.login(inst, exec_replace=exec_replace)


def shell(inst_name: str) -> int | None:
    inst = instances.load(inst_name)
    cfg = load_config()
    if cfg.use_docker:
        return _docker_session(inst, cfg, kind="shell")
    return _host_shell(inst, cfg)


# --- internals ---------------------------------------------------------------


def _prepare(inst, cfg, engine) -> RunContext:
    job = Job(instance=inst.name, deliverable=Deliverable.ANALYSIS, prompt="", request={})
    ctx = RunContext(
        job=job, inst=inst, cfg=cfg, engine=engine,
        env_all=secrets.resolve_env(inst), env_nonsecret=_nonsecret_env(inst),
    )
    _prepare_workspace(ctx, require_prompt=False)
    return ctx


def _cleanup(ctx: RunContext) -> None:
    for repo in ctx.repos:
        wt = ctx.repo_dirs.get(repo.name)
        if wt:
            try:
                git_ops.remove_worktree(ctx.inst, repo, wt)
            except Exception:  # noqa: BLE001
                pass
    job_root = paths.work_dir() / ctx.job.id
    if job_root.exists() and job_root.parent.name == "work":
        shutil.rmtree(job_root, ignore_errors=True)


def _frame(inst, engine, cfg, kind: str) -> None:
    label = "shell" if kind == "shell" else "login"
    print(f"\n◇ ephemeral container · {inst.name} · {engine.name}/{inst.engine_auth} · {label}")
    print(f"  image {cfg.docker_image} · the host's ~/.claude is NOT used")
    if kind == "shell":
        print("  type /exit (or exit) to leave · changes don't persist unless committed\n")
    else:
        print("  run /login, then /exit when done\n")


def _docker_session(inst, cfg, *, kind: str, exec_replace: bool = False) -> int | None:
    engine = get_engine(inst.engine)
    auth_dir = paths.auth_dir(inst.name) / engine.name
    auth_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["docker", "run", "--rm", "-it", "--hostname", inst.name]
    auth_env = engine.auth_config_env(inst, auth_dir)
    if auth_env:
        cmd += ["-v", f"{auth_dir}:{_AUTH_MOUNT}"]
        for k in auth_env:
            cmd += ["-e", f"{k}={_AUTH_MOUNT}"]
    for k, v in secrets.resolve_env(inst).items():
        cmd += ["-e", f"{k}={v}"]
    limits = inst.limits if isinstance(inst.limits, dict) else {}
    if limits.get("cpus"):
        cmd += ["--cpus", str(limits["cpus"])]
    if limits.get("memory"):
        cmd += ["--memory", str(limits["memory"])]

    ctx = None
    if kind == "shell":
        ctx = _prepare(inst, cfg, engine)
        cmd += ["-v", f"{ctx.wt}:/workspace"]
        inner = ["bash"]
    else:  # login
        inner = engine.login_argv(auth_dir)
        if not inner:
            raise RuntimeError(f"engine {engine.name!r} has no interactive login; use api-key.")

    cmd += ["-w", "/workspace", cfg.docker_image, *inner]
    _frame(inst, engine, cfg, kind)
    try:
        return _run_tty(cmd, exec_replace=exec_replace)
    finally:
        if ctx is not None:
            _cleanup(ctx)


def _host_shell(inst, cfg) -> int | None:
    engine = get_engine(inst.engine)
    ctx = _prepare(inst, cfg, engine)
    env = _process_env(ctx)
    print(f"\n┌─ shell (host, NOT isolated): {inst.name} ─┐")
    print(f"│ workspace: {ctx.wt}")
    print("└" + "─" * 40)
    try:
        return subprocess.run(["bash"], cwd=str(ctx.wt), env=env).returncode
    finally:
        _cleanup(ctx)


def _run_tty(cmd: list[str], *, exec_replace: bool) -> int | None:
    if exec_replace:
        os.execvp(cmd[0], cmd)  # never returns
    return subprocess.run(cmd).returncode
