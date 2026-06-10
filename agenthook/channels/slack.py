"""Slack reference channel (DESIGN.md §19).

Posts to an incoming webhook URL (``SLACK_WEBHOOK_URL``). Approval uses Block Kit
*URL buttons* pointing at the signed approve/reject endpoints, so it works with a
plain incoming webhook — no full Slack app required for the reference flow.
"""

from __future__ import annotations

import os

import httpx

from ..models import Job
from .base import ApprovalChannel


class SlackChannel(ApprovalChannel):
    name = "slack"

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")

    def _post(self, payload: dict) -> None:
        if not self.webhook_url:
            return
        try:
            httpx.post(self.webhook_url, json=payload, timeout=10)
        except Exception:  # noqa: BLE001 - notifications must never crash a job
            pass

    def request_approval(self, job: Job, approve_url: str, reject_url: str) -> None:
        text = f"*agenthook* plan ready for `{job.instance}` (job `{job.id}`)"
        plan = (job.result.text if job.result else "") or "(no plan text)"
        self._post(
            {
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": text}},
                    {"type": "section", "text": {"type": "mrkdwn", "text": plan[:2900]}},
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "style": "primary",
                                "text": {"type": "plain_text", "text": "Approve"},
                                "url": approve_url,
                            },
                            {
                                "type": "button",
                                "style": "danger",
                                "text": {"type": "plain_text", "text": "Reject"},
                                "url": reject_url,
                            },
                        ],
                    },
                ]
            }
        )

    def notify(self, job: Job, event: str) -> None:
        emoji = {"finished": "✅", "error": "❌", "blocked": "🚫"}.get(job.status.value, "ℹ️")
        msg = f"{emoji} agenthook `{job.instance}` job `{job.id}` → *{job.status.value}*"
        if job.pr_url:
            msg += f"\n{job.pr_url}"
        self._post({"text": msg})
