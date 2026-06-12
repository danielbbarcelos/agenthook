import pytest

from agenthook import secrets
from agenthook.instances import Instance, save
from agenthook.secrets import SecretsError


def test_key_generation_and_immutability(instance):
    # generated in fixture; a second generation must refuse
    with pytest.raises(SecretsError):
        secrets.generate_key(instance)


def test_encryption_roundtrip_and_flag(instance):
    b = secrets.get_backend(instance)
    b.set(instance, "API_KEY", "super-secret", secret=True)
    b.set(instance, "LOG_LEVEL", "debug", secret=False)
    items = {e.name: e for e in b.items(instance)}
    assert items["API_KEY"].value == "super-secret"
    assert items["API_KEY"].secret is True
    assert items["LOG_LEVEL"].secret is False


def test_env_blob_is_encrypted_on_disk(instance, tmp_path):
    b = secrets.get_backend(instance)
    b.set(instance, "API_KEY", "plaintext-leak-check", secret=True)
    from agenthook import paths

    blob = (paths.instance_dir("demo") / "env.enc").read_bytes()
    assert b"plaintext-leak-check" not in blob


def test_obfuscate_hides_value():
    assert secrets.obfuscate("sk-ant-1234")[:2] == "••"
    assert secrets.obfuscate("sk-ant-1234").endswith("1234")


def test_resolve_env_returns_real_values(instance):
    b = secrets.get_backend(instance)
    b.set(instance, "X", "1", secret=True)
    b.set(instance, "Y", "2", secret=False)
    assert secrets.resolve_env(instance) == {"X": "1", "Y": "2"}


def test_is_agent_visible_reserved_prefix():
    # agenthook's own control-plane namespace is hidden from the agent runtime
    assert secrets.is_agent_visible("AGENTHOOK_HEADER_X_API_KEY") is False
    assert secrets.is_agent_visible("agenthook_anything") is False
    # tool credentials the agent needs stay visible
    assert secrets.is_agent_visible("GH_TOKEN") is True
    assert secrets.is_agent_visible("DB_PRODUCTION_HOST") is True


def test_resolve_env_excludes_control_plane_secrets(instance):
    b = secrets.get_backend(instance)
    b.set(instance, "GH_TOKEN", "ghp_real", secret=True)
    b.set(instance, "AGENTHOOK_HEADER_X_API_KEY", "webhook-secret", secret=True)
    env = secrets.resolve_env(instance)
    assert env == {"GH_TOKEN": "ghp_real"}  # webhook auth secret never reaches the agent
    # but it is still retrievable for agenthook's own webhook auth
    assert b.get(instance, "AGENTHOOK_HEADER_X_API_KEY") == "webhook-secret"


def test_nonsecret_env_excludes_control_plane(instance):
    from agenthook.runner import _nonsecret_env

    b = secrets.get_backend(instance)
    b.set(instance, "LOG_LEVEL", "debug", secret=False)
    b.set(instance, "AGENTHOOK_FLAG", "x", secret=False)
    assert _nonsecret_env(instance) == {"LOG_LEVEL": "debug"}


def test_env_backend_reads_process_env(monkeypatch):
    inst = Instance(name="envinst", secrets_backend="env")
    save(inst)
    monkeypatch.setenv("AGENTHOOK_ENVINST_TOKEN", "from-env")
    assert secrets.get_backend(inst).get(inst, "TOKEN") == "from-env"
