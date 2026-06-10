"""OpenAI Codex CLI adapter (DESIGN.md §16). Best-effort; reference is claude."""

from __future__ import annotations

import json

from ..errors import ClassifiedError, ErrorClass, classify_text
from ..instances import Instance
from ..models import Result, Usage
from .base import Capabilities, Engine, RunSpec


class CodexEngine(Engine):
    name = "codex"
    binary = "codex"
    context_filename = "AGENTS.md"
    capabilities = Capabilities(
        plan_mode=False, json_output=True, mcp=True, resume=True, cost=True, vision=True
    )

    def build_argv(self, spec: RunSpec) -> list[str]:
        argv = [self.binary, "exec", spec.prompt, "--json"]
        if spec.model:
            argv += ["--model", spec.model]
        if spec.resume_session_id:
            argv += ["resume", spec.resume_session_id]  # codex exec resume <id>
        argv += spec.extra_args
        return argv

    def auth_env_names(self, inst: Instance) -> list[str]:
        return [] if inst.engine_auth == "subscription" else ["OPENAI_API_KEY"]

    def parse_output(self, stdout, stderr, exit_code):
        result = Result(raw=stdout)
        last_msg = ""
        usage = Usage()
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") in ("message", "agent_message", "item.completed"):
                last_msg = evt.get("text") or evt.get("message") or last_msg
            if "usage" in evt:
                u = evt["usage"]
                usage.input_tokens = u.get("input_tokens", usage.input_tokens)
                usage.output_tokens = u.get("output_tokens", usage.output_tokens)
            if evt.get("session_id"):
                result.session_id = evt["session_id"]
        result.text = last_msg
        result.usage = usage
        if exit_code != 0:
            return result, classify_text((stderr or "") + (stdout or ""), exit_code=exit_code)
        if not last_msg:
            return result, ClassifiedError(ErrorClass.BAD_OUTPUT, "no message in codex output")
        return result, None
