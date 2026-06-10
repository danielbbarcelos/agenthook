"""agenthook command-line interface (DESIGN.md §4, §23, §32).

Two levels, always: plain scriptable commands (for automation/CI) and a friendly
layer with arrow-key pickers (questionary) and Rich output. No essential flow
depends on interactivity.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config as config_mod
from . import instances, paths, secrets, store, tui
from .instances import Instance
from .models import Deliverable, Job, Mode

app = typer.Typer(help="agenthook — run agentic coding CLIs via webhooks", no_args_is_help=False)
instance_app = typer.Typer(help="Manage instances")
repo_app = typer.Typer(help="Manage an instance's repo pool")
env_app = typer.Typer(help="Manage encrypted env vars")
jobs_app = typer.Typer(help="Inspect jobs")
sessions_app = typer.Typer(help="Inspect sessions")
service_app = typer.Typer(help="Control the systemd daemon")
app.add_typer(instance_app, name="instance")
instance_app.add_typer(repo_app, name="repo")
app.add_typer(env_app, name="env")
app.add_typer(jobs_app, name="jobs")
app.add_typer(sessions_app, name="sessions")
app.add_typer(service_app, name="service")

console = Console()


def _err(msg: str) -> None:
    console.print(f"[bold red]error:[/] {msg}")
    raise typer.Exit(1)


def _parse_repo_sel(value: Optional[str]) -> Optional[list]:
    """Parse a per-job repo *selection*: ``None`` -> all, ``''`` -> none ([]),
    ``'a,b'`` -> subset."""
    if value is None:
        return None
    return [x.strip() for x in value.split(",") if x.strip()]


def _parse_repos(specs: Optional[List[str]]) -> list[dict]:
    """Parse repeated --repo values (``URL`` or ``name=URL``) into pool entries."""
    from .instances import _derive_repo_name

    repos: list[dict] = []
    for spec in specs or []:
        if "=" in spec:
            rname, url = spec.split("=", 1)
            repos.append({"name": rname.strip(), "url": url.strip()})
        else:
            repos.append({"name": _derive_repo_name(spec), "url": spec.strip()})
    return repos


# --- instance ---------------------------------------------------------------


@instance_app.command("add")
def instance_add(
    name: str,
    repo: Optional[List[str]] = typer.Option(
        None, "--repo", help="repeatable; URL or name=URL. Multiple repos are checked out side by side."
    ),
    engine: str = typer.Option("claude", "--engine"),
    engine_auth: str = typer.Option("api-key", "--engine-auth"),
    deliverable: str = typer.Option("analysis", "--deliverable"),
    model: Optional[str] = typer.Option(None, "--model"),
    branch: str = typer.Option("main", "--branch"),
    on_result: str = typer.Option("logs", "--on-result", help="comma list: logs,output,callback,notify"),
    callback_url: Optional[str] = typer.Option(None, "--callback-url"),
    pr_branch: str = typer.Option("agenthook/job-{id}", "--pr-branch"),
):
    """Create an instance and generate its (immutable) encryption key."""
    if instances.exists(name):
        _err(f"instance {name!r} already exists")
    repos = _parse_repos(repo)
    inst = Instance(
        name=name,
        engine=engine,
        repos=repos,
        engine_auth=engine_auth,
        deliverable=deliverable,
        model=model,
        branch_base=branch,
        on_result=[x.strip() for x in on_result.split(",") if x.strip()],
        callback_url=callback_url,
        pr_branch=pr_branch,
    )
    instances.save(inst)
    key, fp = secrets.generate_key(inst)
    inst.key_fingerprint = fp
    instances.save(inst)
    console.print(
        Panel(
            f"[bold]Instance [cyan]{name}[/] created.[/]\n\n"
            f"[yellow]Encryption key (shown ONCE — store it safely):[/]\n[bold]{key}[/]\n\n"
            f"fingerprint: {fp}",
            title="🔐 keep this key",
            border_style="yellow",
        )
    )


@instance_app.command("list")
def instance_list():
    table = Table("name", "engine", "deliverable", "repos", "paused")
    for inst in instances.list_all():
        names = inst.repo_names()
        repos = ", ".join(names) if names else "-"
        table.add_row(
            inst.name, inst.engine, inst.deliverable, repos,
            "[red]yes[/]" if inst.paused else "no",
        )
    console.print(table)


@instance_app.command("show")
def instance_show(name: Optional[str] = typer.Argument(None)):
    name = name or tui.pick_instance()
    inst = _load(name)
    console.print_json(json.dumps(inst.to_dict(), default=str))


@instance_app.command("rm")
def instance_rm(name: str, yes: bool = typer.Option(False, "--yes")):
    if not yes and not tui.confirm(f"Delete instance {name!r} and its secrets?"):
        raise typer.Exit()
    instances.delete(name)
    console.print(f"deleted {name}")


@instance_app.command("resume")
def instance_resume(name: str):
    """Reactivate an instance paused by the circuit breaker (§17)."""
    instances.set_paused(name, False)
    console.print(f"[green]resumed[/] {name}")


@repo_app.command("add")
def repo_add(
    name: str,
    spec: str = typer.Argument(..., help="URL or name=URL"),
    branch: Optional[str] = typer.Option(None, "--branch", help="base branch for this repo"),
):
    """Add a repository to an instance's pool."""
    inst = _load(name)
    entry = _parse_repos([spec])[0]
    if branch:
        entry["branch_base"] = branch
    if entry["name"] in inst.repo_names():
        _err(f"repo {entry['name']!r} already in pool")
    if inst.repo and not inst.repos:  # migrate legacy single repo into the pool
        inst.repos = [{"name": instances._derive_repo_name(inst.repo), "url": inst.repo}]
        inst.repo = None
    inst.repos.append(entry)
    instances.save(inst)
    console.print(f"added repo [cyan]{entry['name']}[/] to {name}")


