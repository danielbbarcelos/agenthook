# Changelog

## v1.2.0

Adds a control-plane way to run an instance ad-hoc and stream its output, so a
remote console (e.g. the Workspace) can offer an interactive "playground" without
holding the instance's webhook credential.

### Management API
- **`POST /admin/instances/<name>/run`** — enqueue a job against an instance from the
  control-plane, authenticated by the admin credential (no webhook secret needed). Works
  regardless of the instance's `webhook_auth` — the webhook schemes are ANDed, so bolting an
  extra bearer onto a hook would break a coexisting `hmac` integration. Honors an explicit
  `deliverable`/`mode` (operator authority) and returns `{job_id, status, session_id,
  stream_url}`.
- **`GET /admin/jobs/<id>/stream`** — the same live SSE feed as the public
  `GET /jobs/<id>/stream` (`event: text` deltas, `event: done` to close) but under `/admin/*`,
  so a console reaches it through the same channel it already uses for management (reverse
  proxies typically keep the public `/jobs` routes off the internet).

Internally, `/hook` and the new run endpoint share one job-creation path
(`_create_and_dispatch`), so their behavior can't drift.

## v1.1.0-beta

Beta release. Builds on v1.0.0 with live streaming and an interactive chat surface.

### Streaming
- **Live engine token streaming** — the server emits engine output as `event: text`
  SSE deltas on `GET /jobs/<id>/stream` (runner progress lines stay as plain `data:`
  events for back-compat; the feed ends with `event: done`). The same deltas drive the
  chat REPL and the TUI, so a job can be watched thinking in real time.

### Chat / shell
- **`agenthook enter`** — multi-turn chat REPL against an instance: per-turn token
  streaming, a live elapsed timer, real Ctrl+C cancel (kills the container), ↑/↓ input
  history seeded from the thread, and resume of a previous conversation via `--thread-key`.
  Slash commands `/new`, `/note`, `/repos`, `/deliverable`, `/help`, `/exit`.
- **`agenthook shell`** — interactive shell inside the instance's isolated sandbox.
- **`agenthook login`** — log a subscription account into the instance's own auth dir
  (the host's `~/.claude` is never used).

### Server / daemon
- **Background daemon** — `agenthook serve -d` runs the webhook server detached
  (pidfile + log), with `--stop`, `--status`, and `--logs`.

### TUI
- Select-all option when deleting jobs/chats, alongside single and multi-select.

## v0.1.1

### TUI / UX
- **Instance-first navigation** — the instances list is selectable; picking one opens a
  focused detail menu that stays open for several actions without re-selecting. A lone
  instance is entered directly, and the list is ordered by recency so the most-used floats
  to the top.
- **Delete jobs** (new) — single from the job view, multiple via a checkbox picker, in the
  global `jobs` menu and scoped inside an instance. `delete_job` also clears the job's audit
  rows and log file; `delete_session` now cleans its jobs' audit/logs too (no orphans).
- **Per-instance history** — jobs and chats are listed and deletable under a "history" group
  in the instance detail menu.
- Fixed the instance "back to list" entry doing nothing (only Ctrl+C worked).

### Security
- **Control-plane secrets never reach the agent** — the reserved `AGENTHOOK_*` namespace
  (e.g. webhook auth headers) is excluded from the env injected into the container.
- **Operator guardrail** (system prompt, on by default, every run): forbids disclosing or
  exfiltrating configuration, secrets, credentials, authenticated identities, token scopes,
  and connected integrations; resists prompt-injection (including embedded/"I am the
  operator" attempts); and blocks mass-destructive database ops (DELETE/UPDATE without WHERE,
  DROP DATABASE, TRUNCATE) and dumps/bulk exports — while allowing normal tool use and
  bounded, explicitly-requested changes. Validated with a 13-case live red-team.

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
