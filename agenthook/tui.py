"""Friendly interactive layer — the guided TUI (DESIGN.md §23).

Running ``agenthook`` with no subcommand drops into this menu. The design is the
*Guided* direction from ``design-system/`` (variant A): arrow-key menus, a single
column, a warm amber/earth palette, and a shared status vocabulary.

Screen-clear rule (design §02): clear + redraw on *big* transitions (entering a
top section, opening view/edit, launching chat/shell) and keep + append on
*small* ones (wizard pages, sequences of prompts). Every cleared screen is
anchored by a dimmed breadcrumb — ``agenthook ▸ instances ▸ api-bot ▸ edit`` — so
you always know where you are without re-reading scrollback.

Every flow here also has a non-interactive CLI equivalent; the menu just makes
the common CRUD friendly. It talks to ``instances`` / ``secrets`` / ``store``
directly (never to Typer commands, whose defaults are OptionInfo sentinels when
called in-process).
"""

from __future__ import annotations

import sys
import time

from . import instances, secrets, store

# --- Palette (design-system/README.md · ANSI roles) -------------------------
AMBER = "#d9a441"  # highlight / brand — "you are here / act here"
SAGE = "#a3be8c"  # ok / success
CYAN = "#88c0d0"  # info / response
CLAY = "#d08770"  # warning / awaiting
RUST = "#bf616a"  # error / failed
LILAC = "#b48ead"  # plan / session — the "thinking" hue
STONE = "#6f6a5d"  # muted
BONE = "#e8e3d8"  # foreground
BORDER = "#45413a"  # subtle box border — darker than muted, just a hairline

_LOGO = (
    " █████╗  ██████╗ ███████╗███╗   ██╗████████╗██╗  ██╗ ██████╗  ██████╗ ██╗  ██╗\n"
    "██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██║  ██║██╔═══██╗██╔═══██╗██║ ██╔╝\n"
    "███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ███████║██║   ██║██║   ██║█████╔╝ \n"
    "██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██╔══██║██║   ██║██║   ██║██╔═██╗ \n"
    "██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ██║  ██║╚██████╔╝╚██████╔╝██║  ██╗\n"
    "╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝"
)

_MUTED = f"fg:{STONE}"

# Plain-text sentinels — values returned by menu choices.
_BACK = "back"
_QUIT = "quit"

# Job status → (glyph, color). One set of colors everywhere (design §01).
_JOB_VIS = {
    "queued": ("·", STONE),
    "running": ("▸", AMBER),
    "awaiting_approval": ("◷", LILAC),
    "success": ("✓", SAGE),
    "failed-checks": ("▲", CLAY),
    "blocked": ("▲", CLAY),
    "error": ("✗", RUST),
    "timeout": ("✗", RUST),
    "interrupted": ("⊘", STONE),
    "rejected": ("✗", STONE),
    "expired": ("·", STONE),
}


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("agenthook")
    except Exception:  # noqa: BLE001
        return "dev"


# --- Styling ----------------------------------------------------------------


def _style():
    """questionary palette — amber brand, cyan question mark, muted separators."""
    import questionary

    return questionary.Style(
        [
            ("qmark", f"fg:{CYAN} bold"),
            ("question", "bold"),
            ("pointer", f"fg:{AMBER} bold"),
            ("highlighted", f"fg:{AMBER} bold"),
            ("selected", f"fg:{SAGE}"),
            ("answer", f"fg:{CYAN}"),
            ("separator", f"fg:{STONE}"),
            ("instruction", f"fg:{STONE}"),
            ("text", f"fg:{BONE}"),
        ]
    )


def _back_choice(label: str = "back"):
    """A muted '←' back/quit entry, always the last row, set apart from actions."""
    import questionary

    return questionary.Choice(title=[(_MUTED, f"←  {label}")], value=label)


def _sep(label: str = ""):
    """A labelled divider. Aligned to the option text column: questionary
    prefixes every *choice* with 3 chars (' ● ' / '   ') but separators with
    none, so we pad separators by 3 to line them up with the labels above."""
    import questionary

    if not label:
        return questionary.Separator("   ──────────────────────────────")
    pad = max(0, 28 - len(label))
    return questionary.Separator(f"   ─── {label} " + "─" * pad)


def _action(label: str, desc: str = "", value: str | None = None, disabled: str | None = None):
    """A menu row: action name (highlights amber when selected) + muted hint.
    ``disabled`` greys it out and blocks selection (e.g. no instances yet)."""
    import questionary

    title: list = [("", f"{label:<16}")]
    if desc:
        title.append((_MUTED, desc))
    return questionary.Choice(title=title, value=value or label, disabled=disabled)


def _title_tuples(c) -> list:
    """Normalize a choice's title into prompt_toolkit (style, text) fragments."""
    title = getattr(c, "title", c)
    if isinstance(title, list):
        return [(str(s), str(t)) for s, t in title]
    return [("", str(title))]


def _select(
    message: str,
    choices: list,
    *,
    qmark: str = "?",
    instruction: str | None = None,
    header: str | None = None,
):
    """Arrow-key menu inside a rounded container (design-system box), with the
    description column aligned. Falls back to questionary if prompt_toolkit
    can't run (e.g. an exotic terminal)."""
    if not _interactive():
        for c in choices:
            import questionary

            if not isinstance(c, questionary.Separator):
                return c.value if hasattr(c, "value") else c
        return None
    try:
        return _boxed_select(message, choices, header=header)
    except Exception:  # noqa: BLE001 — never let the menu hard-fail
        return _select_q(message, choices, qmark=qmark, instruction=instruction)


def _select_q(message, choices, *, qmark="?", instruction=None):
    import questionary

    print()
    kw = dict(choices=choices, qmark=qmark, pointer="●", style=_style())
    if instruction is not None:
        kw["instruction"] = instruction
    return questionary.select(message, **kw).ask()


def _pt_style():
    from prompt_toolkit.styles import Style

    return Style.from_dict(
        {
            "border": BORDER,
            "title": f"bold {BONE}",
            "pointer": f"{AMBER} bold",
            "sel": f"{AMBER} bold",
            "name": BONE,
            "desc": STONE,
            "sep": STONE,
            "off": STONE,
            "head": STONE,
        }
    )