@repo_app.command("rm")
def repo_rm(name: str, repo: str):
    """Remove a repository from an instance's pool by name."""
    inst = _load(name)
    before = len(inst.repos)
    inst.repos = [r for r in inst.repos if (r.get("name") or instances._derive_repo_name(r["url"])) != repo]
    if len(inst.repos) == before:
        _err(f"repo {repo!r} not in pool of {name!r}")
    instances.save(inst)
    console.print(f"removed repo {repo!r} from {name}")


@repo_app.command("list")
def repo_list(name: str):
    """List the repositories in an instance's pool."""
    inst = _load(name)
    table = Table("name", "url", "branch_base")
    for r in inst.resolved_repos():
        table.add_row(r.name, r.url, r.branch_base)
    console.print(table)


# --- env --------------------------------------------------------------------


@env_app.command("set")
def env_set(name: str, key: str, value: str, secret: bool = typer.Option(False, "--secret")):
    inst = _load(name)
    secrets.get_backend(inst).set(inst, key, value, secret)
    console.print(f"set {key} on {name}{' (secret)' if secret else ''}")


@env_app.command("get")
def env_get(name: str, key: str):
    inst = _load(name)
    backend = secrets.get_backend(inst)
    for ev in backend.items(inst):
        if ev.name == key:
            console.print(secrets.obfuscate(ev.value) if ev.secret else ev.value)
            return
    _err(f"{key} not found")


@env_app.command("list")
def env_list(name: str):
    inst = _load(name)
    table = Table("key", "value", "secret")
    for ev in secrets.get_backend(inst).items(inst):
        shown = secrets.obfuscate(ev.value) if ev.secret else ev.value
        table.add_row(ev.name, shown, "yes" if ev.secret else "no")
    console.print(table)


@env_app.command("rm")
def env_rm(name: str, key: str):
    inst = _load(name)
    secrets.get_backend(inst).delete(inst, key)
    console.print(f"removed {key}")


# --- instance config setters ------------------------------------------------


