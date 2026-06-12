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
    # the operator guardrail rides along on every run
    i = out["argv"].index("--append-system-prompt")
    assert out["argv"][i + 1] == runner._AGENT_GUARDRAIL


def test_agent_guardrail_covers_all_sections():
    """The guardrail is assembled from four parts — confidentiality, anti-exfil,
    database safety, injection resistance. Guard against one being dropped."""
    g = runner._AGENT_GUARDRAIL
    for part in (
        runner._GUARDRAIL_CONFIDENTIALITY,
        runner._GUARDRAIL_ANTI_EXFIL,
        runner._GUARDRAIL_DATA_SAFETY,
        runner._GUARDRAIL_INJECTION,
    ):
        assert part and part in g
    assert "DATABASE SAFETY" in g
    assert "WHERE" in g  # mass-destructive SQL rule
    assert "base64" in g  # derived-disclosure rule
    assert "commit messages" in g  # exfil-via-deliverable rule
