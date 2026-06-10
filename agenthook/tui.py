"""Friendly interactive layer — a persistent, guided menu (DESIGN.md §23).

Running ``agenthook`` with no subcommand drops into this menu: a hero banner
(drawn once, on entry) + arrow-key navigation that stays alive until the user
picks *sair* or presses Ctrl+C twice. The screen is cleared only when entering
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
_BACK = "voltar"
_QUIT = "sair"


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


def _back_choice(label: str = "voltar"):
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
    meta = ["", "agenthook", f"v{_version()}", "runner de tarefas agênticas", ""]

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
        f"  [dim]{n_inst} instância(s) · {n_jobs} job(s)   ·   "
        f"↑↓ navegar · Enter · Ctrl+C 2× p/ sair[/]",
        highlight=False,
    )
    console.print()


def _pause(console) -> None:
    import questionary

    questionary.press_any_key_to_continue("  Enter para voltar…").ask()
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
            "O que deseja fazer?",
            choices=["instâncias", "jobs", "sessões", _sep(), _back_choice(_QUIT)],
        )
        if choice is None:  # Ctrl+C on the top menu
            interrupts += 1
            if interrupts >= 2:
                break
            console.print("[dim]Ctrl+C de novo para sair, ou escolha uma opção.[/]")
            continue
        interrupts = 0
        if choice == _QUIT:
            break
        if choice == "instâncias":
            _instances_menu(console)
        elif choice == "jobs":
            _show_jobs(console)
            _pause(console)
        elif choice == "sessões":
            _show_sessions(console)
            _pause(console)

    console.print("até logo.")


# --- Instances submenu -------------------------------------------------------


def _instances_menu(console) -> None:
    while True:
        choice = _select(
            "Instâncias — o que deseja?",
            choices=[
                _sep("interagir"),
                "conversar (chat)",
                "shell (container)",
                _sep("gerenciar"),
                "adicionar",
                "ver detalhes",
                "editar",
                "variáveis de ambiente",
                _sep("listas / remover"),
                "listar",
                "excluir",
                _sep(),
                _back_choice(),
            ],
        )
        if choice is None or choice == _BACK:
            return
        if choice == "conversar (chat)":
            name = _pick_instance_or_none(console, "Conversar com qual instância?")
            if name and name != _BACK:
                from . import chat

                chat.repl(name, console=console)
        elif choice == "shell (container)":
            name = _pick_instance_or_none(console, "Abrir shell de qual instância?")
            if name and name != _BACK:
                from . import shell as shell_mod

                try:
                    shell_mod.shell(name)
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[red]erro:[/] {exc}")
        elif choice == "adicionar":
            _instance_add(console)
        elif choice == "ver detalhes":
            _instance_view(console)
        elif choice == "editar":
            _instance_edit(console)
        elif choice == "variáveis de ambiente":
            name = _pick_instance_or_none(console, "Env de qual instância?")
            if name and name != _BACK:
                _edit_env(console, name)
        elif choice == "excluir":
            _instance_delete(console)
        elif choice == "listar":
            _show_instances(console)


def _pick_instance_or_none(console, prompt: str = "Qual instância?"):
    names = instances.list_names()
    if not names:
        console.print("[yellow]nenhuma instância ainda.[/]")
        return None
    return _select(prompt, choices=names + [_sep(), _back_choice()])


def _instance_add(console) -> None:
    import questionary
    from rich.panel import Panel

    from .instances import Instance, _derive_repo_name

    style = _style()
    name = questionary.text("Nome da instância (slug):", qmark="●", style=style).ask()
    if not name:
        return
    if instances.exists(name):
        console.print(f"[red]instância {name!r} já existe.[/]")
        return

    from .engines import available as engines_available

    engine = _select("Engine:", choices=engines_available() or ["claude"])
    if engine is None:
        return
    engine_auth = _select("Auth do engine:", choices=["subscription", "api-key"])
    if engine_auth is None:
        return
    # Deliverable is decided per-request (the POST/CLI says what to do); the
    # instance only carries a safe fallback for requests that omit it.
    deliverable = "analysis"
    model = questionary.text(
        "Modelo (opcional, Enter p/ pular):", qmark="●", style=style
    ).ask() or None
    branch = questionary.text(
        "Branch base:", default="main", qmark="●", style=style
    ).ask() or "main"

    repos: list[dict] = []
    while questionary.confirm(
        f"Adicionar repositório ao pool? ({len(repos)} já)", default=False, qmark="●", style=style
    ).ask():
        spec = questionary.text("repo (name=url ou url):", qmark="●", style=style).ask()
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
        console.print(f"[red]erro:[/] {exc}")
        return
    key, fp = secrets.generate_key(inst)
    inst.key_fingerprint = fp
    instances.save(inst)
    console.print(
        Panel(
            f"[bold]Instância [cyan]{name}[/] criada.[/]\n\n"
            f"[yellow]Chave de criptografia (mostrada UMA vez — guarde com segurança):[/]\n"
            f"[bold]{key}[/]\n\nfingerprint: {fp}",
            title="guarde esta chave",
            border_style="yellow",
        )
    )
    # Per-instance auth — never inherited from the host's ambient login.
    if engine_auth == "api-key":
        _set_api_key(console, inst)
    else:  # subscription
        console.print(
            "[dim]auth = subscription (isolada do host). Faça o login desta instância:[/]\n"
            f"  [bold]agenthook login {name}[/]\n"
            "[dim]Cada instância tem login próprio; o ~/.claude do host nunca é usado.[/]"
        )


def _instance_view(console) -> None:
    import json

    from rich.table import Table

    name = _pick_instance_or_none(console, "Ver qual instância?")
    if not name or name == _BACK:
        return
    inst = instances.load(name)

    info = Table("campo", "valor", title=f"instância: {name}", title_style="bold cyan")
    info.add_row("engine", inst.engine)
    info.add_row("engine_auth", inst.engine_auth)
    info.add_row("deliverable", inst.deliverable)
    info.add_row("model", inst.model or "-")
    info.add_row("branch_base", inst.branch_base)
    info.add_row("paused", "[red]sim[/]" if inst.paused else "não")
    console.print(info)

    repos = inst.resolved_repos()
    if repos:
        rt = Table("repo", "url", "branch_base", title="pool de repositórios")
        for r in repos:
            rt.add_row(r.name, r.url, r.branch_base)
        console.print(rt)
    else:
        console.print("[dim]sem repositórios no pool.[/]")

    try:
        items = secrets.get_backend(inst).items(inst)
    except Exception:  # noqa: BLE001
        items = []
    if items:
        et = Table("env", "valor", "secret", title="variáveis de ambiente")
        for ev in items:
            shown = secrets.obfuscate(ev.value) if ev.secret else ev.value
            et.add_row(ev.name, shown, "sim" if ev.secret else "não")
        console.print(et)

    jobs = [j for j in store.list_jobs(limit=50) if j.instance == name][:8]
    if jobs:
        jt = Table("job", "status", "deliverable", title="jobs recentes")
        for j in jobs:
            jt.add_row(j.id, j.status.value, j.deliverable.value)
        console.print(jt)
    if not (repos or items or jobs):
        console.print(f"[dim]{json.dumps(inst.to_dict(), default=str)}[/]")


def _instance_delete(console) -> None:
    name = _pick_instance_or_none(console, "Excluir qual instância?")
    if not name or name == _BACK:
        return
    if not confirm(f"Excluir {name!r} e seus segredos? Isso é irreversível."):
        console.print("cancelado.")
        return
    instances.delete(name)
    console.print(f"[green]excluída[/] {name}")


# --- Instance edit -----------------------------------------------------------


def _instance_edit(console) -> None:
    name = _pick_instance_or_none(console, "Editar qual instância?")
    if not name or name == _BACK:
        return
    while True:
        inst = instances.load(name)
        console.print(
            f"[bold]Editando [cyan]{name}[/][/]  "
            f"(engine={inst.engine}, auth={inst.engine_auth}, "
            f"deliverable={inst.deliverable}, repos={len(inst.resolved_repos())}, "
            f"{'[red]pausada[/]' if inst.paused else 'ativa'})"
        )
        field = _select(
            "Qual campo?",
            choices=[
                "deliverable", "engine", "autenticação", "model", "branch base",
                "repos (pool)", "variáveis de ambiente",
                "pausar / retomar", _sep(), _back_choice(),
            ],
        )
        if field is None or field == _BACK:
            return
        if field == "deliverable":
            from .models import Deliverable

            val = _select("Novo deliverable:", choices=[d.value for d in Deliverable])
            if val:
                inst.deliverable = val
                _save_inst(console, inst)
        elif field == "engine":
            from .engines import available as engines_available

            val = _select("Novo engine:", choices=engines_available() or ["claude"])
            if val:
                inst.engine = val
                _save_inst(console, inst)
        elif field == "autenticação":
            _edit_auth(console, name)
        elif field == "model":
            import questionary

            val = questionary.text(
                "Modelo (vazio = nenhum):", default=inst.model or "", qmark="●", style=_style()
            ).ask()
            inst.model = val or None
            _save_inst(console, inst)
        elif field == "branch base":
            import questionary

            val = questionary.text(
                "Branch base:", default=inst.branch_base, qmark="●", style=_style()
            ).ask()
            if val:
                inst.branch_base = val
                _save_inst(console, inst)
        elif field == "repos (pool)":
            _edit_repos(console, name)
        elif field == "variáveis de ambiente":
            _edit_env(console, name)
        elif field.startswith("pausar"):
            instances.set_paused(name, not inst.paused,
                                 "pausada manualmente" if not inst.paused else None)
            console.print("[green]ok[/]")


def _save_inst(console, inst) -> None:
    try:
        instances.save(inst)
        console.print("[green]salvo.[/]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]erro ao salvar:[/] {exc}")


def _set_api_key(console, inst) -> None:
    import questionary

    from .engines import get_engine

    names = get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]
    key_name = names[0]
    val = questionary.password(
        f"{key_name} (vira secret cifrado da instância):", qmark="●", style=_style()
    ).ask()
    if val:
        secrets.get_backend(inst).set(inst, key_name, val, True)
        console.print(f"[green]{key_name} salvo (cifrado).[/]")
    else:
        console.print("[yellow]cancelado.[/]")


def _edit_auth(console, name: str) -> None:
    from . import engine_auth

    while True:
        inst = instances.load(name)
        st = engine_auth.is_authenticated(inst)
        status = (
            "[green]logado[/]" if st is True
            else "[yellow]não logado[/]" if st is False
            else "[dim]via api-key (secret)[/]"
        )
        console.print(
            f"[bold]auth de [cyan]{name}[/][/]  "
            f"engine={inst.engine} · método={inst.engine_auth} · {status}"
        )
        first = "fazer login (isolado)" if inst.engine_auth == "subscription" else "definir / trocar api-key"
        act = _select(
            "Autenticação:",
            choices=[
                first,
                "trocar método (subscription ↔ api-key)",
                "deslogar / limpar dados",
                _sep(), _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act.startswith("fazer login"):
            try:
                from . import shell as shell_mod

                console.print("[dim]abrindo login isolado… faça /login e depois saia (/exit).[/]")
                shell_mod.login(inst.name)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]erro:[/] {exc}")
        elif act.startswith("definir"):
            _set_api_key(console, inst)
        elif act.startswith("trocar método"):
            val = _select("Novo método:", choices=["subscription", "api-key"])
            if val and val != inst.engine_auth:
                inst.engine_auth = val
                _save_inst(console, inst)
                if val == "api-key":
                    _set_api_key(console, instances.load(name))
                else:
                    console.print(
                        f"[dim]agora faça o login:[/] [bold]agenthook login {name}[/] "
                        "[dim](ou 'fazer login' aqui).[/]"
                    )
        elif act.startswith("deslogar"):
            if confirm(f"Deslogar {name!r} e apagar os dados de auth isolados?"):
                wiped = engine_auth.logout(inst)
                try:  # also drop the api-key secret, if any
                    from .engines import get_engine

                    for key in get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]:
                        secrets.get_backend(inst).delete(inst, key)
                except Exception:  # noqa: BLE001
                    pass
                console.print("[green]auth limpa.[/]" if wiped else "[dim]nada a limpar.[/]")


def _edit_repos(console, name: str) -> None:
    import questionary
    from rich.table import Table

    from .instances import _derive_repo_name

    style = _style()
    while True:
        inst = instances.load(name)
        repos = inst.resolved_repos()
        t = Table("repo", "url", "branch_base", title=f"pool de {name}")
        for r in repos:
            t.add_row(r.name, r.url, r.branch_base)
        console.print(t if repos else "[dim]pool vazio.[/]")
        act = _select("Repositórios:", choices=["adicionar", "remover", _sep(), _back_choice()])
        if act is None or act == _BACK:
            return
        if act == "adicionar":
            spec = questionary.text("repo (name=url ou url):", qmark="●", style=style).ask()
            if not spec:
                continue
            if "=" in spec:
                rname, url = spec.split("=", 1)
                entry = {"name": rname.strip(), "url": url.strip()}
            else:
                entry = {"name": _derive_repo_name(spec), "url": spec.strip()}
            branch = questionary.text(
                "branch base (vazio = herda):", qmark="●", style=style
            ).ask()
            if branch:
                entry["branch_base"] = branch
            if entry["name"] in inst.repo_names():
                console.print(f"[red]repo {entry['name']!r} já existe no pool.[/]")
                continue
            # migrate a legacy single repo into the pool transparently
            if inst.repo and not inst.repos:
                inst.repos = [{"name": _derive_repo_name(inst.repo), "url": inst.repo}]
                inst.repo = None
            inst.repos.append(entry)
            _save_inst(console, inst)
        elif act == "remover":
            if not repos:
                continue
            target = _select("Remover qual?", choices=[r.name for r in repos] + [_sep(), _back_choice()])
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
        t = Table("env", "valor", "secret", title=f"env de {name}")
        for ev in items:
            shown = secrets.obfuscate(ev.value) if ev.secret else ev.value
            t.add_row(ev.name, shown, "sim" if ev.secret else "não")
        console.print(t if items else "[dim]sem variáveis.[/]")
        act = _select("Variáveis de ambiente:", choices=["definir", "remover", _sep(), _back_choice()])
        if act is None or act == _BACK:
            return
        if act == "definir":
            key = questionary.text("Nome (KEY):", qmark="●", style=style).ask()
            if not key:
                continue
            value = questionary.text("Valor:", qmark="●", style=style).ask() or ""
            is_secret = bool(
                questionary.confirm(
                    "É secret (ofuscar)?", default=True, qmark="●", style=style
                ).ask()
            )
            backend.set(inst, key, value, is_secret)
            console.print(f"[green]definida[/] {key}{' (secret)' if is_secret else ''}")
        elif act == "remover":
            if not items:
                continue
            target = _select("Remover qual?", choices=[ev.name for ev in items] + [_sep(), _back_choice()])
            if not target or target == _BACK:
                continue
            backend.delete(inst, target)
            console.print(f"[green]removida[/] {target}")


# --- Listings ----------------------------------------------------------------


def _show_instances(console) -> None:
    from rich.table import Table

    t = Table("name", "engine", "deliverable", "repos", "paused")
    for inst in instances.list_all():
        names = inst.repo_names()
        t.add_row(inst.name, inst.engine, inst.deliverable,
                  ", ".join(names) if names else "-",
                  "[red]sim[/]" if inst.paused else "não")
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
