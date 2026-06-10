"""Gemini CLI adapter (DESIGN.md §16). Best-effort; reference is claude."""

from __future__ import annotations

import json

from ..errors import classify_text
from ..instances import Instance
from ..models import Mode, Result, Usage
from .base import Capabilities, Engine, RunSpec


class GeminiEngine(Engine):
    name = "gemini"
    binary = "gemini"
    context_filename = "GEMINI.md"
    capabilities = Capabilities(
        plan_mode=False, json_output=True, mcp=True, resume=False, cost=True, vision=True
    )

    def build_argv(self, spec: RunSpec) -> list[str]:
        argv = [self.binary, "-p", spec.prompt, "--output-format", "json", "--non-interactive"]
        if spec.mode is Mode.AUTO:
            argv += ["--yolo"]
        if spec.model:
            argv += ["-m", spec.model]
        argv += spec.extra_args
        return argv

    def auth_env_names(self, inst: Instance) -> list[str]:
        return [] if inst.engine_auth == "subscription" else ["GEMINI_API_KEY"]

    def parse_output(self, stdout, stderr, exit_code):
        result = Result(raw=stdout)
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            if exit_code != 0:
                return result, classify_text((stderr or "") + (stdout or ""), exit_code=exit_code)
            result.text = stdout.strip()
            return result, None
        result.text = data.get("response", "") if isinstance(data, dict) else str(data)
        stats = (data or {}).get("stats", {}) if isinstance(data, dict) else {}
        tokens = stats.get("tokens", {}) if isinstance(stats, dict) else {}
        result.usage = Usage(
            input_tokens=tokens.get("input"),
            output_tokens=tokens.get("output"),
            model=stats.get("model"),
        )
        if exit_code != 0:
            return result, classify_text((stderr or "") + (stdout or ""), exit_code=exit_code)
        return result, None
