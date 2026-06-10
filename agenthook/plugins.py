"""Plugin loading via entry points (DESIGN.md §26).

Extension points: ``agenthook.engines``, ``agenthook.channels``,
``agenthook.secrets_backends`` and ``agenthook.hooks``. Built-in implementations
are always available directly (so the tool works when run from source); entry
points are *additive*, letting third-party pip packages register their own
adapters without forking.
"""

from __future__ import annotations

from importlib import metadata
from typing import Any, Callable


def _entry_points(group: str):
    try:
        eps = metadata.entry_points()
    except Exception:  # pragma: no cover - defensive
        return []
    # Python 3.10+ supports selection by group; older dict-style as fallback.
    select = getattr(eps, "select", None)
    if callable(select):
        return list(eps.select(group=group))
    return list(eps.get(group, []))  # type: ignore[union-attr]


def _load_group(group: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ep in _entry_points(group):
        try:
            out[ep.name] = ep.load()
        except Exception:  # pragma: no cover - a broken plugin must not crash us
            continue
    return out


def load_engines() -> dict[str, Any]:
    return _load_group("agenthook.engines")


def load_channels() -> dict[str, Any]:
    return _load_group("agenthook.channels")


def load_secrets_backend(name: str):
    return _load_group("agenthook.secrets_backends").get(name)


def load_hooks() -> dict[str, Callable]:
    """Lifecycle hooks: pre_run / post_run / on_result / on_error (DESIGN.md §26)."""
    return _load_group("agenthook.hooks")
