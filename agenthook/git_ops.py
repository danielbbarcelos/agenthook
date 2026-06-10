"""Git worktree / branch / commit / push / PR helpers (DESIGN.md §22).

A per-repo mirror clone lives in ``~/.agenthook/repos/<instance>/<repo>`` and is
kept fresh with ``git fetch``. Each job gets its own ``git worktree`` so runs
never collide on the working tree. When a job uses several repos they are
checked out side by side under the job's workspace. PRs are opened via the
``gh`` CLI, one per repository that actually changed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

from . import paths
from .instances import Instance, RepoRef


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


def mirror_path(inst: Instance, repo: RepoRef) -> Path:
    return paths.repos_dir() / inst.name / repo.name


def ensure_mirror(inst: Instance, repo: RepoRef, env: Mapping[str, str] | None = None) -> Path:
    path = mirror_path(inst, repo)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", repo.url, str(path)], env=env)
    else:
        _run(["git", "fetch", "--all", "--prune"], cwd=path, env=env)
    return path


def _resolve_base_ref(
    mirror: Path, base: str | None, env: Mapping[str, str] | None = None
) -> str:
    """Return a checkout-able ref, preferring ``base`` but falling back to the
    remote's actual default branch — repos named ``master`` (or anything other
    than ``main``) would otherwise fail with 'invalid reference: origin/main'."""
    if base:
        try:
            _run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base}"],
                 cwd=mirror, env=env)
            return f"origin/{base}"
        except GitError:
            pass
    # Fall back to origin/HEAD (the remote default branch).
    for _ in range(2):
        try:
            return _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                        cwd=mirror, env=env)
        except GitError:
            # origin/HEAD not set yet — derive it from the remote, then retry.
            try:
                _run(["git", "remote", "set-head", "origin", "--auto"], cwd=mirror, env=env)
            except GitError:
                break
    raise GitError(
        f"could not resolve a base branch in {mirror} "
        f"(tried {base!r} and origin/HEAD); is the repo empty?"
    )


def create_worktree(
    inst: Instance,
    repo: RepoRef,
    dest: str | Path,
    base: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    mirror = ensure_mirror(inst, repo, env)
    ref = _resolve_base_ref(mirror, base or repo.branch_base, env)
    dest = Path(dest)
    if dest.exists():
        remove_worktree(inst, repo, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "--force", "--detach", str(dest), ref], cwd=mirror, env=env)
    return dest


def remove_worktree(inst: Instance, repo: RepoRef, wt: str | Path) -> None:
    mirror = mirror_path(inst, repo)
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
