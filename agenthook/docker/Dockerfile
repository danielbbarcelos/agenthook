# agenthook runner image (DESIGN.md §5).
#
# This is the per-job sandbox image: it carries the engine CLI plus git and gh.
# agenthook mounts the job worktree at /workspace, injects the decrypted env,
# and runs the engine's argv inside this container (`docker run --rm`).
#
# Build:  docker build -t agenthook/runner:latest agenthook/docker
# The default engine baked in is Claude Code (the reference engine); add other
# engine CLIs here (codex, gemini, aider) as needed for your instances.

FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        curl \
        gnupg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Reference engine: Claude Code. Add other engines as required, e.g.:
#   RUN npm install -g @openai/codex @google/gemini-cli
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace

# Engines run as the argv passed by agenthook; no fixed ENTRYPOINT so the same
# image can run `claude …`, `sh -lc "<verify check>"`, etc.
CMD ["bash"]
