# agenthook

> Self-hosted CLI to run **agentic coding CLIs** (Claude Code, OpenAI Codex, Gemini CLI,
> Aider, …) in **headless** mode, triggered by **webhooks**, inside isolated Docker
> containers — one reusable "instance" per repository.

agenthook is an open-source, self-hosted task runner for AI coding agents. You register a
repository as an **instance**, point your application at its webhook, and every POST runs the
configured engine against that repo and returns/commits/opens-a-PR with the result. Not every
job edits code — a job can also just **analyze** an interaction, **read a database** through
encrypted env vars, or **open a PR**.

**Status:** under active construction. The full design lives in [`DESIGN.md`](./DESIGN.md).

## Highlights

- **Multi-engine** via adapters (Claude Code is the reference engine).
- **Deliverables** orthogonal to execution mode: `analysis` / `action` / `patch` / `commit` / `pr`.
- **Sessions** keyed by `thread_key` — a support ticket / kanban card keeps context across POSTs.
- **Encrypted secrets** per instance; pluggable secret backends.
- **Verification loop** (self-heal) gating PRs on tests/lint.
- **Human-in-the-loop** plan approval (signed URLs + Slack).
- **Usage/cost auditing**, error taxonomy with circuit breaker, durable delivery guarantees.

## Quickstart (target UX)

```bash
pipx install agenthook
agenthook instance add myapp --repo git@github.com:me/app.git --deliverable pr
agenthook env set myapp ANTHROPIC_API_KEY sk-ant-... --secret
agenthook serve --port 8080
# POST http://localhost:8080/hook/myapp  { "prompt": "fix the pagination bug", "thread_key": "ticket-123" }
```

See [`DESIGN.md`](./DESIGN.md) for the complete architecture and decisions.

## License

MIT © 2026 Daniel Barcelos
