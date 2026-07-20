"""Headless subscription login orchestration — "URL out / code in".

Drives the engine's ``setup_token_argv`` flow (for Claude: ``claude setup-token``)
so an operator can connect a subscription entirely from the UI/API instead of a
terminal. The command is interactive: it prints an OAuth authorize URL, waits for
the user to paste back the code their browser shows, then emits a long-lived token
on stdout. We capture that token; the caller stores it as the instance secret named
by ``Engine.token_env_name`` (Claude: ``CLAUDE_CODE_OAUTH_TOKEN``), which the runner
injects at job time.

The subprocess is held open between the two HTTP calls (``start`` → ``submit_code``)
in an in-memory registry keyed by an opaque session id, with a TTL so abandoned
logins can't leak processes. A PTY is allocated because the command only behaves
interactively on a real terminal; the host's ``~/.claude`` is never touched
(``CLAUDE_CONFIG_DIR`` points at an isolated dir).
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
import uuid
from dataclasses import dataclass, field

from . import paths
from .config import load_config
from .engines import get_engine
from .instances import Instance

_AUTH_MOUNT = "/agenthook-auth"
_SESSION_TTL_S = 300.0  # abandoned logins are reaped after 5 min
_URL_TIMEOUT_S = 45.0  # wait for the authorize URL to appear
_CODE_TIMEOUT_S = 60.0  # wait for the token after the code is submitted
_SUBMIT_SETTLE_S = 0.4  # gap so the pasted code and the Enter (CR) read as distinct events

# The login runs as a full-screen TUI: a very wide PTY keeps the URL/token on a
# single logical line (the default 80 cols wraps them), and we strip ANSI before
# matching. URL = the OAuth authorize link; token = the long-lived artifact.
_PTY_COLS = 400
_PTY_ROWS = 50
_ANSI_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[\[\]][0-9;?>=]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
_URL_RE = re.compile(r"https://\S*(?:oauth|authorize|claude\.com/cai|claude\.ai|console\.anthropic)\S*")
_TOKEN_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")


def _clean(buf: str) -> str:
    """Strip ANSI escapes so URLs/tokens can be matched as plain text."""
    return _ANSI_RE.sub("", buf)


class LoginError(RuntimeError):
    """Login flow failed (unsupported engine, timeout, or no token)."""


@dataclass
class _Session:
    proc: subprocess.Popen
    master_fd: int
    instance: str
    buf: str = ""
    created: float = field(default_factory=time.monotonic)


_SESSIONS: dict[str, _Session] = {}


def _reap_expired() -> None:
    now = time.monotonic()
    for sid in [s for s, sess in _SESSIONS.items() if now - sess.created > _SESSION_TTL_S]:
        _kill(_SESSIONS.pop(sid, None))


def _kill(sess: _Session | None) -> None:
    if not sess:
        return
    try:
        if sess.proc.poll() is None:
            sess.proc.send_signal(signal.SIGTERM)
            try:
                sess.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                sess.proc.kill()
    except Exception:
        pass
    try:
        os.close(sess.master_fd)
    except OSError:
        pass


def _drain(master_fd: int, deadline: float, *, until: re.Pattern, proc: subprocess.Popen,
           buf: str) -> tuple[str, str | None]:
    """Read from ``master_fd`` until ``until`` matches, the process exits, or the
    deadline passes. Returns the accumulated buffer and the first match (or None)."""
    while time.monotonic() < deadline:
        m = until.search(_clean(buf))
        if m:
            return buf, m.group(0)
        ready, _, _ = select.select([master_fd], [], [], 0.5)
        if ready:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                chunk = b""
            if chunk:
                buf += chunk.decode("utf-8", "replace")
                continue
        if proc.poll() is not None:
            # Process gone: one last scan of whatever we have.
            m = until.search(_clean(buf))
            return buf, (m.group(0) if m else None)
    return buf, None


def _build_cmd(inst: Instance) -> tuple[list[str], dict[str, str]]:
    """argv + env for the engine's setup-token flow, isolated from the host login."""
    engine = get_engine(inst.engine)
    argv = engine.setup_token_argv()
    if not argv:
        raise LoginError(f"engine {engine.name!r} has no headless subscription login.")
    cfg = load_config()
    auth_dir = paths.auth_dir(inst.name) / engine.name
    auth_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)

    if cfg.use_docker:
        # Allocate the TTY on our side (the PTY slave); -i keeps stdin open. No
        # auth bind mount: the token is printed, not written to a credential file.
        from .shell import _user_args

        # -it: claude only runs the interactive login when docker allocates a TTY
        # inside the container (our PTY slave alone isn't seen as a tty there).
        cmd = ["docker", "run", "--rm", "-it", "--hostname", inst.name, *_user_args(), "-e", "HOME=/tmp"]
        for k, v in engine.auth_config_env(inst, _AUTH_MOUNT).items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [cfg.docker_image, *argv]
        return cmd, env

    # Host fallback: relocate the engine's config dir so ~/.claude is never used.
    env.update(engine.auth_config_env(inst, auth_dir))
    return argv, env


