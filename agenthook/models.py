"""Core data models (DESIGN.md §2, §20, §29).

Plain dataclasses are used for the domain model so they are trivially
serializable to YAML/JSON and independent of any web framework. The FastAPI
layer (``server.py``) defines its own pydantic request models on top of these.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


# --- Enums ------------------------------------------------------------------


class Mode(str, enum.Enum):
    """How autonomous the agent is (DESIGN.md §11)."""

    AUTO = "auto"  # applies changes by itself
    PLAN = "plan"  # produces a plan, no changes
    DEFAULT = "default"  # asks for permission (interactive)


class Deliverable(str, enum.Enum):
    """What comes out of a job (DESIGN.md §20) — orthogonal to Mode."""

    ANALYSIS = "analysis"  # read-only, returns text/JSON
    ACTION = "action"  # external side effects via tools/MCP, no repo mutation
    PATCH = "patch"  # local edits -> .diff artifact, no push
    COMMIT = "commit"  # edits -> push branch
    PR = "pr"  # edits -> push + open PR

    @property
    def mutates_code(self) -> bool:
        return self in {Deliverable.PATCH, Deliverable.COMMIT, Deliverable.PR}

    @property
    def read_only(self) -> bool:
        return self in {Deliverable.ANALYSIS, Deliverable.ACTION}


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCESS = "success"
    FAILED_CHECKS = "failed-checks"
    BLOCKED = "blocked"
    ERROR = "error"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    REJECTED = "rejected"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in {
            JobStatus.SUCCESS,
            JobStatus.FAILED_CHECKS,
            JobStatus.BLOCKED,
            JobStatus.ERROR,
            JobStatus.TIMEOUT,
            JobStatus.INTERRUPTED,
            JobStatus.REJECTED,
            JobStatus.EXPIRED,
        }


class SessionStatus(str, enum.Enum):
    OPEN = "open"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSED = "closed"


# --- Value objects ----------------------------------------------------------


@dataclass
class Usage:
    """Normalized usage/cost record per job (DESIGN.md §24)."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    cost_usd: float | None = None  # None == unknown (never faked)
    num_turns: int | None = None
    model: str | None = None
    duration_s: float | None = None

    def add(self, other: "Usage") -> "Usage":
        """Accumulate another usage record (e.g. verify self-heal turns)."""

        def _s(a, b):
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return Usage(
            input_tokens=_s(self.input_tokens, other.input_tokens),
            output_tokens=_s(self.output_tokens, other.output_tokens),
            cache_read=_s(self.cache_read, other.cache_read),
            cache_write=_s(self.cache_write, other.cache_write),
            cost_usd=_s(self.cost_usd, other.cost_usd),
            num_turns=_s(self.num_turns, other.num_turns),
            model=self.model or other.model,
            duration_s=_s(self.duration_s, other.duration_s),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Result:
    """Normalized engine output (DESIGN.md §16)."""

    text: str = ""
    files_changed: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    session_id: str | None = None  # engine-side session id, for resume
    is_plan: bool = False
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["usage"] = self.usage.to_dict()
        # raw can be huge; callers decide whether to persist it
        return d


# --- Entities ---------------------------------------------------------------


def _job_id() -> str:
    return "j_" + uuid.uuid4().hex[:10]


def _session_id() -> str:
    return "s_" + uuid.uuid4().hex[:10]


@dataclass
class Job:
    instance: str
    prompt: str = ""
    deliverable: Deliverable = Deliverable.ANALYSIS
    mode: Mode = Mode.DEFAULT
    id: str = field(default_factory=_job_id)
    session_id: str | None = None
    thread_key: str | None = None
    status: JobStatus = JobStatus.QUEUED
    request: dict[str, Any] = field(default_factory=dict)
    result: Result | None = None
    error_class: str | None = None
    error_message: str | None = None
    usage: Usage = field(default_factory=Usage)
    container_id: str | None = None
    workdir: str | None = None
    attempts: int = 0
    idempotency_key: str | None = None
    pr_url: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    instance: str
    thread_key: str
    id: str = field(default_factory=_session_id)
    engine_session_id: str | None = None  # for resume
    status: SessionStatus = SessionStatus.OPEN
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    job_count: int = 0
    description: str = ""  # user note/description for the chat (§29)
