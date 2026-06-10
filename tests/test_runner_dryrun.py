from agenthook import runner, secrets
from agenthook.instances import Instance, save
from agenthook.models import Deliverable, Job, Mode


def test_dry_run_renders_without_executing():
    inst = Instance(
        name="demo",
        engine="claude",
        deliverable="analysis",
        context_template="lang={{ language }} proj={{ env.PROJECT }}",
        templates={"ticket": "ticket #{{ subject_ref.ticket_id }}"},
        mcp={"pg": {"env": {"URL": "{{ env.DB }}"}}},
    )
    save(inst)
    secrets.generate_key(inst)
    b = secrets.get_backend(inst)
    b.set(inst, "ANTHROPIC_API_KEY", "sk", True)
    b.set(inst, "PROJECT", "acme", False)
    b.set(inst, "DB", "postgres://x", True)

    job = Job(
        instance="demo",
        deliverable=Deliverable.ANALYSIS,
        mode=Mode.AUTO,
        request={"request_type": "ticket", "language": "pt-BR", "subject_ref": {"ticket_id": 7}},
    )
    out = runner.dry_run(job)

    assert out["prompt"] == "ticket #7"
    assert "proj=acme" in out["context_file"]["body"]
    assert out["argv"][:3] == ["claude", "-p", "ticket #7"]
    # analysis is read-only -> write tools disallowed
    assert "--disallowedTools" in out["argv"]
    # secrets masked, MCP not leaked
    assert out["env"]["ANTHROPIC_API_KEY"].startswith("•")
    assert out["mcp"]["mcpServers"]["pg"]["env"]["URL"] == "***"
    assert out["guardrails"]["read_only"] is True
    assert out["auth_env_required"] == ["ANTHROPIC_API_KEY"]
