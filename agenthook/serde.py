"""(De)serialization helpers for the domain dataclasses (Job, Session).

Kept separate so both the SQLite store and the HTTP/CLI layers share one
canonical JSON representation, with enums rendered as their string values.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .models import Deliverable, Job, JobStatus, Mode, Result, Session, SessionStatus, Usage


def job_to_dict(job: Job) -> dict[str, Any]:
    d = asdict(job)
    d["deliverable"] = job.deliverable.value
    d["mode"] = job.mode.value
    d["status"] = job.status.value
    if job.result is not None:
        d["result"] = job.result.to_dict()
    d["usage"] = job.usage.to_dict()
    return d


def job_from_dict(d: dict[str, Any]) -> Job:
    d = dict(d)
    d["deliverable"] = Deliverable(d.get("deliverable", "analysis"))
    d["mode"] = Mode(d.get("mode", "default"))
    d["status"] = JobStatus(d.get("status", "queued"))
    usage = d.get("usage") or {}
    d["usage"] = Usage(**usage) if isinstance(usage, dict) else Usage()
    res = d.get("result")
    if isinstance(res, dict):
        ru = res.get("usage") or {}
        d["result"] = Result(
            text=res.get("text", ""),
            files_changed=res.get("files_changed", []),
            usage=Usage(**ru) if isinstance(ru, dict) else Usage(),
            session_id=res.get("session_id"),
            is_plan=res.get("is_plan", False),
            raw=res.get("raw", ""),
        )
    else:
        d["result"] = None
    known = set(Job.__dataclass_fields__)  # type: ignore[attr-defined]
    return Job(**{k: v for k, v in d.items() if k in known})


def job_to_json(job: Job) -> str:
    return json.dumps(job_to_dict(job))


def job_from_json(s: str) -> Job:
    return job_from_dict(json.loads(s))


def session_to_dict(s: Session) -> dict[str, Any]:
    d = asdict(s)
    d["status"] = s.status.value
    return d


def session_from_dict(d: dict[str, Any]) -> Session:
    d = dict(d)
    d["status"] = SessionStatus(d.get("status", "open"))
    known = set(Session.__dataclass_fields__)  # type: ignore[attr-defined]
    return Session(**{k: v for k, v in d.items() if k in known})
