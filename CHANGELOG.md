# Changelog

## v0.1.0 — first release

First public release of **agenthook**: a self-hosted CLI that runs agentic coding
CLIs (Claude Code as the reference engine; Codex, Gemini, Aider via adapters) in
headless mode, triggered by webhooks, inside isolated Docker containers.

### Core
- **Instances** — reusable config (repo pool + engine + auth + parameters),
  persisted as YAML, with an immutable per-instance encryption key.
- **Webhook server** (FastAPI/uvicorn) — `POST /hook/<instance>` routes by slug;
  per-instance auth (bearer / hmac / header / ip-allow), idempotency,
  persist-before-ack, async + `?wait`, SSE log streaming, `/healthz` `/metrics`.
- **Runner** — ephemeral Docker container per job; git worktree per run from a
  persistent per-instance mirror; deliverables `analysis` / `action` / `patch` /
  `commit` / `pr`; normalized error taxonomy + circuit breaker; verify self-heal.
- **Sessions** — durable threads keyed by `thread_key`, resumable across jobs.
- **Engines** — adapter interface with a capability matrix; Claude Code reference
  adapter (stream-json parsing, usage/cost, plan/auto modes).
- **Secrets** — per-instance encrypted env (`env.enc`); values masked in
  logs/dry-run; pluggable secrets backend.

### Security / isolation
- Per-instance **engine auth isolation**: no instance inherits the host's
  subscription or API key (`CLAUDE_CONFIG_DIR` relocated per instance).
- Containers run as the **host user (non-root)**, matching mounted file
  ownership and satisfying Claude's non-root requirement.
- `gh` / GitHub access is per-instance via an encrypted `GH_TOKEN`.
- Deleting an instance wipes all of its state (auth, mirrors, logs).

### Guided TUI
- Bare `agenthook` opens an arrow-key menu; every flow also has a dry CLI command.
- Rounded, full-width navigation boxes and tables with a subtle hairline border;
  a hero banner, breadcrumbs, and a real screen-clear (no scrollback soup).
- Instance lifecycle: add wizard (progress rail + one-time key step), view, edit,
  per-field editors for authentication, GitHub token, webhook headers, repo pool
  (add/edit, prefilled GitHub URL), and env vars.
- Instances list shows status + on-disk shell size; **rebuild shell** drops the
  cached clone so the next entry rebuilds.
- Jobs list + job runner (step rail, stats, inline plan approval); sessions
  thread view with resume-in-chat.
- **Shell** into an isolated container (build progress on first entry) and a
  multi-turn **chat** REPL with a live elapsed timer, real Ctrl+C cancel, and
  ↑/↓ input history seeded from the thread.

### Distribution
- `pipx install --editable .`; English UI throughout.
