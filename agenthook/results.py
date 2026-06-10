"""Outbound result delivery: callbacks and notifications (DESIGN.md §31, §19).

Callbacks are at-least-once with retry+backoff, HMAC-signed, and carry a
per-job event sequence number so the receiver can stay idempotent. Chat
notifications go through the pluggable channel layer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from .config import load_config
from .instances import Instance
from .models import Job


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(job: Job, event: str, seq: int) -> dict:
    return {
        "event": event,
        "seq": seq,
        "job_id": job.id,
        "instance": job.instance,
        "status": job.status.value,
        "deliverable": job.deliverable.value,
        "thread_key": job.thread_key,
        "error_class": job.error_class,
        "pr_url": job.pr_url,
        "result": (job.result.text if job.result else None),
        "usage": job.usage.to_dict(),
        "metadata": job.metadata,
    }


def deliver_callbacks(job: Job, inst: Instance) -> None:
    """Fire the configured result actions for a finished (or parked) job."""
    from .models import JobStatus

    cfg = load_config()
    actions = inst.on_result or ["logs"]

    # A plan parked for approval: ask a human via the channel (DESIGN.md §19).
    if job.status is JobStatus.AWAITING_APPROVAL:
        _request_approval(job, inst, cfg)
        return

    callback_url = (job.request or {}).get("callback_url") or inst.callback_url
    if "callback" in actions and callback_url:
        _post_callback(callback_url, job, cfg.approval_secret, cfg.callback_max_attempts)

    if "notify" in actions:
        _notify(job, inst)


def _request_approval(job: Job, inst: Instance, cfg) -> None:
    from . import approval
    from .channels import get_channel

    token_a = approval.make_token(cfg.approval_secret, job.id, "approve", cfg.approval_ttl_s)
    token_r = approval.make_token(cfg.approval_secret, job.id, "reject", cfg.approval_ttl_s)
    base = cfg.public_base_url.rstrip("/")
    approve_url = f"{base}/jobs/{job.id}/approve?token={token_a}"
    reject_url = f"{base}/jobs/{job.id}/reject?token={token_r}"
    scheme = (inst.webhook_auth or {}).get("notify_channel", "slack")
    try:
        get_channel(scheme).request_approval(job, approve_url, reject_url)
    except Exception:  # noqa: BLE001
        pass


def _post_callback(url: str, job: Job, secret: str, max_attempts: int) -> None:
    body = json.dumps(_payload(job, "finished", seq=job.attempts)).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Agenthook-Signature": sign(secret, body),
        "X-Agenthook-Event": "finished",
        "X-Agenthook-Job": job.id,
    }
    for attempt in range(1, max_attempts + 1):
        try:
            r = httpx.post(url, content=body, headers=headers, timeout=15)
            if r.status_code < 500:
                return  # delivered (or a client error we won't fix by retrying)
        except Exception:  # noqa: BLE001
            pass
        time.sleep(min(2 ** attempt, 30))
    # Exhausted: in a fuller build this lands in a callbacks DLQ.


def _notify(job: Job, inst: Instance) -> None:
    from .channels import get_channel

    scheme = (inst.webhook_auth or {}).get("notify_channel", "slack")
    try:
        channel = get_channel(scheme)
    except Exception:
        return
    channel.notify(job, "finished")
