"""Verification / self-heal loop (DESIGN.md §18).

Runs the instance's ``verify`` checks (tests/lint/typecheck) after the agent
finishes. On failure it feeds the (truncated) output back to the agent to fix,
up to a cap on iterations *and* cost, with a "same failure twice → give up"
guard. Only applies to code-mutating deliverables; the caller enforces that.

To avoid a dependency cycle with the runner, the side-effecting operations
(running a shell command, re-running the engine) are injected as callables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .instances import Instance
from .models import Usage

#: (exit_code, combined_output)
ExecFn = Callable[[str], tuple[int, str]]
#: re-run the engine with a fix prompt, returning its Usage
FixFn = Callable[[str], Usage]
LogFn = Callable[[str], None]


@dataclass
class VerifyOutcome:
    ran: bool
    passed: bool
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    last_failures: str = ""


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n...[truncated {len(text) - limit} chars]...\n{tail}"


def run(
    inst: Instance,
    *,
    exec_cmd: ExecFn,
    run_fix: FixFn,
    log: LogFn = lambda _m: None,
) -> VerifyOutcome:
    cfg = inst.verify or {}
    checks: list[str] = cfg.get("checks", []) or []
    if not checks:
        return VerifyOutcome(ran=False, passed=True)

    max_iter = int(cfg.get("max_fix_iterations", 3))
    max_cost = cfg.get("max_fix_cost_usd")
    setup = cfg.get("setup")

    total = Usage()
    if setup:
        log(f"verify: setup: {setup}")
        exec_cmd(setup)

    prev_failures = None
    for iteration in range(max_iter + 1):
        failures: list[str] = []
        for cmd in checks:
            code, out = exec_cmd(cmd)
            status = "ok" if code == 0 else f"FAILED (exit {code})"
            log(f"verify: check `{cmd}` -> {status}")
            if code != 0:
                failures.append(f"$ {cmd}\n{out}")

        if not failures:
            return VerifyOutcome(ran=True, passed=True, iterations=iteration, usage=total)

        joined = "\n\n".join(failures)
        if iteration >= max_iter:
            return VerifyOutcome(True, False, iteration, total, _truncate(joined))
        if max_cost is not None and (total.cost_usd or 0) >= float(max_cost):
            log(f"verify: cost cap reached (${total.cost_usd:.2f}); giving up")
            return VerifyOutcome(True, False, iteration, total, _truncate(joined))
        if prev_failures == joined:
            log("verify: same failure twice without progress; giving up")
            return VerifyOutcome(True, False, iteration, total, _truncate(joined))
        prev_failures = joined

        fix_prompt = (
            "The following verification checks failed. Fix the code so they all pass. "
            "Do not disable or skip the checks.\n\n" + _truncate(joined)
        )
        log(f"verify: attempting fix (iteration {iteration + 1}/{max_iter})")
        total = total.add(run_fix(fix_prompt))

    return VerifyOutcome(True, False, max_iter, total, "")