def _boxed_select(message: str, choices: list, *, header: str | None = None):
    import questionary
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    rows: list[dict] = []
    for c in choices:
        if isinstance(c, questionary.Separator):
            raw = str(c.title).strip().strip("─").strip()
            rows.append({"sep": True, "label": raw})
        elif isinstance(c, questionary.Choice):
            rows.append(
                {
                    "sep": False,
                    "value": c.value,
                    "frags": _title_tuples(c),
                    "disabled": bool(c.disabled),
                    "dis": c.disabled if isinstance(c.disabled, str) else "",
                }
            )
        else:
            rows.append({"sep": False, "value": c, "frags": [("", str(c))], "disabled": False, "dis": ""})

    selectable = [i for i, r in enumerate(rows) if not r["sep"] and not r["disabled"]]
    if not selectable:
        return None
    pos = {"i": selectable[0]}

    def _term_width() -> int:
        try:
            from prompt_toolkit.application import get_app

            return get_app().output.get_size().columns
        except Exception:  # noqa: BLE001
            import shutil

            return shutil.get_terminal_size((100, 24)).columns

    def fragments():
        # A rounded, full-width box drawn by hand (prompt_toolkit's Frame has
        # square corners) — ╭╮╰╯ to match the Rich tables and hero.
        width = max(40, _term_width())
        inner = width - 4  # "│ " + content + " │"
        out: list = []

        if message:
            left = "╭─ "
            dashes = max(0, width - len(left) - len(message) - 2)
            out += [
                ("class:border", left),
                ("class:title", message),
                ("class:border", " " + "─" * dashes + "╮"),
                ("", "\n"),
            ]
        else:
            out += [("class:border", "╭" + "─" * (width - 2) + "╮"), ("", "\n")]

        def row(frags, used):
            o = [("class:border", "│ "), *frags]
            if used < inner:
                o.append(("", " " * (inner - used)))
            o += [("class:border", " │"), ("", "\n")]
            return o

        if header:
            htxt = header[:inner]
            out += row([("class:head", htxt)], len(htxt))

        for i, r in enumerate(rows):
            if r["sep"]:
                lbl = r["label"]
                s = f"─── {lbl} " if lbl else ""
                s = (s + "─" * max(0, inner - len(s)))[:inner]
                out += row([("class:sep", s)], len(s))
                continue
            sel = i == pos["i"]
            frags = [("class:pointer", "● ") if sel else ("", "  ")]
            used = 2
            if r["disabled"]:
                text = ("".join(t for _, t in r["frags"]) + (r["dis"] or ""))[: inner - 2]
                frags.append(("class:off", text))
                used += len(text)
            else:
                for st, txt in r["frags"]:
                    # the default-styled name fragment glows amber when selected;
                    # already-colored fragments (status, etc.) keep their color.
                    style = ("class:sel" if sel else "class:name") if st == "" else st
                    frags.append((style, txt))
                    used += len(txt)
            out += row(frags, used)

        out += [("class:border", "╰" + "─" * (width - 2) + "╯")]
        return out

    control = FormattedTextControl(fragments, focusable=True, show_cursor=False)
    root = Window(control, dont_extend_height=True)

    kb = KeyBindings()

    def _move(delta: int) -> None:
        idx = selectable.index(pos["i"]) if pos["i"] in selectable else 0
        pos["i"] = selectable[(idx + delta) % len(selectable)]

    @kb.add("up")
    @kb.add("c-p")
    @kb.add("k")
    def _(e):
        _move(-1)

    @kb.add("down")
    @kb.add("c-n")
    @kb.add("j")
    def _(e):
        _move(1)

    @kb.add("enter")
    def _(e):
        e.app.exit(result=rows[pos["i"]]["value"])

    @kb.add("escape")
    @kb.add("c-c")
    def _(e):
        e.app.exit(result=None)

    print()
    app = Application(
        layout=Layout(root),
        key_bindings=kb,
        style=_pt_style(),
        full_screen=False,
        mouse_support=False,
    )
    return app.run()


def confirm(prompt: str) -> bool:
    if not _interactive():
        return True
    import questionary

    return bool(questionary.confirm(prompt, default=False, qmark="?", style=_style()).ask())


# --- Breadcrumb & clear -----------------------------------------------------


def _crumb(console, *parts: str, right: str | None = None) -> None:
    trail = " ▸ ".join(["agenthook", *parts])
    line = f"[{STONE}]{trail}[/]"
    if right:
        line += f"   [{STONE}]{right}[/]"
    console.print(line, highlight=False)


def _hard_clear(console) -> None:
    """A real clear, like the ``clear`` command: home the cursor, wipe the
    visible screen *and* the scrollback (``ESC[3J``). Rich's ``console.clear()``
    only does ``ESC[2J``/home, which leaves everything in the scrollback — so the
    screen looks 'cleared' but scrolling up still shows the old pages."""
    try:
        console.file.write("\033[H\033[2J\033[3J")
        console.file.flush()
    except Exception:  # noqa: BLE001
        console.clear()


def _clear(console, *parts: str, right: str | None = None) -> None:
    """Every screen change truly clears the terminal (no infinite scroll),
    redraws the hero banner at the top, then anchors with the breadcrumb."""
    _hard_clear(console)
    _banner(console)
    if parts:
        console.print()
        _crumb(console, *parts, right=right)


# --- Time helpers -----------------------------------------------------------


def _ago(ts: float | None) -> str:
    if not ts:
        return "—"
    d = time.time() - ts
    if d < 60:
        return "now"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


def _elapsed(job) -> str:
    start = job.started_at or job.created_at
    end = job.finished_at or time.time()
    s = int(max(0, end - start))
    return f"{s // 60}:{s % 60:02d}"


# --- Status badges ----------------------------------------------------------


def _job_badge(status: str) -> str:
    glyph, color = _JOB_VIS.get(status, ("·", STONE))
    return f"[{color}]{glyph} {status}[/]"


def _inst_badge(inst) -> str:
    if inst.paused:
        return f"[{STONE}]⏸ paused[/]"
    try:
        from . import engine_auth

        if engine_auth.is_authenticated(inst) is False:
            return f"[{RUST}]⚠ no auth[/]"
    except Exception:  # noqa: BLE001
        pass
    return f"[{SAGE}]● active[/]"


def _auth_badge(state) -> str:
    if state is True:
        return f"[{SAGE}]● logged in[/]"
    if state is False:
        return f"[{RUST}]not logged in[/]"
    return f"[{CYAN}]via api-key[/]"


# --- Reusable pickers (used by the CLI too) ---------------------------------


def pick_instance() -> str:
    names = instances.list_names()
    if not names:
        raise SystemExit("no instances; create one with `agenthook instance add`")
    if len(names) == 1 or not _interactive():
        return names[0]
    return _pick_instance_or_none(None, "Pick an instance:") or names[0]


def pick_job() -> str:
    jobs = store.list_jobs(limit=20)
    if not jobs:
        raise SystemExit("no jobs yet")
    if not _interactive():
        return jobs[0].id
    choice = _select("Pick a job:", [_job_choice(j) for j in jobs] + [_sep(), _back_choice()])
    return choice if (choice and choice != _BACK) else jobs[0].id


def _job_choice(j):
    import questionary

    glyph, color = _JOB_VIS.get(j.status.value, ("·", STONE))
    title = [
        (f"fg:{STONE}", f"{j.id:<14}"),
        ("", f"{j.instance:<14}"),
        (f"fg:{color}", f"{glyph} {j.status.value:<18}"),
        (_MUTED, f"{j.deliverable.value:<10}{_ago(j.created_at)}"),
    ]
    return questionary.Choice(title=title, value=j.id)


def _pick_instance_or_none(console, prompt: str = "Which instance?"):
    import questionary

    names = instances.list_names()
    if not names:
        if console:
            console.print(f"[{CLAY}]no instances yet.[/]")
        return None
    choices = []
    for n in names:
        try:
            inst = instances.load(n)
            desc = f"{inst.engine} · {inst.deliverable}"
        except Exception:  # noqa: BLE001
            desc = ""
        choices.append(
            questionary.Choice(title=[("", f"{n:<18}"), (_MUTED, desc)], value=n)
        )
    return _select(prompt, choices + [_sep(), _back_choice()])


# --- Banner & main menu -----------------------------------------------------


def _job_counts() -> dict:
    counts = {"running": 0, "queued": 0}
    for j in store.list_jobs(limit=500):
        if j.status.value in counts:
            counts[j.status.value] += 1
    return counts


def _server_up(host: str, port: int) -> bool:
    import socket

    target = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        with socket.create_connection((target, port), timeout=0.2):
            return True
    except OSError:
        return False


