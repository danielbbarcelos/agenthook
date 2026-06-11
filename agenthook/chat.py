"""Interactive chat REPL against an instance (``agenthook enter <name>``).

"Entering" an instance opens a multi-turn conversation with its engine: each
line you type becomes a job on a single persistent session (fixed ``thread_key``),
so context carries across turns via the engine's ``--resume``. The pool repos are
checked out and the instance env is applied, exactly like a webhook-triggered job.

Chat is read-only by default (``analysis`` deliverable) — it's for asking, not
shipping. Slash commands switch repos/deliverable or reset the thread. Shared by
the CLI and the guided TUI; never calls Typer commands in-process.
"""

from __future__ import annotations

import uuid

from . import instances, store
from .models import Deliverable, Job, Mode

_HELP = """[dim]commands:
  /help              this help
  /new               start over (new thread, drops the context)
  /repos a,b         use only these pool repos ('' = none, /repos with no arg = all)
  /deliverable NAME  switch the deliverable (analysis, action, patch, commit, pr)
  /exit  /quit       leave[/]"""


def _session_history(name: str, tk: str, limit: int = 200) -> list[str]:
    """Past user prompts for this thread, oldest → newest, deduped — so ↑ in the
    chat input recalls what was already asked in the session."""
    seen: set[str] = set()
    out: list[str] = []
    for job in reversed(store.list_jobs(instance=name, limit=limit)):
        if job.thread_key == tk and job.prompt and job.prompt not in seen:
            seen.add(job.prompt)
            out.append(job.prompt)
    return out


def _prompt_session(name: str, tk: str):
    """An input prompt with ↑/↓ history, seeded from the thread's past prompts.
    New lines are appended automatically as they're accepted."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    hist = InMemoryHistory()
    for prompt in _session_history(name, tk):
        hist.append_string(prompt)
    return PromptSession(history=hist)


def _flush_input() -> None:
    """Discard anything typed while a turn was running, so stray keystrokes /
    Enters don't auto-submit once the prompt comes back."""
    try:
        import sys
        import termios

        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:  # noqa: BLE001 — non-tty / non-posix
        pass


def _parse_repo_sel(value):
    """None=all, ''=none, 'a,b'=subset — mirrors cli._parse_repo_sel."""
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def repl(
    name: str,
    *,
    repos=None,
    deliverable: str | None = None,
    thread_key: str | None = None,
    console=None,
) -> None:
    from rich.console import Console

    console = console or Console()
    try:
        inst = instances.load(name)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/] {exc}")
        return
    store.init_db()

    tk = thread_key or f"enter-{uuid.uuid4().hex[:8]}"
    deliv = deliverable or "analysis"
    sel = repos  # None=all, []=none, list=subset

    pool = inst.repo_names()
    if sel is None:
        shown_repos = ", ".join(pool) if pool else "none"
    elif sel == []:
        shown_repos = "none"
    else:
        shown_repos = ", ".join(sel)

    console.print(
        f"[#a3be8c]◇ container ready[/]  [dim]· {name} · {inst.engine}/{inst.engine_auth}"
        f" · {deliv} · repos: {shown_repos}[/]"
    )
    console.print(
        f"[dim]thread: {tk} · /help for commands · /exit or Ctrl+D to leave · ↑ history[/]\n"
    )

    psession = _prompt_session(name, tk)

    while True:
        try:
            line = psession.prompt([("fg:#6f6a5d", "you › ")]).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not line:
            continue
        if line in ("/exit", "/quit", "exit", "quit"):
            break
        if line == "/help":
            console.print(_HELP)
            continue
        if line == "/new":
            tk = f"enter-{uuid.uuid4().hex[:8]}"
            console.print(f"[dim]new thread: {tk} (context reset)[/]")
            continue
        if line.startswith("/repos"):
            arg = line[len("/repos"):].strip()
            sel = None if arg == "" else _parse_repo_sel(arg)
            console.print(f"[dim]repos = {arg or 'all'}[/]")
            continue
        if line.startswith("/deliverable"):
            arg = line[len("/deliverable"):].strip()
            try:
                deliv = Deliverable(arg).value
                console.print(f"[dim]deliverable = {deliv}[/]")
            except ValueError:
                console.print(f"[red]invalid deliverable:[/] {arg}")
            continue
        if line.startswith("/"):
            console.print(f"[red]unknown command:[/] {line}  (/help)")
            continue

        job = _build_job(inst, line, deliv, tk, sel)
        store.create_job(job)
        done = _run_turn(console, job)
        _flush_input()  # drop input typed while it was thinking (no auto-resubmit)
        if done is None:  # cancelled or errored — already reported
            continue

        label = inst.engine
        if done.result and done.result.text:
            console.print(f"[bold #88c0d0]◆ {label} ›[/] {done.result.text}\n")
        else:
            detail = done.error_message or done.status.value
            raw = ""
            if done.result and (done.result.raw or "").strip():
                raw = "  [dim]" + done.result.raw.strip()[:500] + "[/]"
            console.print(
                f"[#d08770]◆ {label} ›[/] [dim]({done.status.value})[/] {detail}{raw}\n"
            )

    console.print("[dim]bye.[/]")


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}h {(s % 3600) // 60:02d}m {s % 60:02d}s"


def _run_turn(console, job):
    """Run one chat turn off-thread so we can show a live elapsed timer and
    actually cancel (kill the container) on Ctrl+C. Returns the finished Job, or
    None if cancelled/errored (already reported to the console)."""
    import subprocess
    import threading
    import time

    from . import runner
    from .config import load_config

    box: dict = {"job": None, "exc": None}

    def work():
        try:
            box["job"] = runner.run_job(job, log_cb=lambda _m: None)
        except BaseException as exc:  # noqa: BLE001 — surface anything to the REPL
            box["exc"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    start = time.monotonic()
    try:
        with console.status("[dim]thinking…[/]", spinner="dots") as st:
            while t.is_alive():
                st.update(
                    f"[dim]thinking… {_fmt_elapsed(time.monotonic() - start)} "
                    f"(Ctrl+C to cancel)[/]"
                )
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        try:
            if load_config().use_docker:
                subprocess.run(
                    ["docker", "kill", runner.container_name(job)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:  # noqa: BLE001
            pass
        t.join(timeout=5)
        console.print("[#d08770]· cancelled.[/] [dim]send another message.[/]\n")
        return None
    if box["exc"] is not None:
        console.print(f"[#bf616a]· engine error:[/] {box['exc']}\n")
        return None
    return box["job"]


def _build_job(inst, prompt: str, deliverable: str, thread_key: str, repos) -> Job:
    request: dict = {"prompt": prompt, "thread_key": thread_key}
    if repos is not None:
        request["repos"] = repos
    sess = store.find_or_create_session(inst.name, thread_key)
    return Job(
        instance=inst.name,
        deliverable=Deliverable(deliverable),
        mode=Mode(inst.default_mode),
        prompt=prompt,
        request=request,
        thread_key=thread_key,
        session_id=sess.id,
    )
