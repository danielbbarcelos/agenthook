# Agenthook → Workspace + Projector — plano de conclusão e integração

> Documento de planejamento. Autossuficiente. Companheiros:
> [`product-plan.md`](./product-plan.md), [`native-secrets-plan.md`](./native-secrets-plan.md),
> [`../deploy/go-live.md`](../deploy/go-live.md). Última revisão: 2026-07-20.

## 0. Arquitetura de três camadas (o reenquadramento)

```
┌─ Workspace (Laravel 12 + React, multi-tenant/multi-brand) ─────────────┐
│  App "Agenthook" via app-switcher (como Projector, Central).            │
│  CONSOLE DE GESTÃO:  org/account  ─┬─►  Server A (base_url + admin token│
│                                    │        name, tags, notas, test-auth)│
│                                    └─►  Server B ...                     │
│  Cada Server expõe N Instâncias, configuráveis via UI (== terminal).    │
└──────────────┬─────────────────────────────────────────────────────────┘
    server-to-server (backend Laravel guarda base_url + admin token cifrado)
               │  admin API /admin/*
               ▼
┌─ Agenthook (SELF-HOSTED na infra privada do usuário) ──────────────────┐
│  O MOTOR. admin API (/admin/*) + webhook API (/hook/*). SQLite+Fernet.  │
│  Single-tenant por deployment. Cria containers runner/egress por job.   │
└──────────────▲─────────────────────────────────────────────────────────┘
    webhook HMAC /hook/{slug}      callback HMAC (finished)
               │                              │
┌─ Projector (consumidor: tickets / kanban) ─┴───────────────────────────┐
│  Por project: aba "Agenthook".  Seleciona/cria instância; define        │
│  instruções, uso (ticket|kanban), triggers, NOME do agente.             │
│  Emite webhook nos triggers; recebe callback; posta a resposta no       │
│  ticket/card com flag "via Agenthook — <agent_name>".                   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Fronteira de tenant = o registro do Server no Workspace.** Cada org registra
seu(s) próprio(s) Server(s); o Agenthook em si permanece **single-tenant**. Isso
**dispensa** o roteamento `org/brand` dentro do Agenthook (lacuna que estava em
aberto no balanço anterior — resolvida por arquitetura, não por código).

> ⚠️ **Regra de confiança:** o admin token controla **todas** as instâncias de um
> Server. Portanto **um Server = uma fronteira de confiança** (idealmente um por
> org). Um Server compartilhado entre orgs = exposição cross-org. O Workspace deve
> impedir que orgs diferentes registrem/enxerguem o mesmo Server.

## 1. Descobertas da revisão (o que já existe e encaixa)

| Requisito da visão | Já existe no Agenthook | Nota |
|---|---|---|
| "instruções para cada instância" | **`instructions`** no webhook (feito nesta sessão) | mapeia 1:1 |
| "usada em Ticket ou Kanban" | `request_type` + templates `ticket`/`kanban` | — |
| Config por UI == por terminal | admin API cobre instances/env/auth/guardrails/templates/mcp/skills/repos/context/verify/engine-auth | paridade quase total |
| "testar autenticação" | qualquer `/admin/*` com bearer; `/healthz`,`/readyz` | ver §2.1 (opcional `/admin/ping`) |
| Resposta volta ao ticket | **callback HMAC** já emitido (`results.py`): event, job_id, instance, status, thread_key, result, pr_url, usage, metadata | falta o **receiver** no Projector |
| Sessão por ticket/card | `/hook/{name}/sessions` (multi-turn) | **já é a base do "chat" da fase futura** |
| Criar instância via API | `POST /admin/instances` | retorna a **encryption key 1×** — ver §2.3 |

**Conclusão da revisão:** o motor já cobre a maior parte do contrato. O trabalho
restante no Agenthook é **de exposição/empacotamento**, não de features.

## 2. Concluir o motor Agenthook (integration-ready)

### 2.1 Acesso remoto ao admin API — o maior gap  *(decisões travadas 2026-07-20)*
Cenário: **Workspace = SaaS centralizado (nosso); Agenthook self-hosted no
cliente**; o tráfego cruza a internet. O Agenthook do cliente aceita inbound do
nosso SaaS (`/hook` + `/admin`) e faz outbound (callback).

- **Modelo: exposição pública restrita (reverse-proxy).** Consistente com o
  `go-live.md` (que já publica `/hook`+`/healthz`); adicionar `/admin` restrito é
  incremental. Túnel phone-home ("Agenthook Connect") = **fase futura**.
- **Comunicação server-to-server.** O backend do Workspace guarda `base_url` +
  segredo **cifrado** e faz **proxy** (o segredo nunca vai ao browser, sem CORS).
- **Portão do `/admin`:** **IP-allow do egress do SaaS (opcional)** + **TLS** +
  **token**. **mTLS = opcional/documentado** (não obrigatório no v1).
- **Token de máquina = JWT HS256 curto (não mais o estático).** O segredo
  cadastrado no Workspace é a chave de assinatura HS256; o backend cunha um JWT
  com **`exp` ~5 min + `jti` anti-replay** e o envia como `Authorization: Bearer`.
  O `admin_auth.py` **valida** (assinatura + `exp` + `jti` não-reusado, com um
  cache curto de `jti` até expirar) e **aceita o token estático legado em
  paralelo** (retrocompatível). Sem endpoint de exchange, stateless. Precedente de
  JWT no repo: `github_app.py`.

**Ações no Agenthook:** (a) caminho JWT no `admin_auth.py` (+ cache de `jti`);
(b) `admin_remote: true` + IP-allow opcional + rate-limit no `/admin`;
(c) opcional `/admin/ping` (whoami) para o "test-auth" do Workspace;
(d) documentar o padrão de exposição segura.

### 2.2 Containerização do control-plane (hospedagem privada)
O usuário hospeda em infra própria → empacotamento limpo é essencial.
- `docker-compose`: **control-plane** + reutiliza imagens **runner** e **egress**.
- **Volume persistente** para `~/.agenthook` (SQLite + `env.enc` + `instance.key`).
- Reverse proxy TLS (Caddy/nginx dos exemplos do `deploy/`).
- Decisão: **DooD** (montar `/var/run/docker.sock`; recomendado — leve, egress
  lockdown intacto) vs **DinD** (`--privileged`, mais isolado, mais pesado).

### 2.3 Provisionamento de instância via API ("criar ali mesmo" no Projector)
- `POST /admin/instances` já existe, mas **retorna a encryption key UMA vez** — o
  proxy do Workspace precisa **capturar e guardar** (ou confiar no `instance.key`
  em disco do host). Definir o tratamento desse retorno na UI.
- Instância "utilizável" é multi-passo (engine auth + repos + templates). Duas
  rotas: **(a)** UI guia o multi-step; **(b)** endpoint `quick-create` com defaults
  seguros (`deliverable=analysis`, `mode=plan`) e configuração posterior.

### 2.4 Atribuição do agente ("via Agenthook" + nome)
- O **nome do agente vive no Projector** (config por project-instância). O callback
  já traz `instance`/`job_id`/`thread_key`/`metadata` → o Projector mapeia
  instância→nome e renderiza a flag ao postar a resposta.
- **Enhancement opcional (pequeno) no Agenthook:** aceitar `agent_name` no payload
  do webhook e **ecoá-lo no callback**, e ecoar `request_type`/`subject_ref` no
  callback — facilita a correlação e a atribuição sem lookup extra.

### 2.5 Setup guideline (doc user-facing)
Guia de setup self-host derivado do `go-live.md`, mas voltado ao **usuário final do
Workspace**: subir o Agenthook (compose), obter `base_url` + admin token, testar a
auth, e a partir daí gerir tudo pela UI. É o "guideline de setup" que a visão pede.

### 2.6 Paridade UI ↔ terminal
A admin API já dá quase paridade total. Ação: revisar se falta algum endpoint para
a UI cobrir 100% do que o terminal faz (candidatos: expor `capabilities`/`engines`
— `/admin/engines` já existe). Provavelmente completo; validar na implementação da UI.

### 2.7 UI nativa & auth de dois planos  *(trilha PARALELA — não bloqueia a integração)*
O token estático de hoje é fraco para **humanos**. Separar em dois planos:

- **Plano humano — UI nativa (`/ui`):** login de verdade. **Admin único (v1)**;
  multi-usuário/RBAC fica para o futuro. **Senha (Argon2id)** + **MFA TOTP opcional
  (recomendado)** + **recuperação**. **SMTP opcional** destrava email-MFA e
  recuperação por email; sem SMTP, **reset via CLI** (`agenthook admin
  reset-password`) — o dono do host sempre destrava. Bootstrap do primeiro admin
  **via CLI** (`agenthook admin create-user`; sem janela web sem-auth). **Sessão
  server-side no SQLite** (cookie `HttpOnly`/`Secure`/`SameSite`, idle timeout,
  revogável).
- **Plano de máquina — API/Workspace:** o **JWT curto** do §2.1 (sem senha/MFA).

**Flag `native_ui: enabled|disabled`** (default **enabled**): controla **só** o
mount do `/ui` (o `/admin` permanece; o CLI sempre funciona). O guideline do
Workspace recomenda **`disabled`** para gestão Workspace-first. O `/ui` **nunca** é
publicado pelo reverse-proxy (fica local/tunnel), mesmo `enabled`.

> Esta trilha é **maior** (subsistema de auth) e **não bloqueia** o go-live via
> Workspace (que só precisa do JWT/token). Rodar em paralelo à Fase I.

## 3. Contrato para o Projector (lado consumidor)
- **Aba Agenthook por project:** escolher Server (do registro do Workspace) +
  instância; ou criar instância (via proxy admin API).
- **Por instância no project:** instruções → campo **`instructions`** do webhook;
  uso (ticket|kanban) → **`request_type`**; **triggers** (lógica Projector-side:
  ao abrir ticket externo, ao receber interação externa, etc.); **nome do agente**.
- **Emissor:** `POST /hook/{slug}` assinado (HMAC `X-Agenthook-Signature`) com
  `request_type`, `thread_key`, `subject_ref`, `requester`, `language`,
  `instructions`, `attachments`, `callback_url`, `Idempotency-Key`.
- **Receiver de callback:** endpoint que valida HMAC + `seq`, idempotente, e posta a
  resposta no ticket/card com a flag **"via Agenthook — <agent_name>"**.

## 4. Sequência recomendada

- **Fase I — Concluir o motor (Agenthook):** §2.1 exposição remota segura (+ `/admin/ping`) →
  §2.2 containerização (compose, DooD) → §2.5 guideline → §2.4 (opcional) echo no callback.
- **Fase II — Workspace (console):** registro org→Servers (token cifrado, name/tags/
  notas, test-auth) → proxy server-to-server + UI de config de instâncias.
- **Fase III — Projector:** aba Agenthook por project (select/create instância,
  instruções, uso, triggers, agent name) → emissor HMAC + receiver de callback + atribuição.
- **Fase IV — (futuro) Chat com instâncias:** já tem fundação em `/hook/{name}/sessions`
  (multi-turn por `thread_key`).

## 5. Decisões resolvidas (entrevista 2026-07-20)
- [x] **Exposição `/admin`:** reverse-proxy restrito (público, cenário SaaS→cliente),
  server-to-server. Túnel phone-home = fase futura.
- [x] **Portão `/admin`:** IP-allow **opcional** + TLS + **JWT HS256 curto** (`exp`
  5 min + `jti`), token estático legado aceito em paralelo. mTLS opcional/documentado.
- [x] **UI nativa:** flag `native_ui` (default enabled, mexe só no `/ui`). Auth de
  dois planos: UI = login humano (admin único v1, senha Argon2id, TOTP opcional,
  SMTP opcional, reset via CLI, sessão server-side SQLite); API = JWT. Multi-usuário/
  RBAC = futuro. **Trilha paralela**, não bloqueia go-live.
- [x] **Containerização:** control-plane containerizado + **DooD via `docker compose`**.
- [x] **Criar instância:** reusar `POST /admin/instances` + UI multi-step; encryption
  key = backup opcional 1×.
- [x] **Atribuição:** **sem echo** de `agent_name` (Projector correlaciona por `job_id`).
  Echo de `request_type`/`subject_ref` no callback = deferido (não adotado).
- [x] **Isolamento:** um **Server por org** (o Workspace impõe; server compartilhado
  entre orgs é proibido).

## 6. Dívida de documentação (passada final)
Ao concluir, atualizar: **guideline de setup** (novo, user-facing), `go-live.md`
(compose/DooD + `/admin` remoto + JWT), `README`, `DESIGN.md` (auth de dois planos,
`native_ui`, `instructions`), e os docs de plano. Rastrear numa checklist única.
