"""Friendly interactive layer — a persistent, guided menu (DESIGN.md §23).

Running ``agenthook`` with no subcommand drops into this menu: a hero banner
(drawn once, on entry) + arrow-key navigation that stays alive until the user
picks *quit* or presses Ctrl+C twice. The screen is cleared only when entering
the menu; navigation just scrolls, so you keep the history of what you did.

Every flow here also has a non-interactive CLI equivalent; the menu just makes
the common CRUD friendly. It talks to ``instances`` / ``secrets`` / ``store``
directly (never to Typer commands, whose defaults are OptionInfo sentinels when
called in-process).
"""

from __future__ import annotations

import sys

from . import instances, secrets, store

# Plain-text sentinels — no icons (keep navigation calm and readable).
_BACK = "back"
_QUIT = "quit"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("agenthook")
    except Exception:  # noqa: BLE001
        return "dev"


def _style():
    """Lavender questionary palette (matches the hero)."""
    import questionary

    return questionary.Style(
        [
            ("qmark", "fg:#b48ead bold"),
            ("question", "bold"),
            ("pointer", "fg:#b48ead bold"),
            ("highlighted", "fg:#b48ead"),
            ("selected", "fg:#a3be8c"),
            ("answer", "fg:#88c0d0"),
            ("separator", "fg:#6b7280"),
        ]
    )


_MUTED = "fg:#6b7280"


def _back_choice(label: str = "back"):
    """A muted '←' back/quit entry, set apart from the real actions."""
    import questionary

    return questionary.Choice(title=[(_MUTED, f"←  {label}")], value=label)


def _sep(label: str = ""):
    import questionary

    return questionary.Separator(f"  {label}" if label else " ")


# --- Reusable pickers (used by the CLI too) ---------------------------------


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

    return bool(questionary.confirm(prompt, default=False, style=_style()).ask())


# --- Banner ------------------------------------------------------------------


def _banner(console) -> None:
    """A minimal hero in the local-server style: a small node logo + name,
    version and tagline inside a rounded lavender box, with a dim status line
    underneath. Drawn once, on entry."""
    from rich.panel import Panel
    from rich.text import Text

    try:
        n_inst = len(instances.list_names())
    except Exception:  # noqa: BLE001
        n_inst = 0
    try:
        n_jobs = len(store.list_jobs(limit=100000))
    except Exception:  # noqa: BLE001
        n_jobs = 0

    logo = ["●─╮", "│ │", "├─●", "│ │", "●─╯"]
    meta = ["", "agenthook", f"v{_version()}", "agentic task runner", ""]

    body = Text()
    for i in range(5):
        body.append(logo[i], style="bold #b48ead")
        body.append("   ")
        if meta[i] == "agenthook":
            body.append(meta[i], style="bold white")
        else:
            body.append(meta[i], style="dim")
        if i < 4:
            body.append("\n")

    console.print(Panel(body, border_style="#b48ead", padding=(1, 3), expand=False))
    console.print(
        f"  [dim]{n_inst} instance(s) · {n_jobs} job(s)   ·   "
        f"↑↓ move · Enter · Ctrl+C 2× to quit[/]",
        highlight=False,
    )
    console.print()


def _pause(console) -> None:
    import questionary

    questionary.press_any_key_to_continue("  Enter to go back…").ask()
    console.print()


def _select(message: str, choices: list):
    import questionary

    print()  # breathing room above every menu
    return questionary.select(message, choices=choices, qmark="●", style=_style()).ask()


# --- Main loop ---------------------------------------------------------------