def _banner(console) -> None:
    """Drawn once on entry: the AGENTHOOK wordmark, version + tagline, and a
    status line that answers 'is anything running, is the server up' at a glance."""
    from rich.text import Text

    try:
        n_inst = len(instances.list_names())
    except Exception:  # noqa: BLE001
        n_inst = 0
    counts = _job_counts()
    try:
        from .config import load_config

        cfg = load_config()
        up = _server_up(cfg.host, cfg.port)
        port = cfg.port
    except Exception:  # noqa: BLE001
        up, port = False, 8080

    from rich import box
    from rich.console import Group
    from rich.panel import Panel

    art = Text(_LOGO, style=f"bold {AMBER}", no_wrap=True, overflow="crop")
    subtitle = Text.from_markup(
        f"[{STONE}]v{_version()} · self-hosted agent task runner[/]"
    )

    srv = f"[{SAGE}]● up[/] [{STONE}]:{port}[/]" if up else f"[{STONE}]○ down[/]"
    status = Text.from_markup(
        f"[{BONE}]{n_inst} instance(s)[/][{STONE}] · [/]"
        f"[{AMBER}]{counts['running']} running[/][{STONE}] · [/]"
        f"[{STONE}]{counts['queued']} queued[/][{STONE}] · [/]"
        f"[{BONE}]server[/] {srv}"
    )
    hints = Text.from_markup(
        f"[{STONE}]↑↓ move · ↵ select · esc back · Ctrl+C 2× to quit[/]"
    )
    console.print()
    console.print(
        Panel(
            Group(art, Text(""), subtitle, Text(""), status, hints),
            box=box.ROUNDED,
            border_style=BORDER,
            padding=(0, 2),
            expand=True,
        )
    )


def main_menu() -> None:
    from rich.console import Console

    console = Console()
    if not _interactive():
        console.print("agenthook — run `agenthook --help` for commands.")
        return

    interrupts = 0
    while True:
        _clear(console)  # clear + hero banner on every screen change
        choice = _select(
            "Where to?",
            choices=[
                _action("instances", "register, configure & run agents"),
                _action("jobs", "watch and review executions"),
                _action("sessions", "durable threads across jobs"),
                _action("serve", "start the webhook server"),
                _sep(),
                _back_choice(_QUIT),
            ],
        )
        if choice is None:  # Ctrl+C on the top menu (footer says "Ctrl+C 2×")
            interrupts += 1
            if interrupts >= 2:
                break
            continue
        interrupts = 0
        if choice == _QUIT:
            break
        if choice == "instances":
            _instances_menu(console)
        elif choice == "jobs":
            _jobs_menu(console)
        elif choice == "sessions":
            _sessions_menu(console)
        elif choice == "serve":
            _serve(console)

    console.print(f"[{STONE}]bye.[/]")


# --- serve ------------------------------------------------------------------


