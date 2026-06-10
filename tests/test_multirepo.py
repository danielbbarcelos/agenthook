"""Multi-repo pool: an instance declares 0..N repos and each job selects a
subset (DESIGN.md §2). Covers resolution/selection, the webhook validation,
and the side-by-side checkout + per-repo deliverable."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agenthook import config, secrets, store
from agenthook.instances import Instance, InstanceError, save
from agenthook.server import create_app


# --- selection / resolution -------------------------------------------------


def test_legacy_single_repo_resolves():
    inst = Instance(name="legacy", repo="https://github.com/org/api.git")
    refs = inst.resolved_repos()
    assert len(refs) == 1
    assert refs[0].name == "api"
    assert refs[0].url == "https://github.com/org/api.git"


def test_pool_resolution_and_names():
    inst = Instance(
        name="multi",
        repos=[
            {"url": "https://github.com/org/api.git"},
            {"name": "web", "url": "git@github.com:org/frontend.git", "branch_base": "develop"},
        ],
    )
    assert inst.repo_names() == ["api", "web"]
    web = inst.resolved_repos()[1]
    assert web.branch_base == "develop"


def test_select_subset_all_and_none():
    inst = Instance(
        name="multi",
        repos=[{"name": "api", "url": "u1"}, {"name": "web", "url": "u2"}],
    )
    assert [r.name for r in inst.select_repos(None)] == ["api", "web"]  # all
    assert inst.select_repos([]) == []  # none (0 repos)
    assert [r.name for r in inst.select_repos(["web"])] == ["web"]  # subset


def test_select_unknown_repo_raises():
    inst = Instance(name="multi", repos=[{"name": "api", "url": "u1"}])
    with pytest.raises(InstanceError):
        inst.select_repos(["nope"])


def test_duplicate_repo_name_rejected():
    inst = Instance(name="multi", repos=[{"name": "x", "url": "a"}, {"name": "x", "url": "b"}])
    with pytest.raises(InstanceError):
        inst.validate()


# --- webhook validation ------------------------------------------------------


@pytest.fixture
def client():
    cfg = config.load_config()
    cfg.use_docker = False
    config.save_config(cfg)
    inst = Instance(
        name="api",
        engine="claude",
        engine_auth="subscription",
        deliverable="analysis",
        repos=[{"name": "api", "url": "u1"}, {"name": "web", "url": "u2"}],
        webhook_auth={"schemes": ["bearer"]},
        limits={"concurrency": 0},
    )
    save(inst)
    secrets.generate_key(inst)
    secrets.get_backend(inst).set(inst, "AGENTHOOK_WEBHOOK_TOKEN", "tok", True)
    with TestClient(create_app()) as c:
        yield c


AUTH = {"Authorization": "Bearer tok"}


def test_hook_rejects_unknown_repo(client):
    r = client.post("/hook/api", json={"prompt": "x", "repos": ["ghost"]}, headers=AUTH)
    assert r.status_code == 422
    assert "ghost" in r.json()["error"]


def test_hook_accepts_known_subset(client):
    r = client.post("/hook/api", json={"prompt": "x", "repos": ["web"]}, headers=AUTH)
    assert r.status_code == 202
    job = store.get_job(r.json()["job_id"])
    assert job.request["repos"] == ["web"]


# --- side-by-side checkout + per-repo deliverable ----------------------------


def _make_remote(path: Path) -> str:
    """A tiny local git repo with one commit on main, usable as a clone URL."""
    path.mkdir(parents=True)
    g = ["git", "-C", str(path)]
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(g + ["config", "user.email", "t@t"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    (path / "README.md").write_text("seed\n")
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "seed"], check=True)
    return str(path)


def test_multi_checkout_side_by_side_and_patch(tmp_path, monkeypatch):
    from agenthook.config import Config
    from agenthook.models import Deliverable, Job
    from agenthook.runner import RunContext, _apply_deliverable, _prepare_workspace
    from agenthook.engines import get_engine

    api_url = _make_remote(tmp_path / "remote_api")
    web_url = _make_remote(tmp_path / "remote_web")
    inst = Instance(
        name="multi",
        engine="claude",
        engine_auth="subscription",
        deliverable="patch",
        repos=[{"name": "api", "url": api_url}, {"name": "web", "url": web_url}],
    )
    save(inst)
    secrets.generate_key(inst)

    job = Job(instance="multi", deliverable=Deliverable.PATCH, prompt="x", request={"prompt": "x"})
    ctx = RunContext(
        job=job, inst=inst, cfg=Config(use_docker=False), engine=get_engine("claude"),
        env_all={}, env_nonsecret={},
    )
    _prepare_workspace(ctx)

    # Both repos checked out side by side under the job root.
    assert set(ctx.repo_dirs) == {"api", "web"}
    assert (ctx.repo_dirs["api"] / "README.md").exists()
    assert (ctx.repo_dirs["web"] / "README.md").exists()
    assert ctx.wt.name == job.id  # multi -> root is the job dir

    # The agent changes only one repo.
    (ctx.repo_dirs["api"] / "new.txt").write_text("hello\n")
    job.result = None
    _apply_deliverable(ctx)

    patches = job.metadata.get("patches", [])
    assert [p["repo"] for p in patches] == ["api"]  # only the changed repo
    assert "new.txt" in Path(patches[0]["path"]).read_text()
