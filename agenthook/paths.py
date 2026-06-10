"""Filesystem layout for agenthook state (DESIGN.md §3).

All runtime state lives under a single root, ``~/.agenthook`` by default, which
can be overridden with the ``AGENTHOOK_HOME`` environment variable (useful for
tests and for running several isolated instances on one host).
"""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """Return the agenthook state root, creating it if needed."""
    root = os.environ.get("AGENTHOOK_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".agenthook"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return home() / "config.yaml"


def jobs_db() -> Path:
    return home() / "jobs.db"


def instances_dir() -> Path:
    d = home() / "instances"
    d.mkdir(parents=True, exist_ok=True)
    return d


def instance_dir(name: str) -> Path:
    return instances_dir() / name


def repos_dir() -> Path:
    d = home() / "repos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def work_dir() -> Path:
    d = home() / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    d = home() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(instance: str) -> Path:
    d = home() / "logs" / instance
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_log(instance: str, job_id: str) -> Path:
    return logs_dir(instance) / f"{job_id}.log"
