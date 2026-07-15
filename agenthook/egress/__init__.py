"""Host-side lifecycle + registration for the egress broker.

The broker (see :mod:`agenthook.egress.broker`) is a long-lived container that
the job containers are forced through. This module owns everything the *host*
does: create the internal network, ensure the broker container is up, and
register/deregister a job's per-job token before/after it runs.

All Docker interaction is via the ``docker`` CLI (subprocess) — the same
dependency the runner already assumes — so there is no Python docker SDK to add.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field

from .config_names import (
    BROKER_ALIAS,
    BROKER_IMAGE,
    BROKER_NAME,
    CTRL_PORT,
    GW_PORT,
)


@dataclass
class EgressGrant:
    """Everything a single job needs to run under the broker (host-issued).

    ``container_env`` is added to the job container (gateway BASE_URL, dummy key,
    proxy vars); ``strip_env`` names the real credentials removed from the
    injected env so they never enter the container."""

    token: str
    network: str
    allow: list[str] = field(default_factory=list)
    container_env: dict[str, str] = field(default_factory=dict)
    strip_env: list[str] = field(default_factory=list)


class EgressError(RuntimeError):
    pass


def _run(args: list[str], *, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, check=check, timeout=timeout
    )


def _network_exists(name: str) -> bool:
    r = _run(["docker", "network", "inspect", name], check=False)
    return r.returncode == 0


def _container_running(name: str) -> bool:
    r = _run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name], check=False
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _ensure_connected(network: str, container: str, alias: str) -> None:
    """Connect ``container`` to ``network`` with ``alias`` unless already on it."""
    r = _run(
        ["docker", "inspect", "-f", "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}", container],
        check=False,
    )
    if network in (r.stdout or "").split():
        return
    _run(["docker", "network", "connect", "--alias", alias, network, container], check=False)


def ensure_broker(network: str, *, ctrl_host_port: int) -> None:
    """Idempotently ensure the internal network + broker container are up.

    Fail-closed: if this cannot bring the broker up, it raises and the caller
    must not run the job (a job with no working broker would have no egress at
    all, or — worse, if we fell back to the default bridge — unrestricted egress).
    """
    # 1. internal network (no NAT to the internet)
    if not _network_exists(network):
        _run(["docker", "network", "create", "--internal", network])
    # A second, internet-facing network the broker is also attached to.
    egress_out = f"{network}-out"
    if not _network_exists(egress_out):
        _run(["docker", "network", "create", egress_out])

    # 2. broker container
    if not _container_running(BROKER_NAME):
        _run(["docker", "rm", "-f", BROKER_NAME], check=False)
        _run(
            [
                "docker", "run", "-d", "--name", BROKER_NAME,
                "--restart", "unless-stopped",
                "--network", egress_out,  # internet side
                "-p", f"127.0.0.1:{ctrl_host_port}:{CTRL_PORT}",  # control -> host loopback only
                "-e", f"AGENTHOOK_EGRESS_GW_PORT={GW_PORT}",
                "-e", f"AGENTHOOK_EGRESS_CTRL_PORT={CTRL_PORT}",
                BROKER_IMAGE,
            ]
        )
        _wait_healthy(ctrl_host_port)
    # attach the internal network (data plane) with a stable alias — idempotent,
    # so a network recreated under a still-running broker is reconnected.
    _ensure_connected(network, BROKER_NAME, BROKER_ALIAS)


def _wait_healthy(ctrl_host_port: int, *, tries: int = 30) -> None:
    url = f"http://127.0.0.1:{ctrl_host_port}/healthz"
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310
                if r.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise EgressError("egress broker did not become healthy")


def _ctrl(ctrl_host_port: int, path: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{ctrl_host_port}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
        if r.status != 200:
            raise EgressError(f"broker {path} failed: {r.status}")


def register(
    ctrl_host_port: int,
    token: str,
    *,
    upstream: str,
    header: str,
    value: str,
    allow: list[str],
) -> None:
    _ctrl(
        ctrl_host_port,
        "/register",
        {"token": token, "upstream": upstream, "header": header, "value": value, "allow": allow},
    )


def deregister(ctrl_host_port: int, token: str) -> None:
    try:
        _ctrl(ctrl_host_port, "/deregister", {"token": token})
    except Exception:  # noqa: BLE001 — best-effort revocation
        pass
