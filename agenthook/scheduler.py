"""Internal cron scheduler (DESIGN.md §28).

Each instance may declare ``schedules`` with cron expressions. The scheduler
thread enqueues a normal job for each due schedule, reusing the whole runner
pipeline (verify, deliverables, auditing, governance).
"""

from __future__ import annotations

import threading
import time

from croniter import croniter

from . import instances, store
from .models import Deliverable, Job, Mode


class Scheduler:
    def __init__(self, worker=None, tick_s: float = 30.0):
        self._worker = worker
        self._tick = tick_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[str, float] = {}  # "instance/name" -> last enqueue epoch

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="agenthook-cron", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._tick):
            try:
                self._scan()
            except Exception as exc:  # noqa: BLE001
                print(f"[scheduler] error: {exc}")

    def _scan(self) -> None:
        now = time.time()
        for inst in instances.list_all():
            if inst.paused:
                continue
            for sched in inst.schedules or []:
                key = f"{inst.name}/{sched.get('name', 'unnamed')}"
                cron = sched.get("cron")
                if not cron or not croniter.is_valid(cron):
                    continue
                base = self._last.get(key, now - self._tick)
                nxt = croniter(cron, base).get_next(float)
                if nxt <= now:
                    self._enqueue(inst, sched)
                    self._last[key] = now

    def _enqueue(self, inst, sched) -> None:
        job = Job(
            instance=inst.name,
            deliverable=Deliverable(sched.get("deliverable", inst.deliverable)),
            mode=Mode(sched.get("mode", inst.default_mode)),
            prompt=sched.get("prompt", inst.default_prompt or ""),
            request={"request_type": "schedule", "schedule": sched.get("name")},
        )
        store.create_job(job)
        print(f"[scheduler] enqueued {job.id} for {inst.name}/{sched.get('name')}")
        if self._worker:
            self._worker.notify()
