"""Durable state: jobs, sessions, audit, idempotency, queue (DESIGN.md §3, §24, §31).

SQLite is used for everything except instance config (which is YAML). The full
:class:`Job`/:class:`Session` objects are stored as JSON in a ``data`` column,
with hot fields denormalized into indexed columns so usage/audit queries stay
cheap.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from . import paths
from .instances import load as load_instance
from .models import Deliverable, Job, JobStatus, Session, SessionStatus
from .serde import (
    job_from_json,
    job_to_json,
    session_from_dict,
    session_to_dict,
)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    instance TEXT NOT NULL,
    session_id TEXT,
    thread_key TEXT,
    status TEXT NOT NULL,
    deliverable TEXT,
    mode TEXT,
    engine TEXT,
    requester TEXT,
    request_type TEXT,
    idempotency_key TEXT,
    cost_usd REAL,
    error_class TEXT,
    pr_url TEXT,
    attempts INTEGER DEFAULT 0,
    created_at REAL,
    started_at REAL,
    finished_at REAL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_instance ON jobs(instance);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_idem ON jobs(instance, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    instance TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    engine_session_id TEXT,
    status TEXT NOT NULL,
    created_at REAL,
    updated_at REAL,
    job_count INTEGER DEFAULT 0,
    description TEXT DEFAULT '',
    UNIQUE(instance, thread_key)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    instance TEXT,
    requester TEXT,
    request_type TEXT,
    deliverable TEXT,
    engine TEXT,
    status TEXT,
    error_class TEXT,
    cost_usd REAL,
    pr_url TEXT,
    prompt_hash TEXT,
    prompt_full TEXT,
    output_full TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_audit_instance ON audit(instance);
CREATE INDEX IF NOT EXISTS idx_audit_requester ON audit(requester);
"""


_initialized_paths: set[str] = set()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    db_path = paths.jobs_db()
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if str(db_path) not in _initialized_paths:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        _initialized_paths.add(str(db_path))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Lightweight additive migrations for already-created databases."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}  # r[1] = column name
    if "description" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


# --- Jobs -------------------------------------------------------------------


def _engine_of(instance: str) -> str | None:
    try:
        return load_instance(instance).engine
    except Exception:
        return None


def _job_columns(job: Job) -> dict[str, Any]:
    req = job.request or {}
    requester = (req.get("requester") or {}).get("name") if isinstance(req.get("requester"), dict) else None
    return {
        "id": job.id,
        "instance": job.instance,
        "session_id": job.session_id,
        "thread_key": job.thread_key,
        "status": job.status.value,
        "deliverable": job.deliverable.value,
        "mode": job.mode.value,
        "engine": _engine_of(job.instance),
        "requester": requester,
        "request_type": req.get("request_type"),
        "idempotency_key": job.idempotency_key,
        "cost_usd": job.usage.cost_usd,
        "error_class": job.error_class,
        "pr_url": job.pr_url,
        "attempts": job.attempts,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "data": job_to_json(job),
    }


def create_job(job: Job) -> None:
    cols = _job_columns(job)
    placeholders = ",".join("?" for _ in cols)
    with _lock, _conn() as conn:
        conn.execute(
            f"INSERT INTO jobs ({','.join(cols)}) VALUES ({placeholders})",
            list(cols.values()),
        )


def save_job(job: Job) -> None:
    cols = _job_columns(job)
    assignments = ",".join(f"{k}=?" for k in cols if k != "id")
    values = [v for k, v in cols.items() if k != "id"] + [job.id]
    with _lock, _conn() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id=?", values)


def get_job(job_id: str) -> Job | None:
    with _conn() as conn:
        row = conn.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
    return job_from_json(row["data"]) if row else None


def find_by_idempotency(instance: str, key: str) -> Job | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT data FROM jobs WHERE instance=? AND idempotency_key=?", (instance, key)
        ).fetchone()
    return job_from_json(row["data"]) if row else None


def list_jobs(
    instance: str | None = None, status: str | None = None, limit: int = 50
) -> list[Job]:
    q = "SELECT data FROM jobs"
    clauses, params = [], []
    if instance:
        clauses.append("instance=?")
        params.append(instance)
    if status:
        clauses.append("status=?")
        params.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [job_from_json(r["data"]) for r in rows]


def next_queued(instance: str | None = None) -> Job | None:
    q = "SELECT data FROM jobs WHERE status=?"
    params: list[Any] = [JobStatus.QUEUED.value]
    if instance:
        q += " AND instance=?"
        params.append(instance)
    q += " ORDER BY created_at ASC LIMIT 1"
    with _conn() as conn:
        row = conn.execute(q, params).fetchone()
    return job_from_json(row["data"]) if row else None


def running_count(instance: str) -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE instance=? AND status=?",
            (instance, JobStatus.RUNNING.value),
        ).fetchone()
    return row["c"]


def claim_job(job_id: str) -> bool:
    """Atomically move a job queued -> running. Returns True if this caller won."""
    with _lock, _conn() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status=? WHERE id=? AND status=?",
            (JobStatus.RUNNING.value, job_id, JobStatus.QUEUED.value),
        )
        return cur.rowcount == 1


