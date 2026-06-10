"""Engine auth isolation: an instance must carry its own credentials and never
inherit whatever is logged in on the host (subscription or api-key)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from agenthook import secrets
from agenthook.config import Config
from agenthook.engines import get_engine
from agenthook.instances import Instance, RepoRef, save
from agenthook.models import Deliverable, Job
from agenthook.runner import RunContext, _process_env


def _ctx(inst: Instance, env_all: dict | None = None) -> RunContext:
    save(inst)
    secrets.generate_key(inst)
    job = Job(instance=inst.name, deliverable=Deliverable.ANALYSIS, prompt="x", request={})
    return RunContext(
        job=job, inst=inst, cfg=Config(use_docker=False), engine=get_engine(inst.engine),
        env_all=env_all or {}, env_nonsecret={},
    )


def test_host_engine_key_does_not_leak(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-HOST-LEAK")
    inst = Instance(name="sub", engine="claude", engine_auth="subscription")
    env = _process_env(_ctx(inst))
    assert "ANTHROPIC_API_KEY" not in env  # host's ambient key must not pass through


def test_subscription_uses_isolated_config_dir(monkeypatch):
    inst = Instance(name="sub2", engine="claude", engine_auth="subscription")
    env = _process_env(_ctx(inst))
    cfg_dir = env["CLAUDE_CONFIG_DIR"]
    assert cfg_dir.endswith("auth/sub2/claude")  # per-instance, not ~/.claude


def test_instance_own_api_key_is_used(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-HOST-LEAK")
    inst = Instance(name="ak", engine="claude", engine_auth="api-key")
    env = _process_env(_ctx(inst, env_all={"ANTHROPIC_API_KEY": "sk-OWN"}))
    assert env["ANTHROPIC_API_KEY"] == "sk-OWN"  # the instance's own secret wins


def _make_remote(path: Path, branch: str) -> str:
    path.mkdir(parents=True)
    g = ["git", "-C", str(path)]
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(g + ["config", "user.email", "t@t"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    (path / "README.md").write_text("seed\n")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "seed"], check=True)
    return str(path)


def test_worktree_falls_back_to_default_branch(tmp_path, monkeypatch):
    """A repo whose default branch is 'master' must still check out even though
    the instance's branch_base default is 'main' (the old origin/main bug)."""
    from agenthook.git_ops import create_worktree

    url = _make_remote(tmp_path / "remote", branch="master")
    inst = Instance(name="legacy", engine="claude", engine_auth="subscription", branch_base="main")
    save(inst)
    repo = RepoRef(name="r", url=url, branch_base="main")  # 'main' does not exist on the remote
    dest = create_worktree(inst, repo, tmp_path / "wt")
    assert (dest / "README.md").exists()
