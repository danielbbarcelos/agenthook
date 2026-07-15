"""Egress lockdown: instance allowlist validation, engine model routing,
_docker_wrap grant application, and (opt-in) a real-Docker fail-closed check."""

import os
import shutil

import pytest

from agenthook.config import Config
from agenthook.egress import EgressGrant
from agenthook.egress.broker import _host_allowed
from agenthook.engines import get_engine
from agenthook.instances import Instance, InstanceError
from agenthook.models import Deliverable, Job
from agenthook.runner import RunContext, _docker_wrap


# --- instance allowlist (append-only) ---------------------------------------


def test_egress_allow_roundtrips():
    inst = Instance(name="e", engine="claude", egress={"allow": ["db.internal", "*.corp"]})
    inst.validate()
    assert inst.egress_allow() == ["db.internal", "*.corp"]


def test_egress_rejects_unknown_key():
    inst = Instance(name="e", engine="claude", egress={"deny": ["x"]})
    with pytest.raises(InstanceError):
        inst.validate()


def test_egress_allow_must_be_list_of_str():
    inst = Instance(name="e", engine="claude", egress={"allow": "db.internal"})
    with pytest.raises(InstanceError):
        inst.validate()


# --- engine model routing ----------------------------------------------------


def test_claude_egress_model_apikey_injects_key():
    m = get_engine("claude").egress_model({"ANTHROPIC_API_KEY": "sk-real"})
    assert m.host == "api.anthropic.com"
    assert m.base_url_env == "ANTHROPIC_BASE_URL"
    assert m.inject_value == "sk-real"  # broker injects the real key
    assert m.key_env == "ANTHROPIC_API_KEY"


def test_claude_egress_model_subscription_forwards():
    m = get_engine("claude").egress_model({})  # no api key (subscription)
    assert m.inject_value == ""  # broker forwards the CLI's own auth header


# --- _docker_wrap applies the grant -----------------------------------------


def _ctx(tmp_path, grant):
    inst = Instance(name="api", engine="claude", deliverable="analysis")
    job = Job(instance="api", deliverable=Deliverable.ANALYSIS, prompt="x")
    cfg = Config(use_docker=True)
    ctx = RunContext(
        job=job, inst=inst, cfg=cfg, engine=get_engine("claude"),
        env_all={"ANTHROPIC_API_KEY": "sk-real", "OTHER": "keep"},
        env_nonsecret={},
    )
    ctx.wt = tmp_path
    ctx.egress = grant
    return ctx


def test_docker_wrap_applies_egress_grant(tmp_path):
    grant = EgressGrant(
        token="tok", network="agh-net", allow=["api.anthropic.com"],
        container_env={"ANTHROPIC_BASE_URL": "http://egress:8080/tok",
                       "ANTHROPIC_API_KEY": "agenthook-egress"},
        strip_env=["ANTHROPIC_API_KEY"],
    )
    argv = _docker_wrap(_ctx(tmp_path, grant), ["claude", "-p", "hi"])
    joined = " ".join(argv)
    assert "--network agh-net" in joined
    # the real key is stripped; only the dummy is present
    assert "ANTHROPIC_API_KEY=sk-real" not in joined
    assert "ANTHROPIC_API_KEY=agenthook-egress" in joined
    assert "ANTHROPIC_BASE_URL=http://egress:8080/tok" in joined
    assert "OTHER=keep" in joined  # non-stripped secrets still injected


def test_docker_wrap_no_grant_keeps_default_bridge(tmp_path):
    argv = _docker_wrap(_ctx(tmp_path, None), ["claude", "-p", "hi"])
    joined = " ".join(argv)
    assert "--network" not in joined
    assert "ANTHROPIC_API_KEY=sk-real" in joined  # no egress -> key injected as before


# --- broker host allowlist matching -----------------------------------------


def test_host_allowed_globs():
    assert _host_allowed("api.anthropic.com", ["api.anthropic.com"])
    assert _host_allowed("db.corp", ["*.corp"])
    assert not _host_allowed("evil.com", ["api.anthropic.com", "*.corp"])


# --- opt-in real-Docker fail-closed check -----------------------------------


@pytest.mark.skipif(
    not (shutil.which("docker") and os.environ.get("AGENTHOOK_DOCKER_IT") == "1"),
    reason="set AGENTHOOK_DOCKER_IT=1 with Docker to run the live egress check",
)
def test_egress_fail_closed_live():
    import subprocess

    from agenthook import egress

    net, ctrl = "agh-egress-pytest", 8092

    def sh(a):
        return subprocess.run(a, capture_output=True, text=True)

    def cleanup():
        sh(["docker", "rm", "-f", egress.BROKER_NAME])
        sh(["docker", "network", "rm", net])
        sh(["docker", "network", "rm", f"{net}-out"])

    cleanup()
    try:
        egress.ensure_broker(net, ctrl_host_port=ctrl)
        r = sh(["docker", "run", "--rm", "--network", net,
                "curlimages/curl:latest", "-sS", "--max-time", "5", "https://1.1.1.1"])
        assert r.returncode != 0, "container reached the internet — egress NOT locked"
    finally:
        cleanup()
