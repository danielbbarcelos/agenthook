# Agenthook — deploy & go-live (VPS + systemd + TLS)

Single-tenant VPS, secrets via `local-encrypted`/`env` (no OpenBao in the MVP).
Companion to [`../docs/security-and-secrets.md`](../docs/security-and-secrets.md) §5.

## 0. Prerequisites (as root, once)

```bash
adduser --disabled-password --gecos "" agenthook
usermod -aG docker agenthook          # or set up rootless docker for the user
loginctl enable-linger agenthook      # user units run without a login session
```

## 1. Build & install (as `agenthook`)

The web panel bundle is **git-ignored** and ships inside the wheel (built from
`web/` into `agenthook/static/panel/`), so rebuild it before building the wheel:

```bash
cd web && npm ci && npm run build && cd ..     # -> agenthook/static/panel/
python -m build                                # wheel bakes in the panel via [artifacts]
pipx install ./dist/agenthook-*.whl
# assert the panel shipped:
python -c "import agenthook,os;print(os.listdir(os.path.join(os.path.dirname(agenthook.__file__),'static','panel')))"
```

Build the two images this host needs:

```bash
docker build -t agenthook/runner:latest agenthook/docker    # per-job sandbox (engine CLI)
docker build -t agenthook/egress:latest agenthook/egress    # egress broker (fail-closed net)
```

## 2. Service (systemd user unit)

```bash
agenthook install-service --port 8080 --write   # writes ~/.config/systemd/user/agenthook.service
# EDIT ExecStart to bind loopback: `agenthook serve --host 127.0.0.1 --port 8080`
systemctl --user daemon-reload
systemctl --user enable --now agenthook
ss -ltnp | grep 127.0.0.1:8080                  # confirm loopback, NOT 0.0.0.0
curl -s http://127.0.0.1:8080/healthz           # {"ok": true}
```

(Reference unit: [`agenthook.service`](./agenthook.service).)

## 3. Reverse proxy (TLS)

Run **on the same host** (proxy → 127.0.0.1:8080) so uvicorn honors
`X-Forwarded-For`. Expose only `/hook/*` and `/healthz`; keep `/admin`, `/ui`,
`/jobs` off the internet.

- Caddy (auto-TLS): [`Caddyfile.example`](./Caddyfile.example)
- nginx: [`nginx.conf.example`](./nginx.conf.example)

Operator access to the panel/admin is via SSH tunnel:

```bash
ssh -N -L 8080:127.0.0.1:8080 agenthook@vps    # then browse http://127.0.0.1:8080/ui
```

## 4. `config.yaml` (`~/.agenthook/config.yaml`)

`approval_secret` and `admin_token` are auto-generated and persisted on first
run — don't commit them. Then set:

```yaml
public_base_url: https://hooks.example.com   # REQUIRED: plan->apply approval links embed this
use_docker: true
admin_remote: false                          # /admin/* loopback-only
egress_enabled: true                         # fail-closed job network (see docs §5)
# egress_allow_default: ["projector.internal"]   # hosts every job may reach (e.g. your API)
```

## 5. Per-instance secrets (no OpenBao)

```bash
# engine auth (api-key mode; or use the subscription login flow in the panel)
agenthook env set <inst> ANTHROPIC_API_KEY sk-ant-...  --secret

# webhook auth (reserved names read by the auth layer)
agenthook env set <inst> AGENTHOOK_WEBHOOK_TOKEN "$(openssl rand -hex 32)" --secret
agenthook auth <inst> --scheme bearer,ip-allow --ip-allow 203.0.113.0/24    # all schemes must pass

# GitHub App (ephemeral git tokens — preferred over a static GH_TOKEN)
agenthook env set <inst> AGENTHOOK_GH_APP_ID 123456 --secret
agenthook env set <inst> AGENTHOOK_GH_APP_INSTALLATION_ID 987654 --secret
agenthook env set <inst> AGENTHOOK_GH_APP_PRIVATE_KEY "$(cat app.private-key.pem)" --secret
```

For a code-writing/PR instance, keep the default `deliverable=analysis` and let
per-request overrides opt into `pr`; do **not** set `allow_auto_apply` — writes
then go through plan→apply (human approval).

## 6. Smoke test

```bash
curl -fsS https://hooks.example.com/healthz                                   # 200
curl -s -o /dev/null -w '%{http_code}\n' https://hooks.example.com/admin/instances  # 404 (not exposed)
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://hooks.example.com/hook/<inst> -d '{}'  # 401
# authed webhook -> 202 -> job runs; a `pr` job -> AWAITING_APPROVAL -> approval link (https) works
```

Verify egress is actually closed (the load-bearing guarantee):

```bash
AGENTHOOK_DOCKER_IT=1 pytest tests/test_egress.py::test_egress_fail_closed_live -q
```

## 7. Go-live checklist (maps to security-and-secrets §5)

| §5 item | Status in this build |
|---|---|
| Egress lockdown in the job container | ✅ M2 — internal network, fail-closed |
| HTTP gateway — no API key in container env | ✅ M2 — broker injects the key (dummy in container) |
| GitHub App short-lived token (not static PAT) | ✅ M3 — per-job installation token, revoked at finalize |
| DB user read-only by default; writes gated | ⚠️ provision a **read-only Postgres role** on the DB side |
| `deliverable=analysis` + `mode=plan` default; writes behind plan→apply | ✅ M1 — coercion + approval two-step |
| Ticket payload in a delimited block | ✅ guardrail (verify per-instance templates) |
| Per-instance isolation, no cross-project | ✅ per-instance env.enc + auth dir + container + egress token |
| Audit job_id ↔ ticket/card | ✅ audit rows incl. approver IP; correlate on job_id |
| Webhook rate limiting | ✅ M1 — two-tier token bucket |

**Remaining operator action:** create the read-only DB role and point instances
at it; the anti-DROP guardrail is soft — the read-only grant is the hard control.

## 8. Upgrade (in place — your data is preserved)

All runtime state — `config.yaml`, `instances/`, `jobs.db`, `repos/` — lives under
`AGENTHOOK_HOME` (`~/.agenthook`), which is **separate from the installed code**.
Upgrading replaces code only; **it never overwrites your config or instances**, so you
do **not** re-clone or re-run the first-time setup.

From the source clone, as the `agenthook` user:

```bash
cd ~/agenthook            # your clone
agenthook upgrade         # git pull -> rebuild panel -> rebuild wheel -> pipx --force -> restart
```

`agenthook upgrade` is a thin wrapper over [`upgrade.sh`](./upgrade.sh). Useful flags:

```bash
agenthook upgrade --ref v1.3.0     # pin/roll to a specific release tag (recommended in prod)
agenthook upgrade --images         # ALSO rebuild the runner/egress Docker images (when they changed)
agenthook upgrade --skip-web       # skip the panel rebuild (no npm on the host)
agenthook upgrade --no-restart     # reinstall without bouncing the service
```

Equivalent without the CLI: `deploy/upgrade.sh [flags]`. Prereqs on the host: `git`,
`python` + the `build` package (`pip install build`), `pipx` (falls back to `pip`), `npm`
for the panel, and `docker` for `--images`. In-flight jobs are interrupted by the restart;
drain first with `agenthook service stop` if that matters. Roll back by pinning the previous
tag: `agenthook upgrade --ref <old>`.
