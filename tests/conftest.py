import pytest

from agenthook import ratelimit, store


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Give every test a fresh AGENTHOOK_HOME and a fresh SQLite schema."""
    monkeypatch.setenv("AGENTHOOK_HOME", str(tmp_path))
    store._initialized_paths.discard(str(tmp_path / "jobs.db"))
    ratelimit.reset()  # rate-limit buckets are process-global; isolate per test
    yield


@pytest.fixture
def instance(tmp_path):
    from agenthook import secrets
    from agenthook.instances import Instance, save

    inst = Instance(name="demo", engine="claude", deliverable="analysis")
    save(inst)
    secrets.generate_key(inst)
    return inst
