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
        if spec.stream:
            # emit content_block_delta events so output can be shown token-by-token
            argv += ["--include-partial-messages"]

        # Mode -> permission flags. Every run here is headless (`-p`), so the
        # permission mode must be non-interactive: an unanswered tool-permission
        # prompt hangs the run forever. PLAN emits a plan and exits; AUTO and
        # DEFAULT both run non-interactively (tools stay restricted by
        # --disallowedTools, so read-only deliverables remain read-only).
        if spec.mode is Mode.PLAN:
            argv += ["--permission-mode", "plan"]
        elif spec.sandbox:
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
            return []  # uses the instance's own isolated login (see login_argv)
        return ["ANTHROPIC_API_KEY"]

    def auth_config_env(self, inst: Instance, auth_dir) -> dict[str, str]:
        # Relocate Claude Code's whole config (creds + state) to the instance's
        # own dir; the host's ~/.claude is never read, for either auth mode.
        return {"CLAUDE_CONFIG_DIR": str(auth_dir)}

    def login_argv(self, auth_dir) -> list[str]:
        # Interactive: the user runs /login inside, writing creds into auth_dir.
        return [self.binary]

    def credential_files(self, auth_dir) -> list:
        from pathlib import Path

        return [Path(auth_dir) / ".credentials.json"]

    def stream_text(self, line: str) -> str | None:
        line = line.strip()
        if not line or '"text_delta"' not in line and '"text"' not in line:
            return None
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            return None
        # --include-partial-messages wraps Anthropic stream events.
        ev = evt.get("event") if evt.get("type") == "stream_event" else evt
        if isinstance(ev, dict) and ev.get("type") == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text") or None
        return None

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
