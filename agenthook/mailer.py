"""Minimal SMTP mailer (stdlib) — optional, for native-UI email recovery.

Configured via ``Config.smtp_*`` (password from ``AGENTHOOK_SMTP_PASSWORD`` env,
else ``config.smtp_password``). When unconfigured, :func:`is_configured` is False
and callers fall back to the CLI recovery path (``agenthook admin reset-password``).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from .config import Config, load_config


def _password(cfg: Config) -> str:
    return os.environ.get("AGENTHOOK_SMTP_PASSWORD") or cfg.smtp_password


def is_configured(cfg: Config | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg.smtp_host and cfg.smtp_from)


def send(to: str, subject: str, body: str, *, cfg: Config | None = None) -> None:
    cfg = cfg or load_config()
    if not is_configured(cfg):
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    msg["From"] = cfg.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as s:
        if cfg.smtp_starttls:
            s.starttls()
        pw = _password(cfg)
        if cfg.smtp_user and pw:
            s.login(cfg.smtp_user, pw)
        s.send_message(msg)