@app.command("context")
def context_set(name: str, file: Path = typer.Option(..., "--file", exists=True)):
    """Set the context-file template (CLAUDE.md/AGENTS.md/…) for an instance."""
    inst = _load(name)
    inst.context_template = file.read_text()
    instances.save(inst)
    console.print(f"context template set on {name}")


@app.command("auth")
def auth_set(
    name: str,
    scheme: str = typer.Option(..., "--scheme", help="bearer|hmac|header|ip-allow (comma for several)"),
    header_name: Optional[str] = typer.Option(None, "--header-name"),
    ip_allow: Optional[str] = typer.Option(None, "--ip-allow", help="comma list of CIDRs"),
    notify_channel: Optional[str] = typer.Option(None, "--notify-channel"),
):
    """Configure webhook endpoint protection (§12)."""
    inst = _load(name)
    cfg = dict(inst.webhook_auth or {})
    cfg["schemes"] = [s.strip() for s in scheme.split(",") if s.strip()]
    if header_name:
        cfg["header_name"] = header_name
    if ip_allow:
        cfg["ip_allow"] = [c.strip() for c in ip_allow.split(",")]
    if notify_channel:
        cfg["notify_channel"] = notify_channel
    inst.webhook_auth = cfg
    instances.save(inst)
    console.print(f"webhook auth set on {name}: {cfg['schemes']}")


@app.command("template")
def template_set(name: str, request_type: str, file: Path = typer.Option(..., "--file", exists=True)):
    """Set a per-request_type prompt template (§14)."""
    inst = _load(name)
    inst.templates[request_type] = file.read_text()
    instances.save(inst)
    console.print(f"template '{request_type}' set on {name}")


@app.command("mcp")
def mcp_set(name: str, file: Path = typer.Option(..., "--file", exists=True)):
    """Set MCP servers config (YAML) for an instance (§25)."""
    import yaml

    inst = _load(name)
    inst.mcp = yaml.safe_load(file.read_text()) or {}
    instances.save(inst)
    console.print(f"mcp set on {name} ({len(inst.mcp)} servers)")


@app.command("verify")
def verify_set(
    name: str,
    checks: str = typer.Option(..., "--checks", help="comma-separated commands"),
    setup: Optional[str] = typer.Option(None, "--setup"),
    gate: bool = typer.Option(True, "--gate/--no-gate"),
    max_fix_iterations: int = typer.Option(3, "--max-fix-iterations"),
):
    """Configure the verification self-heal loop (§18)."""
    inst = _load(name)
    inst.verify = {
        "checks": [c.strip() for c in checks.split(",") if c.strip()],
        "gate": gate,
        "max_fix_iterations": max_fix_iterations,
    }
    if setup:
        inst.verify["setup"] = setup
    instances.save(inst)
    console.print(f"verify set on {name}")


# --- apply / serve / service ------------------------------------------------


@app.command("apply")
def apply_cmd(
    file: Path = typer.Option("agenthook.yaml", "-f", "--file"),
    prune: bool = typer.Option(False, "--prune"),
):
    """Reconcile instances from a declarative agenthook.yaml (§21)."""
    if not file.exists():
        _err(f"{file} not found")
    report = config_mod.apply_file(file, prune=prune)
    for action, names in report.items():
        if names:
            console.print(f"[bold]{action}:[/] {', '.join(names)}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
):
    """Run the webhook server (embedded uvicorn — no Apache/nginx needed)."""
    import uvicorn

    store.init_db()
    console.print(f"[green]agenthook[/] serving on http://{host}:{port}")
    uvicorn.run("agenthook.server:app", host=host, port=port, workers=1, log_level="info")


