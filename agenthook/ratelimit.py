"""In-process webhook rate limiting (token bucket).

State is a module-level dict keyed by an opaque string (``ip`` for the pre-auth
flood guard, ``instance:ip`` for the per-instance budget). This is correct
*only* because the server runs single-process (``Config.workers == 1``, enforced
by ``agenthook serve``): every request shares one address space, so one dict is
the whole picture.

⚠️ If ``workers`` is ever raised above 1, this must move to a shared store
(SQLite/Redis) — a per-process bucket would then under-count by a factor of N
and let bursts through. Guard that change; don't just bump ``workers``.

The bucket refills continuously at ``rate`` tokens/second up to ``burst``; a
request costs one token. ``check`` returns ``(allowed, retry_after_seconds)``.
Time is injected so tests are deterministic and don't sleep.
"""

from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass

_lock = threading.Lock()
# key -> (tokens, last_refill_epoch)
_buckets: dict[str, tuple[float, float]] = {}
_last_prune = 0.0
_PRUNE_EVERY_S = 300.0


@dataclass(frozen=True)
class Limit:
    rpm: float  # sustained requests per minute
    burst: float  # bucket capacity (max instantaneous burst)

    @property
    def rate_per_s(self) -> float:
        return self.rpm / 60.0


def _prune(now: float) -> None:
    """Drop full, idle buckets so memory stays bounded under key churn (many
    distinct IPs). A full bucket carries no state worth keeping."""
    global _last_prune
    if now - _last_prune < _PRUNE_EVERY_S:
        return
    _last_prune = now
    stale = [k for k, (_, last) in _buckets.items() if now - last > _PRUNE_EVERY_S]
    for k in stale:
        del _buckets[k]


def check(key: str, limit: Limit, *, now: float | None = None) -> tuple[bool, int]:
    """Consume one token for ``key``. Returns ``(allowed, retry_after)``.

    ``retry_after`` is a whole number of seconds until the next token, and is 0
    when the request is allowed."""
    if limit.rpm <= 0:  # a non-positive limit disables the check
        return True, 0
    n = _time.time() if now is None else now
    rate = limit.rate_per_s
    with _lock:
        _prune(n)
        tokens, last = _buckets.get(key, (limit.burst, n))
        tokens = min(limit.burst, tokens + (n - last) * rate)
        if tokens >= 1.0:
            _buckets[key] = (tokens - 1.0, n)
            return True, 0
        _buckets[key] = (tokens, n)
        retry = int((1.0 - tokens) / rate) + 1 if rate > 0 else 1
        return False, retry


def reset() -> None:
    """Clear all buckets — for tests."""
    with _lock:
        _buckets.clear()
        global _last_prune
        _last_prune = 0.0
