"""agenthook — self-hosted runner for agentic coding CLIs via webhooks.

See DESIGN.md for the full architecture. Public API is intentionally small;
most functionality is reached through the CLI (`agenthook.cli`) and the HTTP
server (`agenthook.server`).
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:  # single source of truth = the installed package metadata (pyproject version)
    __version__ = _pkg_version("agenthook")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+dev"