def main_menu() -> None:
    from rich.console import Console

    console = Console()
    if not _interactive():
        console.print("agenthook — run `agenthook --help` for commands.")
        return

    console.clear()  # the only clear: on entry
    _banner(console)
    interrupts = 0
    while True:
        choice = _select(
            "What would you like to do?",
            choices=["instances", "jobs", "sessions", _sep(), _back_choice(_QUIT)],
        )
        if choice is None:  # Ctrl+C on the top menu
            interrupts += 1
            if interrupts >= 2:
                break
            console.print("[dim]Ctrl+C again to quit, or pick an option.[/]")
            continue
        interrupts = 0
        if choice == _QUIT:
            break
        if choice == "instances":
            _instances_menu(console)
        elif choice == "jobs":
            _show_jobs(console)
            _pause(console)
        elif choice == "sessions":
            _show_sessions(console)
            _pause(console)

    console.print("bye.")


# --- Instances submenu -------------------------------------------------------


def _instances_menu(console) -> None:
    while True:
        choice = _select(
            "Instances — what would you like?",
            choices=[
                _sep("interact"),
                "chat",
                "shell (container)",
                _sep("manage"),
                "add",
                "view",
                "edit",
                "env vars",
                _sep("list / remove"),
                "list",
                "delete",
                _sep(),
                _back_choice(),
            ],
        )
        if choice is None or choice == _BACK:
            return
        if choice == "chat":
            name = _pick_instance_or_none(console, "Chat with which instance?")
            if name and name != _BACK:
                from . import chat

                chat.repl(name, console=console)
        elif choice == "shell (container)":
            name = _pick_instance_or_none(console, "Open a shell for which instance?")
            if name and name != _BACK:
                from . import shell as shell_mod

                try:
                    shell_mod.shell(name)
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]error:[/] {exc}")
        elif choice == "add":
            _instance_add(console)
        elif choice == "view":
            _instance_view(console)
        elif choice == "edit":
            _instance_edit(console)
        elif choice == "env vars":
            name = _pick_instance_or_none(console, "Env for which instance?")
            if name and name != _BACK:
                _edit_env(console, name)
        elif choice == "delete":
            _instance_delete(console)
        elif choice == "list":
            _show_instances(console)


def _pick_instance_or_none(console, prompt: str = "Which instance?"):
    names = instances.list_names()
    if not names:
        console.print("[yellow]no instances yet.[/]")
        return None
    return _select(prompt, choices=names + [_sep(), _back_choice()])


def _instance_add(console) -> None:
    import questionary
    from rich.panel import Panel

    from .instances import Instance, _derive_repo_name

    style = _style()
    name = questionary.text("Instance name (slug):", qmark="●", style=style).ask()
    if not name:
        return
    if instances.exists(name):
        console.print(f"[red]instance {name!r} already exists.[/]")
        return

    from .engines import available as engines_available

    engine = _select("Engine:", choices=engines_available() or ["claude"])
    if engine is None:
        return
    engine_auth = _select("Engine auth:", choices=["subscription", "api-key"])
    if engine_auth is None:
        return
    # Deliverable is decided per-request (the POST/CLI says what to do); the
    # instance only carries a safe fallback for requests that omit it.
    deliverable = "analysis"
    model = questionary.text(
        "Model (optional, Enter to skip):", qmark="●", style=style
    ).ask() or None
    branch = questionary.text(
        "Base branch:", default="main", qmark="●", style=style
    ).ask() or "main"

    repos: list[dict] = []
    while questionary.confirm(
        f"Add a repo to the pool? ({len(repos)} so far)", default=False, qmark="●", style=style
    ).ask():
        spec = questionary.text("repo (name=url or url):", qmark="●", style=style).ask()
        if not spec:
            break
        if "=" in spec:
            rname, url = spec.split("=", 1)
            repos.append({"name": rname.strip(), "url": url.strip()})
        else:
            repos.append({"name": _derive_repo_name(spec), "url": spec.strip()})

    inst = Instance(
        name=name,
        engine=engine,
        engine_auth=engine_auth,
        deliverable=deliverable,
        model=model,
        branch_base=branch,
        repos=repos,
    )
    try:
        instances.save(inst)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]error:[/] {exc}")
        return
    key, fp = secrets.generate_key(inst)
    inst.key_fingerprint = fp
    instances.save(inst)
    console.print(
        Panel(
            f"[bold]Instance [cyan]{name}[/] created.[/]\n\n"
            f"[yellow]Encryption key (shown ONCE — keep it safe):[/]\n"
            f"[bold]{key}[/]\n\nfingerprint: {fp}",
            title="save this key",
            border_style="yellow",
        )
    )
    # Per-instance auth — never inherited from the host's ambient login.
    if engine_auth == "api-key":
        _set_api_key(console, inst)
    else:  # subscription
        console.print(
            "[dim]auth = subscription (isolated from the host). Log this instance in:[/]\n"
            f"  [bold]agenthook login {name}[/]\n"
            "[dim]Each instance has its own login; the host's ~/.claude is never used.[/]"
        )


