"""Engine registry (DESIGN.md §16).

Built-in engines are always available; plugin engines registered via the
``agenthook.engines`` entry point are merged on top.
"""

from __future__ import annotations

from .aider import AiderEngine
from .base import Capabilities, Engine, RunSpec
from .claude import ClaudeEngine
from .codex import CodexEngine
from .gemini import GeminiEngine

_BUILTINS: dict[str, type[Engine]] = {
    ClaudeEngine.name: ClaudeEngine,
    CodexEngine.name: CodexEngine,
    GeminiEngine.name: GeminiEngine,
    AiderEngine.name: AiderEngine,
}


def registry() -> dict[str, type[Engine]]:
    from ..plugins import load_engines

    merged = dict(_BUILTINS)
    merged.update(load_engines())  # plugins override/extend builtins
    return merged


def get_engine(name: str) -> Engine:
    cls = registry().get(name)
    if cls is None:
        raise ValueError(f"unknown engine {name!r}; available: {', '.join(sorted(registry()))}")
    return cls()


def available() -> list[str]:
    return sorted(registry())


__all__ = [
    "Engine",
    "RunSpec",
    "Capabilities",
    "get_engine",
    "registry",
    "available",
]