@app.command("install-service")
def install_service(
    port: int = typer.Option(8080, "--port"),
    user_unit: bool = typer.Option(True, "--user/--system"),
    write: bool = typer.Option(False, "--write"),
):
    """Generate a systemd unit for the daemon (§10)."""
    import shutil

    exe = shutil.which("agenthook") or "agenthook"
    unit = f"""[Unit]
Description=agenthook webhook daemon
After=network.target docker.service

[Service]
ExecStart={exe} serve --host 0.0.0.0 --port {port}
Restart=on-failure
Environment=AGENTHOOK_HOME=%h/.agenthook

[Install]
WantedBy=default.target
"""
    if write:
        dest = Path.home() / ".config/systemd/user/agenthook.service"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(unit)
        console.print(f"wrote {dest}\nenable with: systemctl --user enable --now agenthook")
    else:
        console.print(unit)


@service_app.command("start")
def service_start():
    _systemctl("start")


@service_app.command("stop")
def service_stop():
    _systemctl("stop")


@service_app.command("status")
def service_status():
    _systemctl("status")


@service_app.command("logs")
def service_logs():
    import subprocess

    subprocess.run(["journalctl", "--user", "-u", "agenthook", "-f"])


def _systemctl(action: str) -> None:
    import subprocess

    subprocess.run(["systemctl", "--user", action, "agenthook"])


# --- run / dry-run / send ---------------------------------------------------


@app.command("run")
def run_cmd(
    name: str,
    prompt: Optional[str] = typer.Option(None, "--prompt"),
    deliverable: Optional[str] = typer.Option(None, "--deliverable"),
    mode: Optional[str] = typer.Option(None, "--mode"),
    thread_key: Optional[str] = typer.Option(None, "--thread-key"),
    repos: Optional[str] = typer.Option(
        None, "--repos", help="comma list of repo names to use (omit=all, ''=none)"
    ),
):
    """Run a job locally (synchronous), bypassing the webhook (§4, P1)."""
    from . import runner

    inst = _load(name)
    store.init_db()
    job = _build_job(inst, prompt, deliverable, mode, thread_key, repos=_parse_repo_sel(repos))
    store.create_job(job)
    console.print(f"running {job.id} …")
    job = runner.run_job(job, log_cb=lambda m: console.print(f"[dim]{m}[/]"))
    _print_job_result(job)


@app.command("enter")
def enter_cmd(
    name: str,
    repos: Optional[str] = typer.Option(
        None, "--repos", help="comma list of repo names to use (omit=all, ''=none)"
    ),
    deliverable: Optional[str] = typer.Option(
        None, "--deliverable", help="default analysis (read-only chat)"
    ),
    thread_key: Optional[str] = typer.Option(
        None, "--thread-key", help="resume/continue a named conversation"
    ),
):
    """Open an interactive chat REPL against an instance (multi-turn session)."""
    from . import chat

    inst = _load(name)
    chat.repl(
        inst.name,
        repos=_parse_repo_sel(repos),
        deliverable=deliverable,
        thread_key=thread_key,
        console=console,
    )


@app.command("login")
def login_cmd(name: str):
    """Log a subscription account into the instance's ISOLATED auth dir.

    Opens the engine pointed at ``~/.agenthook/auth/<instance>/`` — the host's
    own login (~/.claude) is never used. Run /login inside, then exit.
    """
    from . import engine_auth

    inst = _load(name)
    try:
        argv, _env = engine_auth.login_env(inst)
    except RuntimeError as exc:
        _err(str(exc))
    console.print(
        f"abrindo [cyan]{argv[0]}[/] isolado para [cyan]{name}[/]  "
        f"[dim](config: {engine_auth.auth_dir_for(inst)})[/]\n"
        f"[yellow]→ faça /login nesta janela e depois saia (/exit).[/]\n"
    )
    engine_auth.login(inst, exec_replace=True)