def _instance_view(console) -> None:
    import json

    from rich.table import Table

    name = _pick_instance_or_none(console, "View which instance?")
    if not name or name == _BACK:
        return
    inst = instances.load(name)

    info = Table("field", "value", title=f"instance: {name}", title_style="bold cyan")
    info.add_row("engine", inst.engine)
    info.add_row("engine_auth", inst.engine_auth)
    info.add_row("deliverable", inst.deliverable)
    info.add_row("model", inst.model or "-")
    info.add_row("branch_base", inst.branch_base)
    info.add_row("paused", "[red]yes[/]" if inst.paused else "no")
    console.print(info)

    repos = inst.resolved_repos()
    if repos:
        rt = Table("repo", "url", "branch_base", title="repo pool")
        for r in repos:
            rt.add_row(r.name, r.url, r.branch_base)
        console.print(rt)
    else:
        console.print("[dim]no repos in the pool.[/]")

    try:
        items = secrets.get_backend(inst).items(inst)
    except Exception:  # noqa: BLE001
        items = []
    if items:
        et = Table("env", "value", "secret", title="environment variables")
        for ev in items:
            shown = secrets.obfuscate(ev.value) if ev.secret else ev.value
            et.add_row(ev.name, shown, "yes" if ev.secret else "no")
        console.print(et)

    jobs = [j for j in store.list_jobs(limit=50) if j.instance == name][:8]
    if jobs:
        jt = Table("job", "status", "deliverable", title="recent jobs")
        for j in jobs:
            jt.add_row(j.id, j.status.value, j.deliverable.value)
        console.print(jt)
    if not (repos or items or jobs):
        console.print(f"[dim]{json.dumps(inst.to_dict(), default=str)}[/]")


def _instance_delete(console) -> None:
    name = _pick_instance_or_none(console, "Delete which instance?")
    if not name or name == _BACK:
        return
    if not confirm(f"Delete {name!r} and its secrets? This is irreversible."):
        console.print("cancelled.")
        return
    instances.delete(name)
    console.print(f"[green]deleted[/] {name}")


# --- Instance edit -----------------------------------------------------------