def _serve(console) -> None:
    import questionary

    from .config import load_config, save_config

    while True:
        cfg = load_config()
        _clear(console, "serve")
        console.print(
            f"\n  [{BONE}]webhook server[/]   [{AMBER}]http://{cfg.host}:{cfg.port}[/]\n"
        )
        act = _select(
            "serve",
            [
                _action("start", "run the server (Ctrl+C to stop)"),
                _action("set port", f"current: {cfg.port}", value="set port"),
                _action("set host", f"current: {cfg.host}", value="set host"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "set port":
            val = questionary.text(
                "Port:", default=str(cfg.port), qmark="?", style=_style()
            ).ask()
            if val and val.strip().isdigit():
                cfg.port = int(val.strip())
                save_config(cfg)
                console.print(f"[{SAGE}]✓ port = {cfg.port}[/]")
            elif val:
                console.print(f"[{RUST}]not a number.[/]")
            _pause(console)
        elif act == "set host":
            val = questionary.text(
                "Host (0.0.0.0 = all interfaces):",
                default=cfg.host,
                qmark="?",
                style=_style(),
            ).ask()
            if val:
                cfg.host = val.strip()
                save_config(cfg)
                console.print(f"[{SAGE}]✓ host = {cfg.host}[/]")
            _pause(console)
        elif act == "start":
            try:
                import uvicorn

                store.init_db()
                console.print(
                    f"[{SAGE}]agenthook[/] serving on http://{cfg.host}:{cfg.port}\n"
                )
                uvicorn.run(
                    "agenthook.server:app",
                    host=cfg.host,
                    port=cfg.port,
                    workers=1,
                    log_level="info",
                )
            except KeyboardInterrupt:
                console.print(f"\n[{STONE}]server stopped.[/]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[{RUST}]error:[/] {exc}")
            _pause(console)


# --- Instances submenu ------------------------------------------------------


def _instances_menu(console) -> None:
    while True:
        names = instances.list_names()
        has = bool(names)
        _clear(console, "instances")
        _show_instances(console)  # the list, right up front (design req)
        if not has:
            console.print(
                f"\n  [{RUST}]⚠ no instances yet — choose “add” to create your first.[/]"
            )
        dis = None if has else "needs an instance"
        choice = _select(
            "instances — pick an action",
            choices=[
                _sep("interact"),
                _action("chat", "talk to the agent in a container", disabled=dis),
                _action("shell", "open a bash shell in a container", disabled=dis),
                _sep("manage"),
                _action("add", "register a new instance"),
                _action("view", "inspect config, repos, env & jobs", disabled=dis),
                _action("edit", "change config or authentication", disabled=dis),
                _action("remove", "delete an instance", disabled=dis),
                _sep(),
                _back_choice(),
            ],
        )
        if choice is None or choice == _BACK:
            return
        if choice == "chat":
            name = _pick_instance_or_none(console, "Chat with which instance?")
            if name and name != _BACK:
                _clear(console, "chat", name)
                from . import chat

                chat.repl(name, console=console)
        elif choice == "shell":
            name = _pick_instance_or_none(console, "Open a shell for which instance?")
            if name and name != _BACK:
                _clear(console, "shell", name)
                from . import shell as shell_mod

                try:
                    shell_mod.shell(name)
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[{RUST}]error:[/] {exc}")
                _pause(console)
        elif choice == "add":
            _instance_add(console)
        elif choice == "view":
            _instance_view(console)
        elif choice == "edit":
            _instance_edit(console)
        elif choice == "remove":
            _instance_delete(console)


def _pause(console) -> None:
    import questionary

    questionary.press_any_key_to_continue("  Enter to continue…").ask()


# --- Add instance — guided wizard (design §06) ------------------------------


def _instance_add(console) -> None:
    import questionary

    from .engines import available as engines_available
    from .instances import Instance, _derive_repo_name
    from .models import Deliverable

    style = _style()
    steps = [
        ("name", "name"),
        ("engine", "engine"),
        ("deliverable", "deliverable"),
        ("auth", "auth method"),
        ("model", "model"),
        ("branch", "branch base"),
        ("repos", "repositories"),
        ("key", "encryption key"),
    ]
    total = len(steps)
    vals: dict = {"repos": []}

    def rail(i: int) -> None:
        _clear(console, "instances", "add", right=f"step {i + 1} / {total}")
        console.print()
        for j, (key, label) in enumerate(steps):
            if j < i:
                shown = _wizard_value(key, vals)
                console.print(f"  [{SAGE}]✓[/] [dim]{label:<16}[/][{STONE}]{shown}[/]")
            elif j == i:
                console.print(f"  [{AMBER}]▸[/] [{AMBER} bold]{label:<16}[/]")
            else:
                console.print(f"  [{STONE}]·  {label:<16}[/]")
        console.print()

    i = 0
    while i < total - 1:  # steps 0..6 collect; step 7 (key) is handled after save
        rail(i)
        key = steps[i][0]
        if key == "name":
            ans = questionary.text("Instance name (slug):", qmark="?", style=style).ask()
            if ans is None:
                return
            if not ans:
                i = 0
                continue
            if instances.exists(ans):
                console.print(f"[{RUST}]instance {ans!r} already exists.[/]")
                _pause(console)
                continue
            vals["name"] = ans
        elif key == "engine":
            ans = _select("Engine:", (engines_available() or ["claude"]))
            if ans is None:
                i -= 1
                continue
            vals["engine"] = ans
        elif key == "deliverable":
            console.print(f"  [{STONE}]Default for requests that don't specify one.[/]")
            ans = _select("Default deliverable:", [d.value for d in Deliverable])
            if ans is None:
                i -= 1
                continue
            vals["deliverable"] = ans
        elif key == "auth":
            console.print(f"  [{STONE}]Each instance logs in on its own — never the host's.[/]")
            ans = _select(
                "How should this instance authenticate?",
                [
                    _action("subscription", "log in to a provider account (isolated)"),
                    _action("api-key", "paste a provider API key"),
                ],
            )
            if ans is None:
                i -= 1
                continue
            vals["auth"] = ans
        elif key == "model":
            ans = questionary.text(
                "Model (optional, Enter to skip):", qmark="?", style=style
            ).ask()
            if ans is None:
                i -= 1
                continue
            vals["model"] = ans or None
        elif key == "branch":
            ans = questionary.text("Base branch:", default="main", qmark="?", style=style).ask()
            if ans is None:
                i -= 1
                continue
            vals["branch"] = ans or "main"
        elif key == "repos":
            if not _wizard_repos(console, vals, _derive_repo_name):
                i -= 1
                continue
        i += 1

    # Build & save the instance, then the emphatic one-time key step (8/8).
    inst = Instance(
        name=vals["name"],
        engine=vals["engine"],
        engine_auth=vals["auth"],
        deliverable=vals.get("deliverable", "analysis"),
        model=vals.get("model"),
        branch_base=vals.get("branch", "main"),
        repos=vals.get("repos", []),
    )
    try:
        instances.save(inst)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[{RUST}]error:[/] {exc}")
        _pause(console)
        return
    key, fp = secrets.generate_key(inst)
    inst.key_fingerprint = fp
    instances.save(inst)
    _wizard_key_step(console, total, key, fp)

    # Per-instance auth — never inherited from the host's ambient login.
    if inst.engine_auth == "api-key":
        _set_api_key(console, inst)
    else:
        console.print(
            f"\n  [{STONE}]auth = subscription (isolated). Log this instance in:[/]\n"
            f"  [{AMBER}]agenthook login {inst.name}[/]   "
            f"[{STONE}]or instances ▸ edit ▸ authentication.[/]"
        )
    console.print(f"\n  [{SAGE}]✓ instance [bold]{inst.name}[/] created.[/]")
    _pause(console)


def _wizard_value(key: str, vals: dict) -> str:
    if key == "repos":
        n = len(vals.get("repos", []))
        return f"{n} repo(s)" if n else "none"
    if key == "model":
        return vals.get("model") or "default"
    return str(vals.get(key, ""))


def _wizard_repos(console, vals, derive) -> bool:
    """Sub-loop to build the repo pool. Returns False to step back."""
    import questionary

    style = _style()
    while True:
        repos = vals.get("repos", [])
        if repos:
            console.print(f"  [{STONE}]pool:[/] " + ", ".join(r["name"] for r in repos))
        act = _select(
            "Repositories (optional):",
            [
                _action("add", "add a repo to the pool"),
                _action("done", "continue", value="done"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return False
        if act == "done":
            return True
        url = questionary.text(
            "Repository URL:", default=_GH_PREFILL, qmark="?", style=style
        ).ask()
        if not url or url.strip() in ("", _GH_PREFILL):
            continue
        url = url.strip()
        rname = questionary.text(
            "Name:", default=derive(url), qmark="?", style=style
        ).ask()
        if not rname or not rname.strip():
            continue
        vals.setdefault("repos", []).append({"name": rname.strip(), "url": url})


def _wizard_key_step(console, total: int, key: str, fp: str) -> None:
    from rich.panel import Panel

    _clear(console, "instances", "add", right=f"step {total} / {total}")
    console.print(f"\n  [{CLAY}]▲ Encryption key — shown once[/]\n")
    console.print(
        Panel(
            f"[{AMBER} bold]{key}[/]\n\n"
            f"[dim]Encrypts this instance's secrets at rest.\n"
            f"It cannot be shown again — losing it means re-entering\n"
            f"every secret for this instance.[/]\n\n"
            f"[{STONE}]fingerprint: {fp}[/]",
            title="Save this key now",
            border_style=CLAY,
            padding=(1, 3),
            expand=False,
        )
    )
    import questionary

    questionary.press_any_key_to_continue(
        "  Enter once you've saved it…", style=_style()
    ).ask()


# --- View instance (design §07) ---------------------------------------------


def _instance_view(console) -> None:
    name = _pick_instance_or_none(console, "View which instance?")
    if not name or name == _BACK:
        return
    inst = instances.load(name)
    _clear(console, "instances", name)
    console.print()
    console.print(f"  {_inst_badge(inst)}  [{AMBER} bold]{name}[/]")
    console.print()

    _section(console, "config")
    _kv(console, "engine", inst.engine)
    _kv(console, "auth", inst.engine_auth)
    _kv(console, "deliverable", inst.deliverable)
    _kv(console, "branch base", inst.branch_base)
    _kv(console, "model", inst.model or "default", muted=not inst.model)

    repos = inst.resolved_repos()
    _section(console, f"repositories  ({len(repos)})")
    console.print(
        _table(
            ["repo", "branch base"],
            [(r.name, r.branch_base) for r in repos],
            "no repos in the pool",
        )
    )

    try:
        items = secrets.get_backend(inst).items(inst)
    except Exception:  # noqa: BLE001
        items = []
    _section(console, f"env  ({len(items)}, encrypted)")
    env_rows = []
    for ev in items:
        if ev.secret:
            env_rows.append((ev.name, "[dim]••••••••••••[/]", f"[{CLAY}]secret[/]"))
        else:
            env_rows.append((ev.name, f"[{CYAN}]{ev.value}[/]", f"[{STONE}]no[/]"))
    console.print(_table(["env", "value", "secret"], env_rows, "no variables"))

    jobs = [j for j in store.list_jobs(instance=name, limit=50)][:6]
    _section(console, "recent jobs")
    job_rows = [
        (j.id, _job_badge(j.status.value), j.deliverable.value, _ago(j.created_at))
        for j in jobs
    ]
    console.print(_table(["job", "status", "deliverable", "age"], job_rows, "no jobs yet"))
    _pause(console)


def _section(console, title: str) -> None:
    pad = max(0, 56 - len(title))
    console.print(f"\n  [{STONE}]─── {title} {'─' * pad}[/]")


def _kv(console, key: str, value: str, muted: bool = False) -> None:
    color = STONE if muted else BONE
    console.print(f"  [{STONE}]{key:<14}[/][{color}]{value}[/]")


def _table(columns: list[str], rows: list, empty_msg: str):
    """A rounded-border table (design-system box). When there are no rows it
    renders the same bordered box with the headers and a single, full-width
    'no data' message spanning all columns, in the error color."""
    from rich import box
    from rich.table import Table

    if rows:
        t = Table(
            box=box.ROUNDED,
            border_style=BORDER,
            header_style=f"bold {BONE}",
            pad_edge=False,
            expand=False,
        )
        for col in columns:
            t.add_column(col)
        for r in rows:
            t.add_row(*r)
        return t

    from rich.console import Group
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.text import Text

    head = Text("   ".join(columns), style=f"bold {BONE}")
    msg = Text(empty_msg, style=RUST, justify="center")
    return Panel(
        Group(head, Rule(style=BORDER), msg),
        box=box.ROUNDED,
        border_style=BORDER,
        padding=(0, 1),
        expand=False,
    )


# --- Delete instance --------------------------------------------------------


def _instance_delete(console) -> None:
    name = _pick_instance_or_none(console, "Remove which instance?")
    if not name or name == _BACK:
        return
    if not confirm(f"Delete {name!r} and its secrets? This is irreversible."):
        console.print(f"[{STONE}]cancelled.[/]")
        return
    instances.delete(name)
    console.print(f"[{SAGE}]✓ removed[/] {name}")
    _pause(console)


# --- Edit instance (design §08) ---------------------------------------------


def _instance_edit(console) -> None:
    name = _pick_instance_or_none(console, "Edit which instance?")
    if not name or name == _BACK:
        return
    while True:
        inst = instances.load(name)
        _clear(console, "instances", name, "edit")
        auth_v = "logged in" if _auth_state(inst) is True else (
            "via api-key" if _auth_state(inst) is None else "not logged in"
        )
        field = _select(
            "What do you want to change?",
            choices=[
                _sep("config"),
                _action("deliverable", inst.deliverable),
                _action("engine", inst.engine),
                _action("model", inst.model or "default"),
                _action("branch base", inst.branch_base, value="branch base"),
                _sep("connections"),
                _action("authentication", auth_v),
                _action("github (gh)", _gh_status(inst), value="github"),
                _action("webhook access", _webhook_status(inst), value="webhook"),
                _action("repositories", f"{len(inst.resolved_repos())} repos"),
                _action("env vars", f"{len(_env_items(inst))} vars", value="env vars"),
                _sep("state"),
                _action(
                    "resume" if inst.paused else "pause",
                    "paused — resume intake" if inst.paused else "running — pause intake",
                    value="pause",
                ),
                _action(
                    "rebuild shell",
                    "wipe the cached clone; rebuilds on next entry",
                    value="rebuild shell",
                ),
                _sep(),
                _back_choice("done"),
            ],
        )
        if field is None or field == "done":
            return
        if field == "deliverable":
            from .models import Deliverable

            val = _select("New deliverable:", [d.value for d in Deliverable])
            if val:
                inst.deliverable = val
                _save_inst(console, inst)
        elif field == "engine":
            from .engines import available as engines_available

            val = _select("New engine:", engines_available() or ["claude"])
            if val:
                inst.engine = val
                _save_inst(console, inst)
        elif field == "authentication":
            _edit_auth(console, name)
        elif field == "github":
            _edit_github(console, name)
        elif field == "webhook":
            _edit_webhook(console, name)
        elif field == "model":
            import questionary

            val = questionary.text(
                "Model (empty = none):", default=inst.model or "", qmark="?", style=_style()
            ).ask()
            inst.model = val or None
            _save_inst(console, inst)
        elif field == "branch base":
            import questionary

            val = questionary.text(
                "Base branch:", default=inst.branch_base, qmark="?", style=_style()
            ).ask()
            if val:
                inst.branch_base = val
                _save_inst(console, inst)
        elif field == "repositories":
            _edit_repos(console, name)
        elif field == "env vars":
            _edit_env(console, name)
        elif field == "pause":
            instances.set_paused(
                name, not inst.paused, "paused manually" if not inst.paused else None
            )
            console.print(f"[{SAGE}]ok[/]")
        elif field == "rebuild shell":
            if confirm("Destroy the cached workspace? The next shell will re-clone."):
                from . import shell as shell_mod

                freed = shell_mod.destroy(name)
                console.print(
                    f"[{SAGE}]✓ shell destroyed[/] "
                    f"[{STONE}](freed {_fmt_size(freed)} — rebuilds on next entry).[/]"
                )
                _pause(console)


def _auth_state(inst):
    try:
        from . import engine_auth

        return engine_auth.is_authenticated(inst)
    except Exception:  # noqa: BLE001
        return None


def _env_items(inst):
    try:
        return secrets.get_backend(inst).items(inst)
    except Exception:  # noqa: BLE001
        return []


def _save_inst(console, inst) -> None:
    try:
        instances.save(inst)
        console.print(f"[{SAGE}]✓ saved.[/]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[{RUST}]save error:[/] {exc}")


def _set_api_key(console, inst) -> None:
    import questionary

    from .engines import get_engine

    names = get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]
    key_name = names[0]
    val = questionary.password(
        f"{key_name} (stored as an encrypted instance secret):", qmark="?", style=_style()
    ).ask()
    if val:
        secrets.get_backend(inst).set(inst, key_name, val, True)
        console.print(f"[{SAGE}]✓ {key_name} saved (encrypted).[/]")
    else:
        console.print(f"[{CLAY}]cancelled.[/]")


# --- Instance authentication (design §09) -----------------------------------


def _edit_auth(console, name: str) -> None:
    from rich.panel import Panel

    from . import engine_auth

    while True:
        inst = instances.load(name)
        state = engine_auth.is_authenticated(inst)
        _clear(console, "instances", name, "authentication")
        console.print()
        console.print(
            Panel(
                f"[{STONE}]status   [/]{_auth_badge(state)}\n"
                f"[{STONE}]method   [/][{BONE}]{inst.engine_auth}"
                f"{' (isolated)' if inst.engine_auth == 'subscription' else ''}[/]\n"
                f"[{STONE}]engine   [/][{BONE}]{inst.engine}[/]\n"
                f"[{STONE}]scope    [/][dim]this instance only[/]",
                title=f"Authentication · {name}",
                border_style=BORDER,
                padding=(0, 2),
                expand=False,
            )
        )
        is_sub = inst.engine_auth == "subscription"
        first = (
            _action("relogin", "re-run the isolated login")
            if is_sub
            else _action("set key", "set / change the api-key", value="set key")
        )
        act = _select(
            "Manage authentication",
            choices=[
                first,
                _action("switch", "use the other method", value="switch"),
                _action("logout", "clear credentials & data", value="logout"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "relogin":
            try:
                from . import shell as shell_mod

                console.print(f"[{STONE}]opening isolated login… run /login, then exit (/exit).[/]")
                shell_mod.login(inst.name)
            except Exception as exc:  # noqa: BLE001
                console.print(f"[{RUST}]error:[/] {exc}")
            _pause(console)
        elif act == "set key":
            _set_api_key(console, inst)
            _pause(console)
        elif act == "switch":
            new = "api-key" if is_sub else "subscription"
            if confirm(f"Switch authentication to {new!r}?"):
                inst.engine_auth = new
                _save_inst(console, inst)
                if new == "api-key":
                    _set_api_key(console, instances.load(name))
                else:
                    console.print(
                        f"[{STONE}]now log in:[/] [{AMBER}]agenthook login {name}[/] "
                        f"[{STONE}](or 'relogin' here).[/]"
                    )
                _pause(console)
        elif act == "logout":
            if confirm(f"Log {name!r} out and wipe its isolated auth data?"):
                wiped = engine_auth.logout(inst)
                try:
                    from .engines import get_engine

                    for k in get_engine(inst.engine).auth_env_names(inst) or ["ANTHROPIC_API_KEY"]:
                        secrets.get_backend(inst).delete(inst, k)
                except Exception:  # noqa: BLE001
                    pass
                console.print(
                    f"[{SAGE}]✓ auth wiped.[/]" if wiped else f"[{STONE}]nothing to wipe.[/]"
                )
                _pause(console)


# --- GitHub (gh) auth — per-instance, like the engine (design §5) -----------


_GH_VARS = ("GH_TOKEN", "GITHUB_TOKEN")


def _gh_token_name(inst):
    """The name of the GitHub token secret on this instance, if any."""
    names = {ev.name for ev in _env_items(inst)}
    for n in _GH_VARS:
        if n in names:
            return n
    return None


def _gh_status(inst) -> str:
    return "token set" if _gh_token_name(inst) else "not set"


def _edit_github(console, name: str) -> None:
    """Per-instance GitHub access. gh/git authenticate via an encrypted PAT
    (GH_TOKEN) — isolated per instance, exactly like the engine's own auth, just
    carried as a secret rather than a config dir."""
    import questionary
    from rich.panel import Panel

    while True:
        inst = instances.load(name)
        tok = _gh_token_name(inst)
        has = tok is not None
        _clear(console, "instances", name, "github")
        console.print()
        status = f"[{SAGE}]● token set[/]" if has else f"[{RUST}]not set[/]"
        console.print(
            Panel(
                f"[{STONE}]status   [/]{status}\n"
                f"[{STONE}]variable [/][{BONE}]{tok or 'GH_TOKEN'}[/]\n"
                f"[{STONE}]scope    [/][dim]this instance only (encrypted)[/]\n"
                f"[{STONE}]used by  [/][dim]git push · gh pr create[/]",
                title=f"GitHub · {name}",
                border_style=BORDER,
                padding=(0, 2),
                expand=False,
            )
        )
        act = _select(
            "Manage GitHub access",
            [
                _action("set token", "store a PAT (encrypted)", value="set token"),
                _action("clear token", "remove the PAT", value="clear token"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "set token":
            val = questionary.password(
                "GH_TOKEN (PAT, stored as an encrypted secret):", qmark="?", style=_style()
            ).ask()
            if val:
                secrets.get_backend(inst).set(inst, "GH_TOKEN", val, True)
                console.print(f"[{SAGE}]✓ GH_TOKEN saved (encrypted).[/]")
            else:
                console.print(f"[{CLAY}]cancelled.[/]")
            _pause(console)
        elif act == "clear token":
            if has and confirm("Remove the GitHub token from this instance?"):
                for n in _GH_VARS:
                    try:
                        secrets.get_backend(inst).delete(inst, n)
                    except Exception:  # noqa: BLE001
                        pass
                console.print(f"[{SAGE}]✓ token cleared.[/]")
                _pause(console)
            elif not has:
                console.print(f"[{STONE}]no token set.[/]")
                _pause(console)


# --- Webhook access — schemes + IP allowlist (design §12) -------------------


def _webhook_status(inst) -> str:
    headers = (inst.webhook_auth or {}).get("headers") or []
    if not headers and (inst.webhook_auth or {}).get("header_name"):
        headers = [1]  # legacy single header
    return f"{len(headers)} header(s)" if headers else "open (no auth)"


def _header_env(name: str) -> str:
    """Encrypted-secret env var name that backs a required header's value."""
    import re

    safe = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "X"
    return f"AGENTHOOK_HEADER_{safe}"


def _mask_value(v: str) -> str:
    """Show the first few characters, obfuscate the rest."""
    if not v:
        return ""
    keep = min(3, len(v))
    return v[:keep] + "•" * 8


def _edit_webhook(console, name: str) -> None:
    """Webhook protection by required request headers: add as many key+value
    pairs as you like. The endpoint accepts a request only if every configured
    header matches. Values are stored encrypted (shown masked here)."""
    import questionary

    while True:
        inst = instances.load(name)
        wa = dict(inst.webhook_auth or {})
        headers = list(wa.get("headers") or [])
        backend = secrets.get_backend(inst)
        _clear(console, "instances", name, "webhook access")
        console.print()
        console.print(
            f"  [dim]POST /hook/{name}  ·  a request must send every header below[/]"
        )
        rows = []
        for h in headers:
            val = ""
            try:
                val = backend.get(inst, h.get("value_env", "")) or ""
            except Exception:  # noqa: BLE001
                val = ""
            rows.append((h.get("name", ""), f"[dim]{_mask_value(val)}[/]"))
        console.print(
            _table(["header", "value"], rows, "no headers — requests are unauthenticated")
        )
        act = _select(
            "Manage request headers",
            [
                _action("add", "add a required header (key + value)"),
                _action("remove", "remove a header"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "add":
            key = questionary.text(
                "Header name (e.g. X-API-Key):", qmark="?", style=_style()
            ).ask()
            if not key or not key.strip():
                continue
            key = key.strip()
            value = questionary.password(
                "Header value (stored encrypted):", qmark="?", style=_style()
            ).ask()
            if not value:
                console.print(f"[{CLAY}]cancelled (no value).[/]")
                _pause(console)
                continue
            env_name = _header_env(key)
            backend.set(inst, env_name, value, True)
            headers = [h for h in headers if h.get("name", "").lower() != key.lower()]
            headers.append({"name": key, "value_env": env_name})
            wa["headers"] = headers
            schemes = list(wa.get("schemes") or [])
            if "header" not in schemes:
                schemes.append("header")
            wa["schemes"] = schemes
            inst.webhook_auth = wa
            _save_inst(console, inst)
        elif act == "remove":
            if not headers:
                continue
            target = _select(
                "Remove which header?",
                [h.get("name") for h in headers] + [_sep(), _back_choice()],
            )
            if not target or target == _BACK:
                continue
            for h in headers:
                if h.get("name") == target:
                    try:
                        backend.delete(inst, h.get("value_env", ""))
                    except Exception:  # noqa: BLE001
                        pass
            headers = [h for h in headers if h.get("name") != target]
            wa["headers"] = headers
            if not headers:
                wa["schemes"] = [s for s in (wa.get("schemes") or []) if s != "header"]
            inst.webhook_auth = wa
            _save_inst(console, inst)


# --- Repo pool editor (design §11) ------------------------------------------


_GH_PREFILL = "https://github.com/"


def _migrate_legacy_repo(inst) -> None:
    from .instances import _derive_repo_name

    if inst.repo and not inst.repos:
        inst.repos = [{"name": _derive_repo_name(inst.repo), "url": inst.repo}]
        inst.repo = None


def _edit_repos(console, name: str) -> None:
    import questionary

    from .instances import _derive_repo_name

    style = _style()
    while True:
        inst = instances.load(name)
        repos = inst.resolved_repos()
        _clear(console, "instances", name, "repositories")
        console.print()
        console.print(
            _table(
                ["repo", "url", "branch base"],
                [(r.name, r.url, r.branch_base) for r in repos],
                "empty pool — add a repository",
            )
        )
        act = _select(
            "Manage repositories",
            [
                _action("add", "add a repository"),
                _action("edit", "change a repository"),
                _action("remove", "remove a repository"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "add":
            # URL comes prefilled with the GitHub base — continue typing or clear it.
            url = questionary.text(
                "Repository URL:", default=_GH_PREFILL, qmark="?", style=style
            ).ask()
            if not url or url.strip() in ("", _GH_PREFILL):
                continue
            url = url.strip()
            rname = questionary.text(
                "Name:", default=_derive_repo_name(url), qmark="?", style=style
            ).ask()
            if not rname or not rname.strip():
                continue
            rname = rname.strip()
            branch = questionary.text(
                "Default branch (empty = inherit):", qmark="?", style=style
            ).ask()
            if rname in inst.repo_names():
                console.print(f"[{RUST}]repo {rname!r} already in the pool.[/]")
                _pause(console)
                continue
            _migrate_legacy_repo(inst)
            entry = {"name": rname, "url": url}
            if branch and branch.strip():
                entry["branch_base"] = branch.strip()
            inst.repos.append(entry)
            _save_inst(console, inst)
        elif act == "edit":
            if not repos:
                continue
            target = _select(
                "Edit which?", [r.name for r in repos] + [_sep(), _back_choice()]
            )
            if not target or target == _BACK:
                continue
            _migrate_legacy_repo(inst)
            raw = next(
                (r for r in inst.repos if (r.get("name") or _derive_repo_name(r["url"])) == target),
                None,
            )
            if raw is None:
                continue
            new_url = questionary.text(
                "Repository URL:", default=raw.get("url", ""), qmark="?", style=style
            ).ask()
            if new_url is None:
                continue
            new_name = questionary.text(
                "Name:",
                default=raw.get("name") or _derive_repo_name(raw["url"]),
                qmark="?",
                style=style,
            ).ask()
            if not new_name or not new_name.strip():
                continue
            new_name = new_name.strip()
            new_branch = questionary.text(
                "Default branch (empty = inherit):",
                default=raw.get("branch_base", ""),
                qmark="?",
                style=style,
            ).ask()
            if new_name != target and new_name in inst.repo_names():
                console.print(f"[{RUST}]repo {new_name!r} already in the pool.[/]")
                _pause(console)
                continue
            entry = {"name": new_name, "url": (new_url.strip() or raw["url"])}
            if new_branch and new_branch.strip():
                entry["branch_base"] = new_branch.strip()
            inst.repos = [
                entry if (r.get("name") or _derive_repo_name(r["url"])) == target else r
                for r in inst.repos
            ]
            _save_inst(console, inst)
        elif act == "remove":
            if not repos:
                continue
            target = _select(
                "Remove which?", [r.name for r in repos] + [_sep(), _back_choice()]
            )
            if not target or target == _BACK:
                continue
            inst.repos = [
                r
                for r in inst.repos
                if (r.get("name") or _derive_repo_name(r["url"])) != target
            ]
            _save_inst(console, inst)


# --- Env vars editor (design §10) -------------------------------------------


def _edit_env(console, name: str) -> None:
    import questionary

    style = _style()
    while True:
        inst = instances.load(name)
        backend = secrets.get_backend(inst)
        items = backend.items(inst)
        _clear(console, "instances", name, "env vars")
        rows = []
        for ev in items:
            if ev.secret:
                rows.append((ev.name, "[dim]••••••••••••[/]", f"[{CLAY}]secret[/]"))
            else:
                rows.append((ev.name, f"[{CYAN}]{ev.value}[/]", f"[{STONE}]no[/]"))
        console.print()
        console.print(
            _table(
                ["env", "value", "secret"],
                rows,
                "no variables yet — choose “set” to add one",
            )
        )
        act = _select(
            "Manage variables",
            [
                _action("set", "add or update a variable"),
                _action("remove", "delete a variable"),
                _sep(),
                _back_choice(),
            ],
        )
        if act is None or act == _BACK:
            return
        if act == "set":
            key = questionary.text("Name (KEY):", qmark="?", style=style).ask()
            if not key:
                continue
            value = questionary.text("Value:", qmark="?", style=style).ask() or ""
            is_secret = bool(
                questionary.confirm(
                    "Secret? (encrypt & obfuscate)", default=True, qmark="?", style=style
                ).ask()
            )
            backend.set(inst, key, value, is_secret)
            console.print(f"[{SAGE}]✓ set[/] {key}{' (secret)' if is_secret else ''}")
        elif act == "remove":
            if not items:
                continue
            target = _select(
                "Remove which?", [ev.name for ev in items] + [_sep(), _back_choice()]
            )
            if not target or target == _BACK:
                continue
            backend.delete(inst, target)
            console.print(f"[{SAGE}]✓ removed[/] {target}")


# --- Instance listing -------------------------------------------------------


def _fmt_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _show_instances(console) -> None:
    from . import shell as shell_mod

    rows = []
    for inst in instances.list_all():
        names = inst.repo_names()
        built = shell_mod.is_built(inst.name)
        shell_cell = (
            f"[{SAGE}]●[/] {_fmt_size(shell_mod.disk_usage(inst.name))}"
            if built
            else f"[{STONE}]○ empty[/]"
        )
        rows.append(
            (
                f"[{AMBER}]{inst.name}[/]",
                inst.engine,
                inst.deliverable,
                ", ".join(names) if names else "-",
                _inst_badge(inst),
                shell_cell,
            )
        )
    console.print()
    console.print(
        _table(
            ["name", "engine", "deliverable", "repos", "status", "shell"],
            rows,
            "no instances yet — choose “add” to create one",
        )
    )


# --- Jobs (design §12 / §13) ------------------------------------------------


def _jobs_menu(console) -> None:
    while True:
        _clear(console, "jobs")
        jobs = store.list_jobs(limit=20)
        if not jobs:
            console.print(f"\n  [{RUST}]no jobs yet.[/]")
        header = f"{'ID':<14}{'INSTANCE':<14}{'STATUS':<20}{'DELIVERABLE':<10}AGE"
        choice = _select(
            f"jobs · {len(jobs)} recent",
            [_job_choice(j) for j in jobs]
            + [_sep(), _action("refresh", "reload the list"), _back_choice()],
            header=header,
        )
        if choice is None or choice == _BACK:
            return
        if choice == "refresh":
            continue
        _job_view(console, choice)


def _job_view(console, job_id: str) -> None:
    job = store.get_job(job_id)
    if not job:
        console.print(f"[{RUST}]job not found.[/]")
        _pause(console)
        return
    _clear(console, "jobs", job.id)
    status = job.status.value
    repos = job.request.get("repos")
    repo_s = ", ".join(repos) if repos else "—"
    console.print()
    console.print(
        f"  [{AMBER} bold]{job.id}[/]   [{BONE}]{job.instance}[/]"
        f"[{STONE}]   ·  {job.deliverable.value}   ·  {repo_s}[/]"
    )
    console.print()
    console.print("  " + _step_rail(status))
    console.print()

    cost = f"${job.usage.cost_usd:.4f}" if job.usage.cost_usd else "—"
    toks = (job.usage.input_tokens or 0) + (job.usage.output_tokens or 0)
    tok_s = f"{toks / 1000:.1f}k tok" if toks else "—"
    console.print(
        f"  {_job_badge(status)}[{STONE}]   elapsed {_elapsed(job)}   ·  {cost}   ·  {tok_s}[/]"
    )
    if job.error_class:
        console.print(f"  [{RUST}]{job.error_class}[/] [dim]{job.error_message or ''}[/]")
    if job.pr_url:
        console.print(f"  [{CYAN}]PR:[/] {job.pr_url}")

    _section(console, "agent log")
    for line in _log_tail(job):
        console.print(f"  [{CYAN}]◆[/] [dim]{line}[/]")

    if status == "awaiting_approval":
        _approve_flow(console, job)
        return

    actions = [_action("logs", "show the full job log", value="logs")]
    if not job.status.terminal:
        actions.append(_action("cancel", "stop this job", value="cancel"))
    actions += [_sep(), _back_choice()]
    act = _select("job", actions)
    if act == "logs":
        _show_logs(console, job)
        _pause(console)
    elif act == "cancel":
        if confirm(f"Cancel job {job.id}?"):
            job.status = job.status.__class__.INTERRUPTED
            store.save_job(job)
            console.print(f"[{CLAY}]cancel requested.[/]")
            _pause(console)


def _step_rail(status: str) -> str:
    """A heuristic clone→plan→edit→checks→deliver rail keyed off status."""
    names = ["clone", "plan", "edit", "checks", "deliver"]
    done_all = status in ("success",)
    if done_all:
        marks = [("✓", SAGE)] * 5
    elif status == "awaiting_approval":
        marks = [("✓", SAGE), ("✓", SAGE), ("◷", LILAC), ("·", STONE), ("·", STONE)]
    elif status == "failed-checks":
        marks = [("✓", SAGE), ("✓", SAGE), ("✓", SAGE), ("✗", RUST), ("·", STONE)]
    elif status in ("error", "timeout", "blocked", "interrupted"):
        marks = [("✓", SAGE), ("✗", RUST), ("·", STONE), ("·", STONE), ("·", STONE)]
    elif status == "running":
        marks = [("✓", SAGE), ("✓", SAGE), ("▸", AMBER), ("·", STONE), ("·", STONE)]
    else:  # queued / rejected / expired
        marks = [("·", STONE)] * 5
    parts = []
    for (glyph, color), nm in zip(marks, names):
        parts.append(f"[{color}]{glyph} {nm}[/]")
    return f"[{STONE}] ── [/]".join(parts)


def _log_tail(job, n: int = 6) -> list[str]:
    from . import paths

    path = paths.job_log(job.instance, job.id)
    if path.exists():
        lines = [ln.rstrip() for ln in path.read_text().splitlines() if ln.strip()]
        if lines:
            return lines[-n:]
    if job.result and job.result.text:
        return [ln for ln in job.result.text.strip().splitlines()[:n]]
    return ["(no log yet)"]


def _show_logs(console, job) -> None:
    from . import paths

    path = paths.job_log(job.instance, job.id)
    console.print()
    if path.exists():
        console.print(path.read_text())
    elif job.result and job.result.text:
        console.print(job.result.text)
    else:
        console.print(f"[{STONE}](no logs yet)[/]")


def _approve_flow(console, job) -> None:
    from rich.panel import Panel

    plan_text = ""
    if job.result and job.result.text:
        plan_text = job.result.text
    plan_text = plan_text or job.metadata.get("plan", "(no plan text captured)")
    console.print()
    console.print(
        f"  [{LILAC}]◷ awaiting_approval[/][{STONE}]   the agent paused for review[/]"
    )
    console.print(
        Panel(
            plan_text.strip()[:1200],
            title=f"Plan · {job.id}",
            border_style=LILAC,
            padding=(1, 2),
            expand=False,
        )
    )
    act = _select(
        "Approve this plan?",
        [
            _action("approve", "run the plan as proposed"),
            _action("edit", "send a note back & replan"),
            _action("reject", "stop the job here"),
            _sep(),
            _back_choice(),
        ],
    )
    from .models import JobStatus

    if act == "approve":
        job.status = JobStatus.QUEUED
        store.save_job(job)
        console.print(f"[{SAGE}]✓ approved — re-queued for apply (the server picks it up).[/]")
        _pause(console)
    elif act == "edit":
        import questionary

        note = questionary.text("Note to the agent:", qmark="?", style=_style()).ask()
        if note:
            job.metadata["review_note"] = note
            job.status = JobStatus.QUEUED
            store.save_job(job)
            console.print(f"[{SAGE}]✓ sent — re-queued to replan.[/]")
            _pause(console)
    elif act == "reject":
        if confirm("Reject this plan and stop the job?"):
            job.status = JobStatus.REJECTED
            store.save_job(job)
            console.print(f"[{CLAY}]rejected.[/]")
            _pause(console)


# --- Sessions (design §14) --------------------------------------------------


def _sessions_menu(console) -> None:
    while True:
        _clear(console, "sessions")
        sessions = store.list_sessions()
        if not sessions:
            console.print(f"\n  [{RUST}]no sessions yet.[/]")
        import questionary

        choices = []
        for s in sessions:
            choices.append(
                questionary.Choice(
                    title=[
                        (f"fg:{LILAC}", f"{s.thread_key:<18}"),
                        ("", f"{s.instance:<14}"),
                        (_MUTED, f"{s.job_count:<6}{_ago(s.updated_at)}"),
                    ],
                    value=s.id,
                )
            )
        header = f"{'THREAD KEY':<18}{'INSTANCE':<14}{'JOBS':<6}LAST"
        choice = _select(
            "sessions", choices + [_sep(), _back_choice()], header=header
        )
        if choice is None or choice == _BACK:
            return
        _session_view(console, choice)


def _session_view(console, session_id: str) -> None:
    sess = store.get_session(session_id)
    if not sess:
        console.print(f"[{RUST}]session not found.[/]")
        _pause(console)
        return
    _clear(console, "sessions", sess.thread_key)
    jobs = [j for j in store.list_jobs(instance=sess.instance, limit=200)
            if j.thread_key == sess.thread_key]
    console.print()
    console.print(
        f"  [{LILAC} bold]{sess.thread_key}[/]   [{BONE}]{sess.instance}[/]"
        f"[{STONE}]   ·  {len(jobs)} jobs   ·  opened {_ago(sess.created_at)}[/]"
    )
    first_prompt = jobs[-1].prompt if jobs else ""
    if first_prompt:
        _section(console, "thread context")
        console.print(f'  [dim]“{first_prompt.strip()[:120]}”[/]')

    _section(console, "jobs in this thread")
    if jobs:
        for j in jobs:
            console.print(
                f"  [{STONE}]{j.id:<14}[/]{_job_badge(j.status.value):<24} "
                f"[{STONE}]{j.deliverable.value:<10}{_ago(j.created_at)}[/]"
            )
    else:
        console.print(f"  [{STONE}]no jobs yet.[/]")

    act = _select(
        "session",
        [
            _action("open job", "inspect a job in this thread", value="open job"),
            _action("resume", "resume this thread in chat", value="resume"),
            _sep(),
            _back_choice(),
        ],
    )
    if act == "open job" and jobs:
        choice = _select("Open which job?", [_job_choice(j) for j in jobs] + [_sep(), _back_choice()])
        if choice and choice != _BACK:
            _job_view(console, choice)
    elif act == "resume":
        _clear(console, "chat", sess.instance, f"#{sess.thread_key}")
        from . import chat

        chat.repl(sess.instance, thread_key=sess.thread_key, console=console)
