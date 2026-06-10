"""Aider adapter (DESIGN.md §16). No structured output -> cost is unknown."""

from __future__ import annotations

from ..errors import classify_text
from ..instances import Instance
from ..models import Deliverable, Result, Usage
from .base import Capabilities, Engine, RunSpec


class AiderEngine(Engine):
    name = "aider"
    binary = "aider"
    context_filename = "CONVENTIONS.md"
    capabilities = Capabilities(
        plan_mode=False, json_output=False, mcp=False, resume=False, cost=False, vision=False
    )

    def build_argv(self, spec: RunSpec) -> list[str]:
        argv = [self.binary, "--message", spec.prompt, "--yes", "--no-stream"]
        if spec.model:
            argv += ["--model", spec.model]
        if spec.deliverable in (Deliverable.ANALYSIS, Deliverable.ACTION):
            argv += ["--no-auto-commits"]
        argv += spec.extra_args
        return argv

    def auth_env_names(self, inst: Instance) -> list[str]:
        # Aider auth depends on the underlying model provider; leave to env vars.
        return []

    def parse_output(self, stdout, stderr, exit_code):
        result = Result(raw=stdout, text=(stdout or "").strip())
        # No token reporting available — honestly report unknown cost.
        result.usage = Usage(cost_usd=None)
        if exit_code != 0:
            return result, classify_text((stderr or "") + (stdout or ""), exit_code=exit_code)
        return result, None
