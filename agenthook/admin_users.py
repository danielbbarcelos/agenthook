"""Native-UI admin accounts — the human auth plane (password + optional TOTP).

Single admin user is the v1 model (multi-user/RBAC is future). Everything here is
**stdlib only**:

- passwords: ``hashlib.scrypt`` (memory-hard), stored as a versioned string
  ``scrypt$n$r$p$salt_b64$hash_b64`` so the algorithm can be swapped later;
- TOTP: RFC 6238 (HMAC-SHA1), for the optional second factor.

This plane is used **only** by the native ``/ui`` login. The machine plane
(Workspace/API) authenticates via ``admin_auth.py`` (short-lived JWT / token) and
never touches this. Storage is the shared SQLite db (``store._conn``); the
``admin_users`` table is created in ``store._migrate``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass

from .store import _conn

# --- password hashing (stdlib scrypt, memory-hard) --------------------------

_N, _R, _P = 2**15, 8, 1  # ~32 MiB work factor (OWASP-ish); tune _N to raise cost
_DKLEN = 32


def _maxmem(n: int, r: int) -> int:
    # scrypt needs ~128*n*r bytes; give headroom so CPython doesn't refuse.
    return 128 * n * r * 2


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN, maxmem=_maxmem(_N, _R))
    return "$".join(
        ["scrypt", str(_N), str(_R), str(_P), base64.b64encode(salt).decode(), base64.b64encode(dk).decode()]
    )


def verify_password(pw: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(
            pw.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected), maxmem=_maxmem(int(n), int(r))
        )
        return hmac.compare_digest(dk, expected)
    except Exception:  # noqa: BLE001 - any parse/compute failure is a non-match
        return False


# --- TOTP (RFC 6238, stdlib) ------------------------------------------------


def generate_totp_secret() -> str:
    """A fresh base32 secret to hand to an authenticator app."""
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o : o + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code).zfill(digits)


def verify_totp(secret_b32: str, code: str, *, now: float | None = None, window: int = 1, step: int = 30) -> bool:
    """Validate a TOTP code, tolerating +/- ``window`` steps of clock skew."""
    now = time.time() if now is None else now
    counter = int(now // step)
    code = str(code).strip()
    for w in range(-window, window + 1):
        if hmac.compare_digest(_totp(secret_b32, counter + w), code):
            return True
    return False


# --- user store -------------------------------------------------------------


_COLS = "username, pw_hash, totp_secret, created_at, email"


@dataclass
class AdminUser:
    username: str
    pw_hash: str
    totp_secret: str | None
    created_at: float
    email: str | None = None

    @property
    def totp_enabled(self) -> bool:
        return bool(self.totp_secret)


def create_user(username: str, password: str, email: str | None = None) -> None:
    with _conn() as c:
        if c.execute("SELECT 1 FROM admin_users WHERE username=?", (username,)).fetchone():
            raise ValueError(f"admin user {username!r} already exists")
        c.execute(
            "INSERT INTO admin_users(username, pw_hash, totp_secret, created_at, email) VALUES(?,?,?,?,?)",
            (username, hash_password(password), None, time.time(), email),
        )


def get_user(username: str) -> AdminUser | None:
    with _conn() as c:
        row = c.execute(f"SELECT {_COLS} FROM admin_users WHERE username=?", (username,)).fetchone()
    return AdminUser(*row) if row else None


def set_email(username: str, email: str | None) -> None:
    with _conn() as c:
        cur = c.execute("UPDATE admin_users SET email=? WHERE username=?", (email, username))
        if cur.rowcount == 0:
            raise ValueError(f"admin user {username!r} not found")


def set_password(username: str, password: str) -> None:
    with _conn() as c:
        cur = c.execute("UPDATE admin_users SET pw_hash=? WHERE username=?", (hash_password(password), username))
        if cur.rowcount == 0:
            raise ValueError(f"admin user {username!r} not found")


def set_totp_secret(username: str, secret: str | None) -> None:
    with _conn() as c:
        cur = c.execute("UPDATE admin_users SET totp_secret=? WHERE username=?", (secret, username))
        if cur.rowcount == 0:
            raise ValueError(f"admin user {username!r} not found")


def delete_user(username: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM admin_users WHERE username=?", (username,))


def list_users() -> list[AdminUser]:
    with _conn() as c:
        rows = c.execute(f"SELECT {_COLS} FROM admin_users ORDER BY username").fetchall()
    return [AdminUser(*r) for r in rows]


# --- password-reset tokens (email recovery) ---------------------------------


def create_reset_token(username: str, *, ttl_seconds: int = 900) -> str:
    """Mint a single-use password-reset token for ``username`` (default 15 min)."""
    import secrets as _secrets

    token = _secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute(
            "INSERT INTO admin_reset_tokens(token, username, expires_at) VALUES(?,?,?)",
            (token, username, time.time() + ttl_seconds),
        )
    return token


def consume_reset_token(token: str, *, now: float | None = None) -> str | None:
    """Return the username for a valid token and delete it (single-use); None if
    unknown or expired."""
    now = time.time() if now is None else now
    with _conn() as c:
        row = c.execute("SELECT username, expires_at FROM admin_reset_tokens WHERE token=?", (token,)).fetchone()
        if row is None:
            return None
        c.execute("DELETE FROM admin_reset_tokens WHERE token=?", (token,))
        username, expires_at = row
        return username if expires_at > now else None


def count_users() -> int:
    with _conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0])


def authenticate(username: str, password: str, totp_code: str | None = None) -> bool:
    """Full human-plane check: password, then TOTP if the user enrolled one."""
    u = get_user(username)
    if u is None or not verify_password(password, u.pw_hash):
        return False
    if u.totp_secret:
        return bool(totp_code) and verify_totp(u.totp_secret, totp_code)
    return True
