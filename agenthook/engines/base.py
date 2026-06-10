"""Engine adapter abstraction (DESIGN.md §16).

agenthook is engine-agnostic: an instance picks an ``engine`` and the rest of
the system stays identical — only the adapter changes. An adapter knows how to
turn an engine-neutral :class:`RunSpec` into the concrete CLI ``argv`` for its
tool, how to parse that tool's output into a normalized :class:`Result`, which
context filename it reads, and which env vars carry its auth.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from ..errors import ClassifiedError
from ..instances import Instance
from ..models import Deliverable, Mode, Result


@dataclass
class Capabilities:
    plan_mode: bool = False
    json_output: bool = False
    mcp: bool = False
    resume: bool = False
    cost: bool = False  # reports token/cost usage
    vision: bool = False  # accepts image attachments
    allowed_tools: bool = False  # supports per-tool allow/deny


@dataclass
class RunSpec:
    """Engine-neutral description of a single run/turn."""

    prompt: str
    mode: Mode = Mode.DEFAULT
    deliverable: Deliverable = Deliverable.ANALYSIS
    model: str | None = None
    max_turns: int | None = None
    allowed_tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    resume_session_id: str | None = None
    sandbox: bool = True  # running inside an isolated container
    extra_args: list[str] = field(default_factory=list)


class Engine(abc.ABC):
    name: str = "base"
    binary: str = ""
    context_filename: str = "AGENTS.md"
    capabilities: Capabilities = Capabilities()

    # ---- command construction --------------------------------------------

    @abc.abstractmethod
    def build_argv(self, spec: RunSpec) -> list[str]:
        """Return the argv to execute the engine headlessly for ``spec``."""

    # ---- output normalization --------------------------------------------

    @abc.abstractmethod
    def parse_output(
        self, stdout: str, stderr: str, exit_code: int
    ) -> tuple[Result, ClassifiedError | None]:
        """Normalize raw CLI output into (Result, error-or-None)."""

    # ---- auth -------------------------------------------------------------

    def auth_env_names(self, inst: Instance) -> list[str]:
        """Names of env vars that must be present for this engine's auth."""
        return []

    def auth_config_env(self, inst: Instance, auth_dir) -> dict[str, str]:
        """Env vars that point the engine at the instance's ISOLATED config/auth
        dir, so it never reads the host's ambient login. Default: none."""
        return {}

    def login_argv(self, auth_dir) -> list[str] | None:
        """argv that interactively logs a subscription account into ``auth_dir``,
        or None if this engine has no interactive login."""
        return None

    def credential_files(self, auth_dir) -> list:
        """Files under ``auth_dir`` whose presence means a login exists. Empty
        when the engine isn't dir-credential based (e.g. pure api-key)."""
        return []

    # ---- helpers ----------------------------------------------------------

    def supports(self, *, plan: bool = False, resume: bool = False, mcp: bool = False) -> bool:
        c = self.capabilities
        return (not plan or c.plan_mode) and (not resume or c.resume) and (not mcp or c.mcp)

    def read_only_disallowed_tools(self) -> list[str]:
        """Tools to forbid for read-only deliverables (analysis)."""
        return ["Edit", "Write", "NotebookEdit"]