def _instance_edit(console) -> None:
    name = _pick_instance_or_none(console, "Edit which instance?")
    if not name or name == _BACK:
        return
    while True:
        inst = instances.load(name)
        console.print(
            f"[bold]Editing [cyan]{name}[/][/]  "
            f"(engine={inst.engine}, auth={inst.engine_auth}, "
            f"deliverable={inst.deliverable}, repos={len(inst.resolved_repos())}, "
            f"{'[red]paused[/]' if inst.paused else 'active'})"
        )
        field = _select(
            "Which field?",
            choices=[
                "deliverable", "engine", "authentication", "model", "branch base",
                "repos (pool)", "env vars",
                "pause / resume", _sep(), _back_choice(),
            ],
        )
        if field is None or field == _BACK:
            return
        if field == "deliverable":
            from .models import Deliverable

            val = _select("New deliverable:", choices=[d.value for d in Deliverable])
            if val:
                inst.deliverable = val
                _save_inst(console, inst)
        elif field == "engine":
            from .engines import available as engines_available

            val = _select("New engine:", choices=engines_available() or ["claude"])
            if val:
                inst.engine = val
                _save_inst(console, inst)
        elif field == "authentication":
            _edit_auth(console, name)
        elif field == "model":
            import questionary

            val = questionary.text(
                "Model (empty = none):", default=inst.model or "", qmark="●", style=_style()
            ).ask()
            inst.model = val or None
            _save_inst(console, inst)
        elif field == "branch base":
            import questionary

            val = questionary.text(
                "Base branch:", default=inst.branch_base, qmark="●", style=_style()
            ).ask()
            if val:
                inst.branch_base = val
                _save_inst(console, inst)
        elif field == "repos (pool)":
            _edit_repos(console, name)
        elif field == "env vars":
            _edit_env(console, name)
        elif field.startswith("pause"):
            instances.set_paused(name, not inst.paused,
                                 "paused manually" if not inst.paused else None)
            console.print("[green]ok[/]")


def _save_inst(console, inst) -> None:
    try:
        instances.save(inst)
        console.print("[green]saved.[/]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]save error:[/] {exc}")


def _set_api_key(console, inst) -> None:
    import questionary

    from .engines import get_engine

    names = get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]
    key_name = names[0]
    val = questionary.password(
        f"{key_name} (stored as an encrypted instance secret):", qmark="●", style=_style()
    ).ask()
    if val:
        secrets.get_backend(inst).set(inst, key_name, val, True)
        console.print(f"[green]{key_name} saved (encrypted).[/]")
    else:
        console.print("[yellow]cancelled.[/]")


def _edit_auth(console, name: str) -> None:
    from . import engine_auth

    while True:
        inst = instances.load(name)
        st = engine_auth.is_authenticated(inst)
        status = (
            "[green]logged in[/]" if st is True
            else "[yellow]not logged in[/]" if st is False
            else "[dim]via api-key (secret)[/]"
        )
        console.print(
            f"[bold]auth for [cyan]{name}[/][/]  "
            f"engine={inst.engine} · method={inst.engine_auth} · {status}"
        )
        first = "log in (isolated)" if inst.engine_auth == "subscription" else "set / change api-key"
        act = _select(
            "Authentication:",
            choices=[
                first,
                "switch method (subscription ↔ api-key)",
                "log out / wipe data",
                _sep(), _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act.startswith("log in"):
            try:
                from . import shell as shell_mod

                console.print("[dim]opening isolated login… run /login, then exit (/exit).[/]")
                shell_mod.login(inst.name)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]error:[/] {exc}")
        elif act.startswith("set"):
            _set_api_key(console, inst)
        elif act.startswith("switch method"):
            val = _select("New method:", choices=["subscription", "api-key"])
            if val and val != inst.engine_auth:
                inst.engine_auth = val
                _save_inst(console, inst)
                if val == "api-key":
                    _set_api_key(console, instances.load(name))
                else:
                    console.print(
                        f"[dim]now log in:[/] [bold]agenthook login {name}[/] "
                        "[dim](or 'log in' here).[/]"
                    )
        elif act.startswith("log out"):
            if confirm(f"Log {name!r} out and wipe its isolated auth data?"):
                wiped = engine_auth.logout(inst)
                try:  # also drop the api-key secret, if any
                    from .engines import get_engine

                    for key in get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]:
                        secrets.get_backend(inst).delete(inst, key)
                except Exception:  # noqa: BLE001
                    pass
                console.print("[green]auth wiped.[/]" if wiped else "[dim]nothing to wipe.[/]")