def session_running(session_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE session_id=? AND status=?",
            (session_id, JobStatus.RUNNING.value),
        ).fetchone()
    return row["c"] > 0


def mutating_running(instance: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE instance=? AND status=? "
            "AND deliverable IN ('patch','commit','pr')",
            (instance, JobStatus.RUNNING.value),
        ).fetchone()
    return row["c"] > 0


def queued_jobs(limit: int = 100) -> list[Job]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT data FROM jobs WHERE status=? ORDER BY created_at ASC LIMIT ?",
            (JobStatus.QUEUED.value, limit),
        ).fetchall()
    return [job_from_json(r["data"]) for r in rows]


# --- Sessions ---------------------------------------------------------------


def find_or_create_session(instance: str, thread_key: str) -> Session:
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE instance=? AND thread_key=?", (instance, thread_key)
        ).fetchone()
        if row:
            return session_from_dict(dict(row))
        sess = Session(instance=instance, thread_key=thread_key, status=SessionStatus.OPEN)
        d = session_to_dict(sess)
        conn.execute(
            "INSERT INTO sessions (id,instance,thread_key,engine_session_id,status,created_at,updated_at,job_count,description)"
            " VALUES (:id,:instance,:thread_key,:engine_session_id,:status,:created_at,:updated_at,:job_count,:description)",
            d,
        )
        return sess


def save_session(sess: Session) -> None:
    sess.updated_at = time.time()
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE sessions SET engine_session_id=?,status=?,updated_at=?,job_count=?,description=? WHERE id=?",
            (sess.engine_session_id, sess.status.value, sess.updated_at,
             sess.job_count, sess.description, sess.id),
        )


def set_session_description(session_id: str, description: str) -> None:
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE sessions SET description=?,updated_at=? WHERE id=?",
            (description, time.time(), session_id),
        )


def delete_session(session_id: str) -> int:
    """Delete a chat: the session row, its jobs, and the persisted engine session
    volume. Returns the number of jobs removed."""
    import shutil

    with _lock, _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE session_id=?", (session_id,)
        ).fetchone()["c"]
        conn.execute("DELETE FROM jobs WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    vol = paths.sessions_dir() / session_id
    if vol.exists():
        shutil.rmtree(vol, ignore_errors=True)
    return n


def get_session(session_id: str) -> Session | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return session_from_dict(dict(row)) if row else None


def list_sessions(instance: str | None = None) -> list[Session]:
    q = "SELECT * FROM sessions"
    params: list[Any] = []
    if instance:
        q += " WHERE instance=?"
        params.append(instance)
    q += " ORDER BY updated_at DESC"
    with _conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [session_from_dict(dict(r)) for r in rows]


# --- Audit & usage ----------------------------------------------------------


def record_audit(job: Job, *, prompt_full: str | None = None, output_full: str | None = None) -> None:
    import hashlib

    cols = _job_columns(job)
    prompt_hash = hashlib.sha256((job.prompt or "").encode()).hexdigest()[:16]
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO audit (job_id,instance,requester,request_type,deliverable,engine,status,"
            "error_class,cost_usd,pr_url,prompt_hash,prompt_full,output_full,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.id,
                job.instance,
                cols["requester"],
                cols["request_type"],
                job.deliverable.value,
                cols["engine"],
                job.status.value,
                job.error_class,
                job.usage.cost_usd,
                job.pr_url,
                prompt_hash,
                prompt_full,
                output_full,
                time.time(),
            ),
        )


def usage_summary(
    instance: str | None = None, requester: str | None = None, since: float | None = None
) -> dict[str, Any]:
    q = "SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) cost FROM audit"
    clauses, params = [], []
    if instance:
        clauses.append("instance=?")
        params.append(instance)
    if requester:
        clauses.append("requester=?")
        params.append(requester)
    if since:
        clauses.append("created_at>=?")
        params.append(since)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    with _conn() as conn:
        row = conn.execute(q, params).fetchone()
    return {"jobs": row["n"], "cost_usd": round(row["cost"], 4)}


def audit_rows(
    instance: str | None = None, requester: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    q = "SELECT * FROM audit"
    clauses, params = [], []
    if instance:
        clauses.append("instance=?")
        params.append(instance)
    if requester:
        clauses.append("requester=?")
        params.append(requester)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


# --- Recovery on boot (DESIGN.md §31) ---------------------------------------


def recover_interrupted() -> dict[str, int]:
    """On startup, reconcile jobs left ``running`` by a crash/restart.

    Read-only deliverables (analysis/action) are safely re-queued; code-mutating
    ones become ``interrupted`` for inspection (never auto-replayed).
    """
    requeued = interrupted = 0
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, deliverable FROM jobs WHERE status=?", (JobStatus.RUNNING.value,)
        ).fetchall()
        for r in rows:
            deliverable = Deliverable(r["deliverable"]) if r["deliverable"] else Deliverable.ANALYSIS
            job = get_job(r["id"])
            if job is None:
                continue
            if deliverable.read_only:
                job.status = JobStatus.QUEUED
                requeued += 1
            else:
                job.status = JobStatus.INTERRUPTED
                interrupted += 1
            save_job(job)
    return {"requeued": requeued, "interrupted": interrupted}