@app.command("dry-run")
def dry_run_cmd(
    name: str,
    prompt: Optional[str] = typer.Option(None, "--prompt"),
    deliverable: Optional[str] = typer.Option(None, "--deliverable"),
    mode: Optional[str] = typer.Option(None, "--mode"),
    request_type: Optional[str] = typer.Option(None, "--request-type"),
    repos: Optional[str] = typer.Option(
        None, "--repos", help="comma list of repo names to use (omit=all, ''=none)"
    ),
):
    """Render prompt/argv/env/MCP without executing anything (§32)."""
    from . import runner

    inst = _load(name)
    job = _build_job(inst, prompt, deliverable, mode, None, request_type, repos=_parse_repo_sel(repos))
    out = runner.dry_run(job)
    if out.get("repos") is not None:
        rl = out["repos"]
        summary = ", ".join(f"{r['name']} ({r['branch_base']})" for r in rl) if rl else "none"
        console.print(Panel(f"{summary}\nlayout: {out['workspace_layout']}", title="repos", border_style="magenta"))
    console.print(Panel(out["prompt"], title="prompt", border_style="cyan"))
    if out["context_file"]["body"]:
        console.print(Panel(out["context_file"]["body"], title=out["context_file"]["name"]))
    console.print(Panel(" ".join(out["argv"]), title="engine argv", border_style="green"))
    t = Table("env", "value (masked)")
    for k, v in out["env"].items():
        t.add_row(k, v)
    console.print(t)
    console.print_json(json.dumps({"guardrails": out["guardrails"], "mcp": out["mcp"],
                                   "auth_env_required": out["auth_env_required"]}))


@app.command("send")
def send_cmd(
    name: str,
    prompt: Optional[str] = typer.Option(None, "--prompt"),
    url: Optional[str] = typer.Option(None, "--url"),
    token: Optional[str] = typer.Option(None, "--token"),
    thread_key: Optional[str] = typer.Option(None, "--thread-key"),
    deliverable: Optional[str] = typer.Option(None, "--deliverable"),
    repos: Optional[str] = typer.Option(
        None, "--repos", help="comma list of repo names to use (omit=all, ''=none)"
    ),
    wait: bool = typer.Option(False, "--wait"),
    replay: Optional[str] = typer.Option(None, "--replay", help="resend a past job's request"),
):
    """POST a real request to the running server (§32)."""
    import httpx

    cfg = config_mod.load_config()
    base = (url or cfg.public_base_url).rstrip("/")
    if replay:
        job = store.get_job(replay)
        if not job:
            _err(f"job {replay} not found")
        payload = job.request
    else:
        payload = {"prompt": prompt or ""}
        if thread_key:
            payload["thread_key"] = thread_key
        if deliverable:
            payload["deliverable"] = deliverable
        sel = _parse_repo_sel(repos)
        if sel is not None:
            payload["repos"] = sel
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    target = f"{base}/hook/{name}" + ("?wait=true" if wait else "")
    try:
        r = httpx.post(target, json=payload, headers=headers, timeout=320 if wait else 30)
    except Exception as exc:  # noqa: BLE001
        _err(f"request failed: {exc}")
    console.print(f"[bold]{r.status_code}[/]")
    console.print_json(r.text)


# --- jobs / sessions / logs / usage / audit --------------------------------


@jobs_app.command("list")
def jobs_list(
    instance: Optional[str] = typer.Option(None, "--instance"),
    status: Optional[str] = typer.Option(None, "--status"),
    limit: int = typer.Option(20, "--limit"),
):
    table = Table("job", "instance", "status", "deliverable", "cost", "created")
    for job in store.list_jobs(instance, status, limit):
        table.add_row(
            job.id, job.instance, job.status.value, job.deliverable.value,
            f"${job.usage.cost_usd:.4f}" if job.usage.cost_usd else "-",
            time.strftime("%m-%d %H:%M", time.localtime(job.created_at)),
        )
    console.print(table)


@jobs_app.command("show")
def jobs_show(job_id: Optional[str] = typer.Argument(None)):
    job_id = job_id or tui.pick_job()
    job = store.get_job(job_id)
    if not job:
        _err("job not found")
    _print_job_result(job)


@sessions_app.command("list")
def sessions_list(instance: Optional[str] = typer.Option(None, "--instance")):
    table = Table("session", "instance", "thread_key", "status", "jobs")
    for s in store.list_sessions(instance):
        table.add_row(s.id, s.instance, s.thread_key, s.status.value, str(s.job_count))
    console.print(table)


