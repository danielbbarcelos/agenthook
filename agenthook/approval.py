"""Signed, single-use-ish, expiring approval tokens (DESIGN.md §19).

A token binds ``job_id`` + ``action`` + an expiry under an HMAC of the global
approval secret. "Single-use" is enforced at apply time by the job's state
machine (a job only leaves ``awaiting_approval`` once), so the token itself just
needs to be unforgeable and time-bounded.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def make_token(secret: str, job_id: str, action: str, ttl: int) -> str:
    exp = int(time.time()) + int(ttl)
    sig = _sig(secret, job_id, action, exp)
    return f"{exp}.{sig}"


def verify_token(secret: str, job_id: str, action: str, token: str) -> bool:
    try:
        exp_str, sig = token.split(".", 1)
        exp = int(exp_str)
    except (ValueError, AttributeError):
        return False
    if exp < time.time():
        return False
    expected = _sig(secret, job_id, action, exp)
    return hmac.compare_digest(sig, expected)


def _sig(secret: str, job_id: str, action: str, exp: int) -> str:
    msg = f"{job_id}:{action}:{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
