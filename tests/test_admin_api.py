import pytest
from fastapi.testclient import TestClient

from agenthook import config
from agenthook.server import create_app


@pytest.fixture
def admin():
    cfg = config.load_config()
    cfg.use_docker = False
    config.save_config(cfg)
    token = cfg.admin_token
    with TestClient(create_app()) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


def _create(c, name="bugbot", **extra):
    body = {"name": name, "repos": [{"url": "git@github.com:me/app.git"}], "deliverable": "pr"}
    body.update(extra)
    return c.post("/admin/instances", json=body)


# --- auth -------------------------------------------------------------------


def test_token_required():
    with TestClient(create_app()) as c:
        assert c.get("/admin/instances").status_code == 401
        assert c.get("/admin/instances", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_loopback_only_blocks_remote():
    # admin_remote defaults to False: a non-loopback client is refused even with
    # a valid token.
    cfg = config.load_config()
    with TestClient(create_app(), client=("203.0.113.5", 9000)) as c:
        r = c.get("/admin/instances", headers={"Authorization": f"Bearer {cfg.admin_token}"})
        assert r.status_code == 403


# --- instances CRUD ---------------------------------------------------------


def test_instance_crud(admin):
    assert admin.get("/admin/instances").json() == []

    r = _create(admin)
    assert r.status_code == 201
    assert r.json()["encryption_key"]  # shown once

    assert _create(admin).status_code == 409  # duplicate

    got = admin.get("/admin/instances/bugbot").json()
    assert got["deliverable"] == "pr"

    admin.patch("/admin/instances/bugbot", json={"deliverable": "analysis"})
    assert admin.get("/admin/instances/bugbot").json()["deliverable"] == "analysis"

    assert admin.post("/admin/instances/bugbot/pause", json={"reason": "x"}).json()["paused"] is True
    assert admin.post("/admin/instances/bugbot/resume").json()["paused"] is False

    assert admin.delete("/admin/instances/bugbot").status_code == 204
    assert admin.get("/admin/instances/bugbot").status_code == 404


def test_invalid_name_422(admin):
    assert _create(admin, name="Bad Name").status_code == 422


# --- env masking ------------------------------------------------------------


def test_env_masked(admin):
    _create(admin)
    admin.put("/admin/instances/bugbot/env/ANTHROPIC_API_KEY", json={"value": "sk-ant-secret-1234", "secret": True})
    items = admin.get("/admin/instances/bugbot/env").json()
    entry = next(e for e in items if e["name"] == "ANTHROPIC_API_KEY")
    assert "sk-ant-secret" not in entry["value"]
    assert entry["value"].endswith("1234")  # masked, recognizable tail
    # non-secret is shown in cleartext (parity with `env list`)
    admin.put("/admin/instances/bugbot/env/REGION", json={"value": "us-east-1", "secret": False})
    items = admin.get("/admin/instances/bugbot/env").json()
    assert next(e for e in items if e["name"] == "REGION")["value"] == "us-east-1"


# --- guardrails (append-only) ----------------------------------------------


def test_guardrails_append_only(admin):
    _create(admin)
    ok = admin.put(
        "/admin/instances/bugbot/guardrails",
        json={"extra": "Never touch prod.", "force_read_only": True},
    )
    assert ok.status_code == 200
    # an unknown/relaxing key is rejected by validation
    bad = admin.put("/admin/instances/bugbot/guardrails", json={"confidentiality": False})
    assert bad.status_code == 422


def test_guardrail_layering_in_prompt(admin):
    from agenthook import instances, runner

    _create(admin)
    admin.put("/admin/instances/bugbot/guardrails", json={"extra": "INSTANCE_RULE_XYZ"})
    inst = instances.load("bugbot")
    text = runner.build_guardrail(inst)
    # instance addendum present AND baseline still there, baseline last
    assert "INSTANCE_RULE_XYZ" in text
    assert "SECURITY DIRECTIVE" in text
    assert text.index("INSTANCE_RULE_XYZ") < text.index("SECURITY DIRECTIVE")
    # with no overlay, identical to the global baseline
    plain = instances.Instance(name="x")
    assert runner.build_guardrail(plain) == runner._AGENT_GUARDRAIL


# --- skills delivery --------------------------------------------------------


def test_skills_crud_and_delivery(admin, tmp_path):
    from agenthook import instances
    from agenthook.engines import get_engine

    _create(admin)
    admin.put("/admin/instances/bugbot/skills/triage", json={"body": "---\nname: triage\n---\nDo triage."})
    assert admin.get("/admin/instances/bugbot/skills").json() == ["triage"]
    assert "Do triage." in admin.get("/admin/instances/bugbot/skills/triage").json()["body"]

    # materialization writes <skills_dir>/<name>/SKILL.md into the workspace
    inst = instances.load("bugbot")
    engine = get_engine(inst.engine)
    wt = tmp_path / "wt"
    skills_root = wt / engine.skills_dir
    for sname, body in inst.skills.items():
        d = skills_root / sname
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(body)
    assert (wt / ".claude/skills/triage/SKILL.md").read_text().endswith("Do triage.")

    assert admin.delete("/admin/instances/bugbot/skills/triage").status_code == 204
    assert admin.get("/admin/instances/bugbot/skills").json() == []


# --- global config ----------------------------------------------------------


def test_config_masked_and_patch(admin):
    cfg = admin.get("/admin/config").json()
    assert cfg["admin_token"].startswith("••")  # masked
    assert cfg["approval_secret"].startswith("••")
    admin.patch("/admin/config", json={"admin_remote": True})
    assert config.load_config().admin_remote is True
