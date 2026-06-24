# agenthook · web panel

A React + shadcn/ui control-plane for the agenthook **Management API** (`/admin/*`).
It does over a UI everything the CLI does: instance CRUD & config (repos, webhook auth,
verify, MCP, CLAUDE.md context, **guardrails**, **skills**), encrypted env (masked), global
config, and observability (jobs/sessions/usage/audit) with **live job streaming** over SSE.

It inherits the project's visual identity from `design-system/` (amber-on-near-black palette,
JetBrains Mono, the shared status vocabulary of glyph + color).

## Stack

Vite · React · TypeScript · Tailwind · shadcn/ui · TanStack Query · React Router · CodeMirror.

## Develop

```bash
# 1) Backend running (it provides /admin and the SSE job stream):
agenthook serve --host 127.0.0.1 --port 8080

# 2) Panel dev server (proxies /admin, /jobs, /healthz to the backend — no CORS):
cd web
npm install
npm run dev          # http://localhost:5180/ui

# Point the proxy elsewhere with AGENTHOOK_API=http://host:port npm run dev
```

Log in by pasting the admin token:

```bash
python -c "from agenthook.config import load_config as c; print(c().admin_token)"
```

> The panel must run on localhost: the server's admin API is **loopback-only** by default.
> To reach a remote agenthook, set `admin_remote: true` in its `config.yaml`.

## Build (shipped with the server)

```bash
npm run build        # outputs to ../agenthook/static/panel
```

`agenthook serve` then serves the built panel at **`/ui`** (same origin as `/admin`, so no
CORS in production). The build dir is gitignored but included in the wheel.

## Checks

```bash
npm run typecheck    # tsc --noEmit
npm run test         # vitest
```
