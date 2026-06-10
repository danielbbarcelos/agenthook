# agenthook

> Self-hosted CLI to run **agentic coding CLIs** (Claude Code, OpenAI Codex, Gemini CLI,
> Aider, …) in **headless** mode, triggered by **webhooks**, inside isolated Docker
> containers — one reusable "instance" per repository.

agenthook is an open-source, self-hosted task runner for AI coding agents. You register a
repository as an **instance**, point your application at its webhook, and every POST runs the
configured engine against that repo. Not every job edits code — a job can also just
**analyze** an interaction, **read a database** through encrypted env vars, or **open a PR**.

The full design and rationale live in [`DESIGN.md`](./DESIGN.md) (32 sections).

## Highlights

- **Multi-engine** via adapters — Claude Code is the reference engine; Codex/Gemini/Aider ship too.
- **Deliverables** orthogonal to execution mode: `analysis` / `action` / `patch` / `commit` / `pr`.
- **Sessions** keyed by `thread_key` — a support ticket or kanban card keeps context across POSTs.
- **Encrypted secrets** per instance (immutable Fernet key), pluggable secret backends.
- **Verification loop** (self-heal) gating PRs on your tests/lint, with cost & iteration caps.
- **Human-in-the-loop** plan approval via signed URLs + a Slack reference connector.
- **Usage/cost auditing**, a normalized **error taxonomy** with a per-instance **circuit breaker**,
  durable **delivery guarantees** (persist-before-ack, idempotency, at-least-once callbacks).

## Install

```bash
pipx install agenthook            # or: pip install agenthook
# Build the per-job sandbox image (carries the engine CLI + git + gh):
docker build -t agenthook/runner:latest agenthook/docker
```

## Quickstart

```bash
# 1) Register a repo as an instance (prints an encryption key ONCE — store it).
agenthook instance add bugbot --repo git@github.com:me/app.git --deliverable pr

# 2) Add secrets (encrypted at rest; --secret hides them on list/get).
agenthook env set bugbot ANTHROPIC_API_KEY sk-ant-... --secret
agenthook env set bugbot GH_TOKEN ghp_... --secret

# 3) Optional: gate PRs on your tests, and require a webhook token.
agenthook verify bugbot --checks "npm test, npm run lint"
agenthook auth bugbot --scheme bearer
agenthook env set bugbot AGENTHOOK_WEBHOOK_TOKEN s3cr3t --secret

# 4) See exactly what would run — no execution, secrets masked.
agenthook dry-run bugbot --prompt "fix the pagination bug" --deliverable pr

# 5) Serve the webhook (embedded server — no Apache/nginx needed).
agenthook serve --host 0.0.0.0 --port 8080
```

Trigger it from your app:

```bash
curl -X POST http://localhost:8080/hook/bugbot \
  -H "Authorization: Bearer s3cr3t" \
  -H "Idempotency-Key: ticket-123" \
  -d '{
        "prompt": "fix the pagination bug in /users",
        "thread_key": "ticket-123",
        "request_type": "ticket",
        "requester": { "name": "Daniel" },
        "language": "pt-BR",
        "callback_url": "https://myapp/cb"
      }'
# -> 202 { "job_id": "j_…", "status": "queued", "stream_url": "/jobs/j_…/stream" }
```

Every POST carrying the same `thread_key` continues the **same session** (shared context),
so a ticket's whole back-and-forth stays in one conversation.

## Deliverables (what a job produces)

| deliverable | mutates repo? | output |
|-------------|---------------|--------|
| `analysis`  | no (read-only) | text/JSON parecer, returned + callback |
| `action`    | no (external effects via tools/MCP) | result summary |
| `patch`     | local only | `.diff` artifact |
| `commit`    | pushes a branch | branch |
| `pr`        | pushes + opens a PR | PR URL |

## Declarative config (GitOps)

```bash
agenthook apply -f examples/agenthook.yaml      # reconcile instances; secrets stay out of YAML
```

## Selected commands

```
agenthook instance add|list|show|rm|resume      env set|get|list|rm
agenthook context|auth|template|mcp|verify       apply   serve   install-service
agenthook run | dry-run | send [--replay]        jobs list|show   sessions list   logs -f
agenthook usage | audit [--export csv|json]
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q          # 35 tests, no Docker / no real engine needed
ruff check agenthook tests
```

`AGENTHOOK_HOME` overrides the state root (`~/.agenthook`) — handy for tests and multiple
isolated deployments. Set `use_docker: false` in `config.yaml` to run engines directly
(dev only).

## License

MIT © 2026 Daniel Barcelos
