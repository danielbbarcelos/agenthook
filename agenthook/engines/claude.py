"""Claude Code adapter — the reference engine (DESIGN.md §16)."""

from __future__ import annotations

import json

from ..errors import ClassifiedError, ErrorClass, classify_text
from ..instances import Instance
from ..models import Mode, Result, Usage
from .base import Capabilities, Engine, RunSpec


class ClaudeEngine(Engine):
    name = "claude"
    binary = "claude"
    context_filename = "CLAUDE.md"
    capabilities = Capabilities(
        plan_mode=True,
        json_output=True,
        mcp=True,
        resume=True,
        cost=True,
        vision=True,
        allowed_tools=True,
    )

    def build_argv(self, spec: RunSpec) -> list[str]:
        argv = [self.binary, "-p", spec.prompt, "--output-format", "stream-json", "--verbose"]

        # Mode -> permission flags.
        if spec.mode is Mode.PLAN:
            argv += ["--permission-mode", "plan"]
        elif spec.mode is Mode.AUTO:
            if spec.sandbox:
                argv += ["--dangerously-skip-permissions"]
            else:
                argv += ["--permission-mode", "acceptEdits"]

        if spec.model:
            argv += ["--model", spec.model]
        if spec.max_turns:
            argv += ["--max-turns", str(spec.max_turns)]
        if spec.allowed_tools:
            argv += ["--allowedTools", ",".join(spec.allowed_tools)]
        if spec.disallowed_tools:
            argv += ["--disallowedTools", ",".join(spec.disallowed_tools)]
        if spec.resume_session_id:
            argv += ["--resume", spec.resume_session_id]
        argv += spec.extra_args
        return argv

    def auth_env_names(self, inst: Instance) -> list[str]:
        if inst.engine_auth == "subscription":
            return []  # uses mounted ~/.claude credentials
        return ["ANTHROPIC_API_KEY"]

    def parse_output(self, stdout, stderr, exit_code):
        result = Result(raw=stdout)
        final: dict | None = None
        files: set[str] = set()

        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "result":
                final = evt
            # Track edited files from tool_use assistant events when present.
            if etype == "assistant":
                for block in evt.get("message", {}).get("content", []) or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        inp = block.get("input", {}) or {}
                        path = inp.get("file_path") or inp.get("path")
                        if path:
                            files.add(str(path))

        if final is not None:
            result.text = final.get("result", "") or ""
            result.session_id = final.get("session_id")
            result.usage = _usage_from(final)
            result.files_changed = sorted(files)
            if final.get("is_error") or final.get("subtype") not in (None, "success"):
                subtype = final.get("subtype", "")
                if "max_turns" in subtype:
                    err = ClassifiedError(ErrorClass.ENGINE_CRASH, "reached max turns")
                else:
                    err = classify_text(result.text or stderr, exit_code=exit_code)
                return result, err
            return result, None

        # No result event: classify from whatever we have.
        if exit_code == 0:
            # Engine ran but produced no parseable result.
            return result, ClassifiedError(ErrorClass.BAD_OUTPUT, "no result event in output")
        return result, classify_text((stderr or "") + "\n" + (stdout or ""), exit_code=exit_code)


def _usage_from(final: dict) -> Usage:
    usage = final.get("usage", {}) or {}
    return Usage(
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cache_read=usage.get("cache_read_input_tokens"),
        cache_write=usage.get("cache_creation_input_tokens"),
        cost_usd=final.get("total_cost_usd"),
        num_turns=final.get("num_turns"),
        model=final.get("model"),
        duration_s=(final.get("duration_ms") or 0) / 1000 or None,
    )
