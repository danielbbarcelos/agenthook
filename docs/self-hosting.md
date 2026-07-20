# Auto-hospedar o Agenthook (guia do usuário)

> Para quem vai rodar o Agenthook na **própria infra** e gerenciá-lo pelo
> **Workspace** (SaaS). Caminho containerizado (`docker compose`).
> Alternativa systemd (sem container): [`../deploy/go-live.md`](../deploy/go-live.md).

## O que você terá

Um Agenthook rodando **na sua máquina/VPS**, que o Workspace acessa remotamente
(server-to-server) para configurar instâncias e disparar jobs. Suas credenciais e
código **nunca saem da sua infra**; o Workspace guarda só o `base_url` + um token.

```
Workspace (SaaS) ──HTTPS──► seu reverse-proxy TLS ──► Agenthook (127.0.0.1:8080)
                                                          │ spawna (Docker do host)
                                                          ├─► runner (job)
                                                          └─► egress broker
```

## 0. Requisitos de servidor

**Software**
- **Linux** (kernel ~5.x+), com **Docker Engine** (28.x+) + **docker compose v2**.
- Um **domínio/subdomínio** apontando para a máquina (para o TLS), ex.: `hooks.seu-dominio.com`.
- **Reverse proxy TLS** — Caddy (auto-TLS) ou nginx (exemplos em `deploy/`).

**Hardware** — o peso real é o **container de job**: cada job roda o CLI do agente e
consome CPU/RAM. A concorrência padrão é **2 jobs simultâneos por instância**
(`default_concurrency`), e cada instância ativa soma.

| Recurso | Mínimo | Confortável |
|---|---|---|
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB+ (escala com jobs simultâneos) |
| Disco | 20 GB | 40 GB+ SSD |

Uso do disco: imagens (~1.1 GB — runner 700 MB + control-plane 277 MB + egress 119 MB)
+ estado em `AGENTHOOK_DATA` (SQLite + repos clonados + um worktree por job + logs). Repos
grandes e muitos jobs pesam. Sem jobs, o Agenthook é leve; o pico é durante os jobs.

**Rede / portas**
- **Entrada pública** (via reverse proxy TLS): só `/hook/*`, `/healthz` e — restrito ao **IP
  de egress do Workspace** — `/admin/*`.
- **App interno:** loopback `127.0.0.1:8080`. **Broker de egress:** loopback `127.0.0.1:8079`.
- **Saída (outbound)** a liberar: API do modelo (Anthropic), `github.com`, host do banco (se a
  instância usa DB) e o Workspace (callbacks). O egress lockdown já restringe o container de
  job a uma allowlist.

> Referência: um **VPS de 4 vCPU / 8 GB / 40 GB SSD** roda confortavelmente um cliente com
> poucas instâncias e 2–4 jobs simultâneos.

## 1. Buildar as imagens de job (uma vez)
O control-plane cria containers de job no daemon do host — essas imagens precisam existir:

```bash
git clone <repo> agenthook && cd agenthook
docker build -t agenthook/runner:latest agenthook/docker
docker build -t agenthook/egress:latest agenthook/egress
```

## 2. Subir o control-plane

```bash
export AGENTHOOK_DATA=/opt/agenthook/data     # onde o estado persiste no host
sudo mkdir -p "$AGENTHOOK_DATA"
docker compose up -d --build
curl -s http://127.0.0.1:8080/healthz         # {"ok": true}
```

O estado (config, instâncias cifradas, jobs) vive em `$AGENTHOOK_DATA` no host —
**faça backup dessa pasta**. Detalhes de por que `network_mode: host` +
path-parity: comentários no [`../docker-compose.yml`](../docker-compose.yml).

## 3. Liberar o acesso remoto do Workspace

O `/admin/*` é **loopback-only** por padrão. Para o Workspace alcançá-lo, edite
`$AGENTHOOK_DATA/config.yaml` (no host, criado no 1º boot):

```yaml
admin_remote: true
# opcional, recomendado: só o IP de egress do Workspace pode falar com o /admin
admin_ip_allow: ["<IP_DE_EGRESS_DO_WORKSPACE>/32"]
```

Reinicie: `docker compose restart`. Pegue o **token de admin** (gerado no 1º boot):

```bash
grep admin_token "$AGENTHOOK_DATA/config.yaml"
```

> O Workspace usa esse segredo para **cunhar um JWT curto (5 min)** por requisição
> — o token estático nunca trafega. Você também pode gerar o seu próprio segredo e
> setá-lo em `admin_token` (ou via env `AGENTHOOK_ADMIN_TOKEN`).

## 4. Reverse proxy TLS (a face pública)

Coloque um proxy TLS na frente do `127.0.0.1:8080`, expondo **só** `/hook`,
`/healthz` e (restrito ao IP do Workspace) `/admin`. Exemplos prontos em `deploy/`:
- Caddy (TLS automático): [`../deploy/Caddyfile.example`](../deploy/Caddyfile.example)
- nginx: [`../deploy/nginx.conf.example`](../deploy/nginx.conf.example)

## 5. Registrar no Workspace e testar

No app **Agenthook** do Workspace, adicione um **Server**:
- **base_url:** `https://hooks.seu-dominio.com`
- **token:** o `admin_token` do passo 3
- (nome, tags, notas à vontade)

Clique **testar autenticação** — por baixo isso chama `GET /admin/ping` com um JWT
curto; **200** = tudo certo. A partir daí, crie e configure instâncias pela UI do
Workspace (ou pelo CLI local — dá no mesmo).

## Gerência local opcional (CLI)
Tudo que a UI faz, o CLI também faz (mesma API). Ex. dentro do host:

```bash
docker compose exec agenthook agenthook instance add <nome> ...
docker compose exec agenthook agenthook env set <nome> DATABASE_URL <cred> --secret
```

## Nota — UI nativa
O painel nativo em `/ui` é servido para acesso local (via SSH tunnel), **nunca**
publicado pelo reverse-proxy. Um flag de setup para desligá-lo (gestão 100% pelo
Workspace) e o login humano com senha/MFA estão na trilha de hardening da UI nativa
(ver `docs/workspace-integration-plan.md` §2.7).
