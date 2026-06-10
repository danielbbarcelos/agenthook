"""Friendly interactive layer — arrow-key pickers and a simple menu (DESIGN.md §23).

Kept thin and optional: every flow also works non-interactively. The live
Textual dashboard is intentionally left for a later phase; these questionary
pickers deliver most of the "friendly" feel at a fraction of the cost.
"""

from __future__ import annotations

import sys

from . import instances, store


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def pick_instance() -> str:
    names = instances.list_names()
    if not names:
        raise SystemExit("no instances; create one with `agenthook instance add`")
    if len(names) == 1 or not _interactive():
        return names[0]
    import questionary

    return questionary.select("Pick an instance:", choices=names).ask() or names[0]


def pick_job() -> str:
    jobs = store.list_jobs(limit=20)
    if not jobs:
        raise SystemExit("no jobs yet")
    if not _interactive():
        return jobs[0].id
    import questionary

    choices = [f"{j.id}  {j.instance}  {j.status.value}" for j in jobs]
    ans = questionary.select("Pick a job:", choices=choices).ask()
    return (ans or choices[0]).split()[0]


def confirm(prompt: str) -> bool:
    if not _interactive():
        return True
    import questionary

    return bool(questionary.confirm(prompt, default=False).ask())


def main_menu() -> None:
    from rich.console import Console

    console = Console()
    if not _interactive():
        console.print("agenthook — run `agenthook --help` for commands.")
        return
    import questionary

    action = questionary.select(
        "agenthook — what would you like to do?",
        choices=["list instances", "list jobs", "list sessions", "quit"],
    ).ask()

    from rich.table import Table

    if action == "list instances":
        t = Table("name", "engine", "deliverable", "paused")
        for inst in instances.list_all():
            t.add_row(inst.name, inst.engine, inst.deliverable, "yes" if inst.paused else "no")
        console.print(t)
    elif action == "list jobs":
        t = Table("job", "instance", "status")
        for j in store.list_jobs(limit=20):
            t.add_row(j.id, j.instance, j.status.value)
        console.print(t)
    elif action == "list sessions":
        t = Table("session", "instance", "thread_key", "jobs")
        for s in store.list_sessions():
            t.add_row(s.id, s.instance, s.thread_key, str(s.job_count))
        console.print(t)