@app.command("logs")
def logs_cmd(
    job_id: Optional[str] = typer.Argument(None),
    follow: bool = typer.Option(False, "-f", "--follow"),
):
    job_id = job_id or tui.pick_job()
    job = store.get_job(job_id)
    if not job:
        _err("job not found")
    path = paths.job_log(job.instance, job_id)
    if not path.exists():
        console.print("[dim](no logs yet)[/]")
        return
    if not follow:
        console.print(path.read_text())
        return
    with path.open() as fh:
        console.print(fh.read(), end="")
        while True:
            line = fh.readline()
            if line:
                console.print(line, end="")
            else:
                j = store.get_job(job_id)
                if j and j.status.terminal:
                    break
                time.sleep(0.4)


@app.command("usage")
def usage_cmd(
    instance: Optional[str] = typer.Option(None, "--instance"),
    requester: Optional[str] = typer.Option(None, "--requester"),
    since_days: Optional[int] = typer.Option(None, "--since-days"),
):
    since = time.time() - since_days * 86400 if since_days else None
    summ = store.usage_summary(instance, requester, since)
    console.print(Panel(f"jobs: [bold]{summ['jobs']}[/]\ncost: [bold]${summ['cost_usd']}[/]",
                        title="usage", border_style="cyan"))


@app.command("audit")
def audit_cmd(
    instance: Optional[str] = typer.Option(None, "--instance"),
    requester: Optional[str] = typer.Option(None, "--requester"),
    limit: int = typer.Option(50, "--limit"),
    export: Optional[str] = typer.Option(None, "--export", help="csv|json"),
):
    rows = store.audit_rows(instance, requester, limit)
    if export == "json":
        console.print_json(json.dumps(rows, default=str))
        return
    if export == "csv":
        import csv
        import io

        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        console.print(buf.getvalue())
        return
    table = Table("job", "instance", "requester", "deliverable", "status", "cost")
    for r in rows:
        table.add_row(
            r["job_id"], r["instance"], r.get("requester") or "-", r.get("deliverable") or "-",
            r["status"], f"${r['cost_usd']:.4f}" if r.get("cost_usd") else "-",
        )
    console.print(table)


# --- helpers ----------------------------------------------------------------


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context):
    if ctx.invoked_subcommand is None:
        tui.main_menu()


def _load(name: str) -> Instance:
    try:
        return instances.load(name)
    except Exception as exc:  # noqa: BLE001
        _err(str(exc))


def _build_job(inst, prompt, deliverable, mode, thread_key, request_type=None, repos=None) -> Job:
    request = {"prompt": prompt or ""} if prompt else {}
    if request_type:
        request["request_type"] = request_type
    if thread_key:
        request["thread_key"] = thread_key
    if repos is not None:
        request["repos"] = repos
    sess = store.find_or_create_session(inst.name, thread_key) if thread_key else None
    return Job(
        instance=inst.name,
        deliverable=Deliverable(deliverable or inst.deliverable),
        mode=Mode(mode or inst.default_mode),
        prompt=prompt or "",
        request=request,
        thread_key=thread_key,
        session_id=sess.id if sess else None,
    )


def _print_job_result(job: Job) -> None:
    color = "green" if job.status.value == "success" else "yellow"
    body = (
        f"status: [{color}]{job.status.value}[/]\n"
        f"deliverable: {job.deliverable.value}   mode: {job.mode.value}\n"
        f"cost: {f'${job.usage.cost_usd:.4f}' if job.usage.cost_usd else 'unknown'}   "
        f"attempts: {job.attempts}\n"
    )
    if job.error_class:
        body += f"error: [red]{job.error_class}[/] {job.error_message}\n"
    if job.pr_url:
        body += f"PR: {job.pr_url}\n"
    console.print(Panel(body.strip(), title=f"job {job.id}", border_style=color))
    if job.result and job.result.text:
        console.print(Panel(job.result.text[:4000], title="result"))


if __name__ == "__main__":
    app()
