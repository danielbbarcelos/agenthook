"""Normalized error taxonomy and retry policy (DESIGN.md §17).

Every engine fails differently (exit codes, stderr text, JSON error fields).
Adapters map those raw failures onto :class:`ErrorClass` so the rest of the
system can reason about retries, circuit breaking and reporting uniformly.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass


class ErrorClass(str, enum.Enum):
    AUTH = "AUTH"  # 401/403, expired key/oauth -> circuit breaker, no retry
    RATE_LIMIT = "RATE_LIMIT"  # 429 -> retry with backoff
    SERVER = "SERVER"  # 5xx/overloaded -> retry with backoff
    QUOTA = "QUOTA"  # 402, credits exhausted -> circuit breaker
    BLOCKED = "BLOCKED"  # safety/content refusal -> terminal
    CONTEXT_LIMIT = "CONTEXT_LIMIT"  # prompt too large -> terminal
    TIMEOUT = "TIMEOUT"  # wall-clock exceeded -> terminal by default
    ENGINE_CRASH = "ENGINE_CRASH"  # non-zero exit / malformed output -> retry once
    BAD_OUTPUT = "BAD_OUTPUT"  # could not parse output -> retry once
    UNKNOWN = "UNKNOWN"  # everything else -> DLQ


#: Classes that may be retried (subject to per-instance max attempts).
RETRYABLE = {ErrorClass.RATE_LIMIT, ErrorClass.SERVER}

#: Classes retried at most once.
RETRY_ONCE = {ErrorClass.ENGINE_CRASH, ErrorClass.BAD_OUTPUT}

#: Classes that pause the whole instance (circuit breaker).
CIRCUIT_BREAK = {ErrorClass.AUTH, ErrorClass.QUOTA}


@dataclass
class ClassifiedError:
    error_class: ErrorClass
    message: str
    retry_after: float | None = None  # seconds, honoured for RATE_LIMIT

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRYABLE or self.error_class in RETRY_ONCE

    @property
    def breaks_circuit(self) -> bool:
        return self.error_class in CIRCUIT_BREAK


class AgenthookError(Exception):
    """Base class for agenthook runtime errors surfaced to the user."""


class InstancePaused(AgenthookError):
    """Raised when a job targets an instance held open by the circuit breaker."""


# --- Heuristic classifier shared by engine adapters -------------------------

_PATTERNS: list[tuple[ErrorClass, re.Pattern[str]]] = [
    (ErrorClass.AUTH, re.compile(r"\b(401|403|unauthorized|forbidden|invalid api key|authentication)\b", re.I)),
    (ErrorClass.QUOTA, re.compile(r"\b(402|quota|insufficient_quota|credit|billing|payment required)\b", re.I)),
    (ErrorClass.RATE_LIMIT, re.compile(r"\b(429|rate.?limit|too many requests)\b", re.I)),
    (ErrorClass.SERVER, re.compile(r"\b(500|502|503|529|overloaded|internal server error|service unavailable)\b", re.I)),
    (ErrorClass.BLOCKED, re.compile(r"\b(content[_ ]policy|safety|refus|blocked|moderation)\b", re.I)),
    (ErrorClass.CONTEXT_LIMIT, re.compile(r"\b(context|maximum.*tokens|too long|prompt is too large)\b", re.I)),
]


def classify_text(text: str, *, exit_code: int | None = None) -> ClassifiedError:
    """Best-effort classification from combined stdout/stderr text.

    Adapters can override or pre-empt this with structured signals (e.g. a JSON
    error field), but this covers the common case where only text is available.
    """
    blob = text or ""
    retry_after = _parse_retry_after(blob)
    for klass, pattern in _PATTERNS:
        if pattern.search(blob):
            return ClassifiedError(klass, _first_line(blob), retry_after)
    if exit_code is not None and exit_code != 0:
        return ClassifiedError(ErrorClass.ENGINE_CRASH, _first_line(blob) or f"exit code {exit_code}")
    return ClassifiedError(ErrorClass.UNKNOWN, _first_line(blob) or "unknown error")


def _parse_retry_after(text: str) -> float | None:
    m = re.search(r"retry[-_ ]after[\"':=\s]+(\d+(?:\.\d+)?)", text, re.I)
    return float(m.group(1)) if m else None


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:500]
    return ""
