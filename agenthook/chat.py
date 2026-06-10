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

    from . import runner

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
        f"[bold #b48ead]●[/] session [cyan]{name}[/] "
        f"[dim](thread: {tk} · engine: {inst.engine}/{inst.engine_auth} · "
        f"deliverable: {deliv} · repos: {shown_repos})[/]"
    )
    console.print("[dim]/help for commands · /exit or Ctrl+D to leave[/]\n")

    while True:
        try:
            line = console.input("[bold #b48ead]you ›[/] ").strip()
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
        with console.status("[dim]thinking…[/]", spinner="dots"):
            job = runner.run_job(job, log_cb=lambda _m: None)

        if job.result and job.result.text:
            console.print(f"[bold #88c0d0]claude ›[/] {job.result.text}\n")
        else:
            detail = job.error_message or job.status.value
            console.print(f"[yellow]claude ›[/] [dim]({job.status.value})[/] {detail}\n")

    console.print("[dim]bye.[/]")


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