def start(inst: Instance) -> tuple[str, str]:
    """Spawn the setup-token flow and return ``(session_id, authorize_url)``."""
    _reap_expired()
    # One pending login per instance: replace any stale session.
    for sid, sess in list(_SESSIONS.items()):
        if sess.instance == inst.name:
            _kill(_SESSIONS.pop(sid, None))

    cmd, env = _build_cmd(inst)
    master_fd, slave_fd = pty.openpty()
    # Wide window so the authorize URL / token stay on one line (no 80-col wrap).
    try:
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", _PTY_ROWS, _PTY_COLS, 0, 0))
    except OSError:
        pass
    try:
        proc = subprocess.Popen(
            cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, env=env, close_fds=True
        )
    except FileNotFoundError as exc:
        os.close(master_fd)
        os.close(slave_fd)
        raise LoginError(f"could not start login: {exc}") from exc
    os.close(slave_fd)  # parent keeps only the master end

    buf, url = _drain(master_fd, time.monotonic() + _URL_TIMEOUT_S, until=_URL_RE, proc=proc, buf="")
    if not url:
        sess = _Session(proc=proc, master_fd=master_fd, instance=inst.name, buf=buf)
        _kill(sess)
        raise LoginError("timed out waiting for the authorize URL — is `claude` installed and a subscription plan active?")

    sid = uuid.uuid4().hex
    _SESSIONS[sid] = _Session(proc=proc, master_fd=master_fd, instance=inst.name, buf=buf)
    return sid, url


def submit_code(session_id: str, code: str) -> str:
    """Feed the pasted code to the held process and return the captured token."""
    _reap_expired()
    sess = _SESSIONS.get(session_id)
    if not sess:
        raise LoginError("login session not found or expired — start again.")
    try:
        # The setup-token TUI (Ink, raw mode) only submits on a carriage return
        # that arrives as its OWN input event. Two failure modes to avoid, both
        # verified against `claude setup-token`: a line feed ("\n") is never read
        # as Enter, and a CR glued onto the pasted code in one write is swallowed
        # as paste text — either way the code sits unsubmitted in the box and the
        # flow times out. So: write the code, let it register, then send a bare CR
        # as a separate write.
        os.write(sess.master_fd, code.strip().encode())
        time.sleep(_SUBMIT_SETTLE_S)
        os.write(sess.master_fd, b"\r")
    except OSError as exc:
        _kill(_SESSIONS.pop(session_id, None))
        raise LoginError(f"login process is gone: {exc}") from exc

    buf, token = _drain(
        sess.master_fd, time.monotonic() + _CODE_TIMEOUT_S, until=_TOKEN_RE, proc=sess.proc, buf=sess.buf
    )
    _kill(_SESSIONS.pop(session_id, None))
    if not token:
        raise LoginError(f"no token returned — the code may be wrong or expired. tail: {_mask(buf)}")
    return token


def cancel(session_id: str) -> None:
    _kill(_SESSIONS.pop(session_id, None))


def _mask(text: str) -> str:
    """Redact any token-shaped substrings and keep only a short tail for diagnostics."""
    redacted = _TOKEN_RE.sub("sk-ant-***", _clean(text))
    tail = [s.strip() for s in redacted.strip().splitlines() if s.strip()][-3:]
    return " / ".join(tail)[:200]
