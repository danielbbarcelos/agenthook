"""Channel registry (DESIGN.md §19, §26)."""

from __future__ import annotations

from .base import ApprovalChannel
from .slack import SlackChannel

_BUILTINS: dict[str, type[ApprovalChannel]] = {SlackChannel.name: SlackChannel}


def registry() -> dict[str, type[ApprovalChannel]]:
    from ..plugins import load_channels

    merged = dict(_BUILTINS)
    merged.update(load_channels())
    return merged


def get_channel(name: str) -> ApprovalChannel:
    cls = registry().get(name)
    if cls is None:
        raise ValueError(f"unknown channel {name!r}")
    return cls()


__all__ = ["ApprovalChannel", "get_channel", "registry"]
