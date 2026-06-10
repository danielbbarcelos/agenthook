"""Approval / notification channel abstraction (DESIGN.md §19)."""

from __future__ import annotations

import abc

from ..models import Job


class ApprovalChannel(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def request_approval(self, job: Job, approve_url: str, reject_url: str) -> None:
        """Ask a human to approve/reject a parked (plan) job."""

    @abc.abstractmethod
    def notify(self, job: Job, event: str) -> None:
        """Notify a channel about a job lifecycle event."""
