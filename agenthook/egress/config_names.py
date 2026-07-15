"""Shared names/ports for the egress broker (host side and image agree here)."""

from __future__ import annotations

BROKER_NAME = "agenthook-egress"  # the long-lived broker container
BROKER_ALIAS = "egress"  # DNS alias the job container uses on the internal net
BROKER_IMAGE = "agenthook/egress:latest"
GW_PORT = 8080  # data plane (gateway + forward proxy), inside the network
CTRL_PORT = 8079  # control plane, published to host loopback only
