"""Background webhook-server daemon (start/stop/status without systemd).

The server is spawned as a detached process (its own session, stdin closed,
stdout/stderr appended to ``~/.agenthook/logs/server.log``) and tracked by a
pidfile at ``~/.agenthook/server.pid``. This gives the TUI and CLI a portable
start/stop story; ``agenthook install-service`` remains the supervised
(systemd) alternative for production.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import paths


def pid_file() -> Path:
    return paths.home() / "server.pid"


def log_file() -> Path:
    d = paths.home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "server.log"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Guard against PID reuse: only accept processes that look like ours.
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        return b"agenthook" in cmdline or b"uvicorn" in cmdline
    except OSError:
        return True  # /proc unavailable — trust the signal check


def running_pid() -> int | None:
    """Return the daemon's PID, or None. Stale pidfiles are removed."""
    p = pid_file()
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None
    if _alive(pid):
        return pid
    p.unlink(missing_ok=True)
    return None


def port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    target = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False


def start(host: str, port: int) -> int:
    """Spawn the server detached and return its PID.

    Raises RuntimeError if it is already running, or if the spawned process
    dies before the port starts accepting connections.
    """
    if (pid := running_pid()) is not None:
        raise RuntimeError(f"server already running (pid {pid})")
    if port_open(host, port):
        raise RuntimeError(f"port {port} is already in use by another process")

    from . import store

    store.init_db()

    exe = shutil.which("agenthook")
    if exe:
        cmd = [exe, "serve", "--host", host, "--port", str(port)]
    else:  # not on PATH (e.g. venv) — run uvicorn from this interpreter
        cmd = [
            sys.executable, "-m", "uvicorn", "agenthook.server:app",
            "--host", host, "--port", str(port), "--log-level", "info",
        ]

    log = log_file()
    with log.open("ab") as out:
        out.write(f"\n--- agenthook server start (host={host} port={port}) ---\n".encode())
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file().write_text(str(proc.pid))

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pid_file().unlink(missing_ok=True)
            tail = tail_log(15)
            raise RuntimeError(f"server exited at startup:\n{tail}")
        if port_open(host, port):
            return proc.pid
        time.sleep(0.1)
    return proc.pid  # spawned but slow to bind — leave it running


def stop(timeout: float = 5.0) -> bool:
    """SIGTERM the daemon (SIGKILL after *timeout*). False if not running."""
    pid = running_pid()
    if pid is None:
        return False
    try:
        os.killpg(pid, signal.SIGTERM)  # whole session (uvicorn + children)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pid_file().unlink(missing_ok=True)
            return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            pid_file().unlink(missing_ok=True)
            return True
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass
    pid_file().unlink(missing_ok=True)
    return True


def tail_log(lines: int = 50) -> str:
    log = log_file()
    if not log.exists():
        return ""
    content = log.read_text(errors="replace").splitlines()
    return "\n".join(content[-lines:])
