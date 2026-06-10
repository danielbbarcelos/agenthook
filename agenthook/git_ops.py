"""Git worktree / branch / commit / push / PR helpers (DESIGN.md §22).

A per-instance mirror clone lives in ``~/.agenthook/repos/<instance>`` and is
kept fresh with ``git fetch``. Each job gets its own ``git worktree`` so runs
never collide on the working tree. PRs are opened via the ``gh`` CLI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

from . import paths
from .instances import Instance


class GitError(Exception):
    pass


def _run(args: list[str], cwd: str | Path | None = None, env: Mapping[str, str] | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"{' '.join(args)} failed (exit {proc.returncode}):\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def ensure_mirror(inst: Instance, env: Mapping[str, str] | None = None) -> Path:
    if not inst.repo:
        raise GitError(f"instance {inst.name!r} has no repo configured")
    path = paths.repos_dir() / inst.name
    if not (path / ".git").exists():
        _run(["git", "clone", inst.repo, str(path)], env=env)
    else:
        _run(["git", "fetch", "--all", "--prune"], cwd=path, env=env)
    return path


def create_worktree(inst: Instance, job_id: str, base: str | None = None) -> Path:
    mirror = ensure_mirror(inst)
    base = base or inst.branch_base
    wt = paths.work_dir() / job_id
    if wt.exists():
        remove_worktree(inst, wt)
    _run(["git", "worktree", "add", "--force", "--detach", str(wt), f"origin/{base}"], cwd=mirror)
    return wt


def remove_worktree(inst: Instance, wt: str | Path) -> None:
    mirror = paths.repos_dir() / inst.name
    try:
        _run(["git", "worktree", "remove", "--force", str(wt)], cwd=mirror)
    except GitError:
        # Best effort — fall back to a plain rmtree if git can't.
        import shutil

        shutil.rmtree(wt, ignore_errors=True)


def has_changes(wt: str | Path) -> bool:
    return bool(_run(["git", "status", "--porcelain"], cwd=wt))


def diff(wt: str | Path) -> str:
    _run(["git", "add", "-A"], cwd=wt)
    return _run(["git", "diff", "--cached"], cwd=wt)


def commit_branch(
    wt: str | Path, branch: str, message: str, env: Mapping[str, str] | None = None
) -> None:
    _run(["git", "checkout", "-B", branch], cwd=wt)
    _run(["git", "add", "-A"], cwd=wt)
    _run(
        [
            "git",
            "-c",
            "user.name=agenthook",
            "-c",
            "user.email=agenthook@localhost",
            "commit",
            "-m",
            message,
        ],
        cwd=wt,
    )


def push(wt: str | Path, branch: str, env: Mapping[str, str] | None = None) -> None:
    _run(["git", "push", "--force-with-lease", "-u", "origin", branch], cwd=wt, env=env)


def open_pr(
    wt: str | Path,
    *,
    base: str,
    title: str,
    body: str,
    env: Mapping[str, str] | None = None,
) -> str:
    """Open a PR with ``gh`` and return its URL."""
    return _run(
        ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
        cwd=wt,
        env=env,
    )
