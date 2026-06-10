"""Background job dispatcher (DESIGN.md §22, §31).

A single dispatcher thread scans the durable queue and submits *eligible* jobs
to a thread pool. Eligibility enforces: instance not paused, per-instance
concurrency, FIFO per session, and per-repo serialization for code-mutating
deliverables. Jobs are claimed atomically (queued -> running) so a job is never
dispatched twice.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import instances, runner, store
from .config import load_config
from .errors import InstancePaused


class Worker:
    def __init__(self, max_parallel: int = 8):
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=max_parallel)
        self._thread: threading.Thread | None = None
        self._cfg = load_config()

    def start(self) -> None:
        recovered = store.recover_interrupted()
        if recovered["requeued"] or recovered["interrupted"]:
            print(f"[worker] recovery: {recovered}")
        self._thread = threading.Thread(target=self._loop, name="agenthook-dispatch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def notify(self) -> None:
        self._wake.set()

    # ---- internals --------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._dispatch_round()
            except Exception as exc:  # noqa: BLE001
                print(f"[worker] dispatch error: {exc}")
            self._wake.wait(timeout=0.5)
            self._wake.clear()

    def _dispatch_round(self) -> None:
        for job in store.queued_jobs():
            if self._stop.is_set():
                return
            if not self._eligible(job):
                continue
            if store.claim_job(job.id):
                try:
                    self._pool.submit(self._run, job.id)
                except RuntimeError:
                    # Pool is shutting down — put the job back for next boot.
                    from .models import JobStatus

                    job.status = JobStatus.QUEUED
                    store.save_job(job)
                    return

    def _eligible(self, job) -> bool:
        try:
            inst = instances.load(job.instance)
        except Exception:
            return False
        if inst.paused:
            return False
        concurrency = self._concurrency(inst)
        if store.running_count(inst.name) >= concurrency:
            return False
        if job.session_id and store.session_running(job.session_id):
            return False  # FIFO per session
        if job.deliverable.mutates_code and store.mutating_running(inst.name):
            return False  # serialize code changes per repo
        return True

    def _concurrency(self, inst) -> int:
        if isinstance(inst.limits, dict) and inst.limits.get("concurrency"):
            return int(inst.limits["concurrency"])
        return self._cfg.default_concurrency

    def _run(self, job_id: str) -> None:
        job = store.get_job(job_id)
        if job is None:
            return
        try:
            runner.run_job(job)
        except InstancePaused as exc:
            from .models import JobStatus

            job.status = JobStatus.QUEUED  # leave queued; instance is paused
            job.error_message = str(exc)
            store.save_job(job)
        except Exception as exc:  # noqa: BLE001
            from .models import JobStatus

            job.status = JobStatus.ERROR
            job.error_message = str(exc)
            store.save_job(job)