def _edit_repos(console, name: str) -> None:
    import questionary
    from rich.table import Table

    from .instances import _derive_repo_name

    style = _style()
    while True:
        inst = instances.load(name)
        repos = inst.resolved_repos()
        t = Table("repo", "url", "branch_base", title=f"pool for {name}")
        for r in repos:
            t.add_row(r.name, r.url, r.branch_base)
        console.print(t if repos else "[dim]empty pool.[/]")
        act = _select("Repos:", choices=["add", "remove", _sep(), _back_choice()])
        if act is None or act == _BACK:
            return
        if act == "add":
            spec = questionary.text("repo (name=url or url):", qmark="●", style=style).ask()
            if not spec:
                continue
            if "=" in spec:
                rname, url = spec.split("=", 1)
                entry = {"name": rname.strip(), "url": url.strip()}
            else:
                entry = {"name": _derive_repo_name(spec), "url": spec.strip()}
            branch = questionary.text(
                "base branch (empty = inherit):", qmark="●", style=style
            ).ask()
            if branch:
                entry["branch_base"] = branch
            if entry["name"] in inst.repo_names():
                console.print(f"[red]repo {entry['name']!r} already in the pool.[/]")
                continue
            # migrate a legacy single repo into the pool transparently
            if inst.repo and not inst.repos:
                inst.repos = [{"name": _derive_repo_name(inst.repo), "url": inst.repo}]
                inst.repo = None
            inst.repos.append(entry)
            _save_inst(console, inst)
        elif act == "remove":
            if not repos:
                continue
            target = _select("Remove which?", choices=[r.name for r in repos] + [_sep(), _back_choice()])
            if not target or target == _BACK:
                continue
            inst.repos = [
                r for r in inst.repos
                if (r.get("name") or _derive_repo_name(r["url"])) != target
            ]
            _save_inst(console, inst)


def _edit_env(console, name: str) -> None:
    import questionary
    from rich.table import Table

    style = _style()
    while True:
        inst = instances.load(name)
        backend = secrets.get_backend(inst)
        items = backend.items(inst)
        t = Table("env", "value", "secret", title=f"env for {name}")
        for ev in items:
            shown = secrets.obfuscate(ev.value) if ev.secret else ev.value
            t.add_row(ev.name, shown, "yes" if ev.secret else "no")
        console.print(t if items else "[dim]no variables.[/]")
        act = _select("Environment variables:", choices=["set", "remove", _sep(), _back_choice()])
        if act is None or act == _BACK:
            return
        if act == "set":
            key = questionary.text("Name (KEY):", qmark="●", style=style).ask()
            if not key:
                continue
            value = questionary.text("Value:", qmark="●", style=style).ask() or ""
            is_secret = bool(
                questionary.confirm(
                    "Is it a secret (obfuscate)?", default=True, qmark="●", style=style
                ).ask()
            )
            backend.set(inst, key, value, is_secret)
            console.print(f"[green]set[/] {key}{' (secret)' if is_secret else ''}")
        elif act == "remove":
            if not items:
                continue
            target = _select("Remove which?", choices=[ev.name for ev in items] + [_sep(), _back_choice()])
            if not target or target == _BACK:
                continue
            backend.delete(inst, target)
            console.print(f"[green]removed[/] {target}")


# --- Listings ----------------------------------------------------------------


def _show_instances(console) -> None:
    from rich.table import Table

    t = Table("name", "engine", "deliverable", "repos", "paused")
    for inst in instances.list_all():
        names = inst.repo_names()
        t.add_row(inst.name, inst.engine, inst.deliverable,
                  ", ".join(names) if names else "-",
                  "[red]yes[/]" if inst.paused else "no")
    console.print(t)


def _show_jobs(console) -> None:
    from rich.table import Table

    t = Table("job", "instance", "status", "deliverable")
    for j in store.list_jobs(limit=20):
        t.add_row(j.id, j.instance, j.status.value, j.deliverable.value)
    console.print(t)


def _show_sessions(console) -> None:
    from rich.table import Table

    t = Table("session", "instance", "thread_key", "jobs")
    for s in store.list_sessions():
        t.add_row(s.id, s.instance, s.thread_key, str(s.job_count))
    console.print(t)
