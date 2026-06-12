from agenthook.engines import available, get_engine
from agenthook.engines.base import RunSpec
from agenthook.models import Deliverable, Mode


def test_registry_has_builtins():
    assert set(available()) >= {"claude", "codex", "gemini", "aider"}


def test_claude_argv_auto_sandbox():
    eng = get_engine("claude")
    argv = eng.build_argv(RunSpec(prompt="hi", mode=Mode.AUTO, sandbox=True))
    assert argv[:3] == ["claude", "-p", "hi"]
    assert "--dangerously-skip-permissions" in argv
    assert "stream-json" in argv


def test_claude_argv_plan_and_model():
    eng = get_engine("claude")
    argv = eng.build_argv(RunSpec(prompt="x", mode=Mode.PLAN, model="claude-opus-4-8"))
    assert "--permission-mode" in argv and "plan" in argv
    assert "--model" in argv and "claude-opus-4-8" in argv


def test_claude_argv_disallows_tools():
    eng = get_engine("claude")
    argv = eng.build_argv(
        RunSpec(prompt="x", deliverable=Deliverable.ANALYSIS, disallowed_tools=["Edit", "Write"])
    )
    assert "--disallowedTools" in argv
    assert "Edit,Write" in argv


def test_claude_argv_appends_system_prompt():
    eng = get_engine("claude")
    argv = eng.build_argv(RunSpec(prompt="x", system_prompt_append="GUARD"))
    assert "--append-system-prompt" in argv
    assert argv[argv.index("--append-system-prompt") + 1] == "GUARD"


def test_claude_argv_omits_system_prompt_when_empty():
    eng = get_engine("claude")
    argv = eng.build_argv(RunSpec(prompt="x"))
    assert "--append-system-prompt" not in argv


def test_claude_parse_stream_json():
    eng = get_engine("claude")
    out = "\n".join(
        [
            '{"type":"assistant","message":{"content":[{"type":"tool_use","input":{"file_path":"a.py"}}]}}',
            '{"type":"result","subtype":"success","is_error":false,"result":"done",'
            '"total_cost_usd":0.12,"num_turns":3,"session_id":"s1",'
            '"usage":{"input_tokens":100,"output_tokens":50}}',
        ]
    )
    res, err = eng.parse_output(out, "", 0)
    assert err is None
    assert res.text == "done"
    assert res.usage.cost_usd == 0.12
    assert res.session_id == "s1"
    assert res.files_changed == ["a.py"]


def test_claude_parse_error_exit():
    eng = get_engine("claude")
    res, err = eng.parse_output("", "401 Unauthorized: invalid api key", 1)
    assert err is not None
    assert err.error_class.value == "AUTH"


def test_capabilities_matrix():
    assert get_engine("claude").capabilities.plan_mode is True
    assert get_engine("codex").capabilities.plan_mode is False
    assert get_engine("aider").capabilities.cost is False
