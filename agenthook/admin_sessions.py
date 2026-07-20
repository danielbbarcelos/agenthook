"""Native-UI login sessions — server-side, SQLite. Cookie -> session -> user.

Sliding idle timeout: each validated access pushes the expiry forward. Every
session carries a CSRF token the SPA echoes in a header on unsafe requests —
cookies are auto-sent by the browser, the header is not, so requiring it blocks
cross-site request forgery. Sessions are revocable (logout, or delete_for_user
after a password reset). Used only by the human plane; the machine plane
(Workspace) authenticates with the bearer JWT/token in ``admin_auth.py``.
"""

from __future__ import annotations

import secrets as _secrets
import time
from dataclasses import dataclass

from .store import _conn

COOKIE_NAME = "agenthook_session"
CSRF_HEADER = "x-agenthook-csrf"


@dataclass
class Session:
    id: str
    username: str
    csrf: str
    created_at: float
    expires_at: float


def create(username: str, *, idle_seconds: int) -> Session:
    now = time.time()
    s = Session(
        id=_secrets.token_urlsafe(32),
        username=username,
        csrf=_secrets.token_urlsafe(24),
        created_at=now,
        expires_at=now + idle_seconds,
    )
    with _conn() as c:
        c.execute(
            "INSERT INTO admin_sessions(id, username, csrf, created_at, expires_at) VALUES(?,?,?,?,?)",
            (s.id, s.username, s.csrf, s.created_at, s.expires_at),
        )
    return s


def get(session_id: str, *, idle_seconds: int | None = None, now: float | None = None) -> Session | None:
    """Return the session if it exists and hasn't expired (expired ones are
    deleted). When ``idle_seconds`` is given, slide the expiry forward."""
    now = time.time() if now is None else now
    with _conn() as c:
        row = c.execute(
            "SELECT id, username, csrf, created_at, expires_at FROM admin_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        s = Session(*row)
        if s.expires_at <= now:
            c.execute("DELETE FROM admin_sessions WHERE id=?", (session_id,))
            return None
        if idle_seconds is not None:
            s.expires_at = now + idle_seconds
            c.execute("UPDATE admin_sessions SET expires_at=? WHERE id=?", (s.expires_at, s.id))
    return s


def delete(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM admin_sessions WHERE id=?", (session_id,))


def delete_for_user(username: str) -> None:
    """Revoke every session of a user (e.g. after a password reset)."""
    with _conn() as c:
        c.execute("DELETE FROM admin_sessions WHERE username=?", (username,))


def reap(now: float | None = None) -> int:
    now = time.time() if now is None else now
    with _conn() as c:
        return int(c.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (now,)).rowcount)
