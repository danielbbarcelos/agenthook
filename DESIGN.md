# agenthook — Design / PRD

> CLI Python instalável no servidor para criar e gerenciar "instâncias" que executam
> **agentic coding CLIs** (Claude Code, OpenAI Codex, Gemini CLI, Aider, …) em modo
> headless, via webhook, dentro de repositórios isolados em containers Docker.

Status: **rascunho de design** (sem código ainda)
Distribuição: **open-source, self-hosted**. Orientado a config/arquivo, extensível por
adapters; o integrador constrói a UX por cima da API (a ferramenta não impõe painel).
Stack escolhida: **Typer** (CLI) + **FastAPI** (servidor de webhook)
Multi-engine via **adapters** (Claude Code é o engine de referência — ver §16).

---

## 1. Objetivo

Permitir que, a partir de um único binário/CLI instalado no servidor, o usuário:

1. **Registre repositórios como "instâncias"** reutilizáveis (repo + auth + config).
2. **Suba um servidor de webhook** que recebe POSTs genéricos e dispara o **engine** da
   instância (Claude Code, Codex, Gemini CLI, Aider, …) em modo **headless** dentro de um
   **container Docker isolado** por execução.
3. **Trate o resultado** de forma configurável: logs locais (sempre), retorno do output,
   callback/notificação externa e/ou commit + push + PR.

Modos de uso (prioridade):
- **P0 — Headless via webhook** (caso principal)
- **P1 — Interativo manual** (`run` que abre sessão no repo/instância)
- **P2 — Daemon persistente** (instância de longa duração recebendo tarefas)

---

## 2. Conceitos

### Instância
Unidade de configuração persistente. **Instância = repositório + auth + parâmetros**.
Registrada uma vez, reutilizada em N execuções (jobs).

Campos:
| Campo | Descrição |
|-------|-----------|
| `name` | Identificador único (slug). Usado na rota do webhook. |
| `engine` | Adapter do agente: `claude` (default) \| `codex` \| `gemini` \| `aider` \| … (ver §16). |
| `repo` | **Legado/opcional.** URL git (ssh/https) ou caminho local, um único repo. Mantido por compatibilidade; prefira `repos`. |
| `repos` | **Opcional. Pool de 0..N repositórios** que a instância conhece: lista de `{name, url, branch_base?}`. Cada job seleciona um subconjunto via `repos` no payload (omitido = todos, `[]` = nenhum). Os repos selecionados são clonados **lado a lado** no mesmo workspace (multi-checkout) — o agente lê/cruza todos; se mutar código, **cada repo alterado gera seu próprio branch/PR**. Em `analysis`/`action` os repos são contexto read-only; sem repos = tarefa pura via env (ver §20). |
| `deliverable` | Tipo de saída default: `analysis` \| `action` \| `patch` \| `commit` \| `pr` (ver §20). |
| `branch_base` | Branch base para checkout (default `main`). |
| `engine_auth` | Auth do **engine** com o provedor de IA: `api-key` \| `subscription` (§5). |
| `webhook_auth` | Auth do **endpoint** do webhook: `bearer`/`hmac`/`header`/`ip-allow` (§12). |
| `model` | Override de modelo opcional (passado ao engine). |
| `default_prompt` | Prompt/template padrão se o webhook não enviar um. |
| `on_result` | Ações de notificação/saída: `logs`, `output`, `callback`, `notify`. O destino do código (commit/PR/patch) é governado por `deliverable` (§20), **não** aqui. |
| `callback_url` | Destino default de notificação (sobrescrevível por job). |
| `pr_branch` | Template da branch de PR (default `agenthook/job-{id}`). |
| `limits` | Timeout, max tokens/turns, limite de concorrência. |
| `key_fingerprint` | Fingerprint da chave de criptografia imutável (a chave fica em `instance.key`). |

> Segredos (API key, `GH_TOKEN`, segredo HMAC do webhook) **não** ficam na instância em claro:
> são variáveis de ambiente cifradas em `env.enc` (ver §7). O segredo HMAC do webhook é uma
> variável reservada (ex.: `AGENTHOOK_WEBHOOK_SECRET`).
>
> A instância também carrega sub-blocos definidos em outras seções: `verify` (§18), `mcp`
> (§25), `schedules` (§28), `allow_overrides` (§11), `limits`, `secrets_backend` (§27).

### Session (thread)
Conversa durável atrelada a uma thread lógica (ticket/kanban), compartilhando contexto entre
vários jobs ao longo do tempo (§29). Chaveada por `thread_key`. Opcional: um job sem
`thread_key` é avulso (sem sessão).

### Job (execução)
Uma execução concreta (um turno) disparada por um webhook (ou manualmente). Efêmero.
Tem: `id`, `instance`, `prompt`, `container_id`, `workdir` (worktree/clone), `logs`,
`result`, `cost`, `session_id` (p/ resume), `error_class` (§17), timestamps.

**Máquina de estados do `status`:**
```
queued → running → {success | failed-checks | blocked | error | timeout | interrupted}
running → awaiting_approval → {approved→running | rejected | expired}   (modo plan, §19)
error(retryable) → queued (retry com backoff)  ·  terminal → DLQ
interrupted: job running cortado por restart (§31) — só read-only é re-enfileirado
```

---

## 3. Arquitetura

```
agenthook/
├── __init__.py
├── cli.py            # Typer: instance / env / serve / run / jobs / logs / usage / apply (§23)
├── tui.py            # pickers (questionary) + dashboard Textual (Fase 5) (§23)
├── config.py         # config global + agenthook.yaml declarativo / apply (§21)
├── instances.py      # CRUD do registro de instâncias (persistência)
├── store.py          # estado de jobs + uso/custo + audit log (SQLite) + fila (§24)
├── server.py         # FastAPI: webhook, auth (§12), aprovação (§19), /healthz /metrics
├── runner.py         # orquestra container Docker + executa o engine headless
├── engines/          # adapters multi-engine (claude, codex, gemini, …) (§16)
├── verify.py         # loop de verificação / self-heal (§18)
├── results.py        # normaliza saída/erro (§17), logs, callback, uso (§24)
├── git_ops.py        # worktree/clone, branch, commit, push, PR (gh) (§22)
├── secrets.py        # SecretsBackend: local-encrypted / env / plugin (§27)
├── channels/         # canais de aprovação/notificação (Slack ref.) (§19)
├── scheduler.py      # cron interno de jobs recorrentes (§28)
├── plugins.py        # carga de entry points: engines/channels/secrets/hooks (§26)
└── docker/
    └── Dockerfile    # imagem base: engine CLI + git + gh + runtime
```

### Layout em disco (estado no servidor)
```
~/.agenthook/
├── config.yaml                  # config global (porta, paths, defaults)
├── jobs.db                      # SQLite com histórico de jobs
├── instances/
│   └── <name>/
│       ├── instance.yaml        # config da instância (campos da §2)
│       ├── instance.key         # chave de criptografia imutável (auto-decrypt)
│       └── env.enc              # variáveis de ambiente cifradas
├── repos/<instance>/<repo>/     # clone "espelho" por repo do pool (atualizado por fetch)
├── work/<job_id>/               # workspace efêmero do job; em multi-repo cada repo vira <job_id>/<repo>/ (+ .agenthook/attachments/, §30)
├── sessions/<session_id>/       # volume persistente de sessão do engine (§29) — ~/.claude etc.
└── logs/<instance>/<job_id>.log
```

### Fluxo de um job (P0 — webhook headless)  *(exemplo com engine `claude` e deliverable `pr`)*
```
POST /hook/<instance>  (auth conforme §12)
   │
   ▼
server.py  → valida auth + resolve instância → persist-before-ack: cria Job (queued)
             no store → resolve sessão por thread_key (§29) → responde 202
   │
   ▼
runner.py  → git_ops cria worktree do job (+ monta volume de sessão, §29)
           → sobe container Docker efêmero:
                - monta worktree como /workspace (read-only se deliverable=analysis, §20)
                - injeta env cifrada decifrada (auth do engine + MCP, §7/§25)
                - roda o argv do engine (engine.build_argv, §16)
                  ex. claude: claude -p "<prompt>" --output-format stream-json --permission-mode ...
           → captura stdout/stderr/exit (streaming p/ log + SSE)
   │
   ▼
verify.py  → (deliverables de código) roda checks; self-heal até verde/limite (§18)
   │
   ▼
results.py → normaliza saída/erro (§16/§17) → grava log, uso/custo (§24)
           → deliverable=pr: git_ops branch+commit+push+PR (gh, §22)
           → on_result: callback (HMAC+seq, §31) / notify (canal, §19)
           → atualiza Job (success/failed-checks/blocked/error/…) no store
```

---

## 4. Superfície do CLI (rascunho)

```bash
# --- instâncias ---
agenthook instance add <name> [--repo <url|name=url> ...] [--branch main] [--engine claude|codex|...]
     [--engine-auth api-key|subscription] [--deliverable analysis|action|patch|commit|pr]
agenthook instance repo add|rm|list <name> [<name=url>] [--branch <base>]   # gerencia o pool (§2)
     [--model ...] [--on-result logs,output,callback,notify]
     [--callback-url ...] [--pr-branch "agenthook/job-{id}"]
# → ao criar, GERA e EXIBE UMA ÚNICA VEZ a chave de criptografia da instância.
#   O usuário deve guardá-la; ela fica salva em disco (auto-decrypt) e é imutável.
agenthook instance list
agenthook instance show <name>
agenthook instance rm <name>

# --- variáveis de ambiente da instância (cifradas com a chave da instância) ---
agenthook env set  <name> <KEY> <VALUE> [--secret]   # add/edit
agenthook env get  <name> <KEY>                       # secret → ofuscado
agenthook env list <name>                             # secret → ofuscado; demais → limpo
agenthook env rm   <name> <KEY>

# --- config declarativa (GitOps, §21) ---
agenthook apply [-f agenthook.yaml]                            # reconcilia instâncias

# --- servidor de webhook (P0) ---
agenthook serve [--host 0.0.0.0] [--port 8080] [--workers N]   # foreground (uvicorn embutido)
agenthook install-service [--port 8080] [--user daniel]        # gera/instala unit systemd
agenthook service {start|stop|status|logs}                     # controla o daemon

# --- configuração da instância ---
agenthook context  set <name> --file ./context.tmpl            # arquivo de contexto (§13)
agenthook auth     set <name> --scheme bearer|hmac|header|ip-allow [...]   # webhook (§12)
agenthook template set <name> <request_type> --file ./ticket.tmpl          # prompt (§14)
agenthook mcp      set <name> --file ./mcp.yaml                # servers MCP (§25)
agenthook verify   set <name> --checks "npm test" [...]        # loop de verificação (§18)
agenthook instance resume <name>                               # reativa após circuit breaker (§17)

# --- execução / teste manual ---
agenthook run     <name> --prompt "..."        # headless one-shot (P1)
agenthook run     <name> --interactive         # sessão interativa no container (P1)
agenthook dry-run <name> [...]                 # renderiza prompt/argv/env sem executar (§32)
agenthook send    <name> [...] [--wait]        # POST real no servidor local (§32)
agenthook send    --replay <job_id>            # reenvia um request passado (§32)

# --- jobs / sessões / observabilidade ---
agenthook jobs     list [--instance <name>] [--status running]
agenthook jobs     show <job_id>
agenthook sessions list [--instance <name>]    # threads ativas (§29)
agenthook logs     <job_id> [-f]
agenthook usage    [--instance <name>] [--requester ...] [--since ...]   # uso/custo (§24)
agenthook audit    [filtros] [--export csv|json]                         # audit log (§24)

# --- daemon (P2, futuro) ---
agenthook daemon start <name>
```

### Contrato do webhook (endpoint genérico)
`POST /hook/<instance>`

Headers (conforme esquema de auth da instância — ver §12):
```
Authorization: Bearer <token>             # ou header custom configurado
X-Agenthook-Signature: sha256=<hmac>      # se HMAC habilitado
Idempotency-Key: ticket-123               # opcional, deduplica reenvios
```

Body — **contexto enriquecido** (a app cliente manda dados; a instância monta o prompt):
```json
{
  "prompt": "corrige o bug de paginação em /users",   // opcional se houver template
  "thread_key": "ticket-123",                          // mesma chave → mesma sessão/contexto (§29)
  "request_type": "ticket",                            // ticket | workflow | kanban | custom
  "attachments": [                                     // opcional (§30)
    { "name": "erro.png", "type": "image/png", "inline_b64": "..." }
  ],
  "requester": { "name": "Daniel", "email": "daniel@example.com" },
  "answering_to": "Cliente X",                         // para quem a resposta se destina
  "language": "pt-BR",                                 // idioma da resposta
  "subject_ref": { "ticket_id": 123, "url": "https://..." },
  "priority": "high",
  "deliverable": "pr",                                 // analysis|action|patch|commit|pr (§20)
  "branch_base": "main",
  "callback_url": "https://meusistema/cb",
  "on_result": ["logs", "callback"],                   // notificação/saída (§2); código → deliverable
  "overrides": { "mode": "plan", "model": "..." },     // só se whitelisted (ver §11)
  "metadata": { "qualquer": "coisa" }
}
```

Resposta (async por default; `?wait=true` espera com timeout):
```json
{ "job_id": "j_ab12", "status": "queued", "stream_url": "/jobs/j_ab12/stream" }
```

---

## 5. Execução em Docker

- **Imagem base** própria (`docker/Dockerfile`): CLI do engine + git + gh + ferramentas.
  Pode haver uma imagem por engine (claude/codex/gemini/…) ou uma multi-engine.
- **Por job:** container efêmero (`--rm`), worktree montado em `/workspace` (read-only em
  `analysis`, §20), rede restrita conforme necessidade (egress p/ API do provedor + git remoto).
- **Auth do engine** (`engine_auth`, §2):
  - `api-key`: env do provedor (ex.: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …) — vinda das
    variáveis cifradas, resolvida por `engine.auth_env` (§16).
  - `subscription`: montar credenciais do engine (ex.: `~/.claude`) read-only. ⚠️ avaliar
    termos de uso para automação; opção explícita por instância.
  - **PR:** `-e GH_TOKEN=...` também das variáveis cifradas (se `deliverable` muta código).
  - Variáveis **decifradas em runtime** e injetadas; nunca em claro fora de `env.enc`.
- **Permissões do agente:** o adapter mapeia `mode` → flags do engine (§11/§16); em sandbox
  isolado pode usar o modo mais permissivo do engine; nunca fora do container.
- **Limites:** `--cpus`, `--memory`, timeout do job, kill ao exceder.

---

## 6. Concorrência e isolamento

- Clone "espelho" por instância em `repos/<instance>`, atualizado via `git fetch`.
- Cada job cria um **git worktree** (ou clone raso) próprio em `work/<job_id>` →
  runs paralelos no mesmo repo sem conflito.
- Limite de concorrência por instância (`limits`) + fila global no `store`.

---

## 7. Segredos e criptografia (definido)

Modelo de segredos por instância, baseado em **chave de criptografia imutável**:

- No `instance add`, gera-se uma **chave de criptografia** (ex.: Fernet/AES-256) única
  da instância. Ela é **exibida UMA ÚNICA VEZ** ao usuário (que deve guardá-la para
  recuperação) e fica **salva em disco**, **imutável** durante a vida da instância.
- As variáveis de ambiente da instância vivem num **arquivo cifrado** (`env.enc`) com essa
  chave. Quem ler o arquivo cru **não entende nada**.
- CRUD de variáveis via CLI (`env set/get/list/rm`). Cada variável tem flag `secret`:
  - `--secret` → ao listar/visualizar vem **ofuscado** (`API_KEY=••••••1f`).
  - sem `--secret` → exibido **em claro** (ex.: `LOG_LEVEL=debug`).
  - No disco, **tudo** fica cifrado independentemente da flag (a flag só controla exibição).
- **Storage da chave:** em disco, modo **auto-decrypt** (daemon decifra sozinho ao rodar).
  Threat model: protege contra leitura casual, commit acidental e vazamento em log;
  **não** protege contra disco totalmente comprometido (a chave está no servidor).
- Em runtime, as variáveis decifradas são injetadas como env no container do job
  (inclui `ANTHROPIC_API_KEY` e, se configurado, `GH_TOKEN` para abrir PR).

### Demais pontos de segurança
- Validação **HMAC** do corpo do webhook por instância (segredo de webhook guardado
  como variável `secret` da instância).
- Container sem privilégios, FS read-only exceto `/workspace`, egress limitado.
- Nunca logar segredos; redigir env no output de debug.

---

## 8. Decisões fechadas

| # | Tema | Decisão |
|---|------|---------|
| 1 | Persistência | **Instâncias em YAML**, **jobs em SQLite** (`jobs.db`). |
| 2 | Resposta do webhook | **Async (202 + callback)** por default; aceita **`?wait=true`** com timeout. |
| 3 | Segredos | Chave de criptografia **imutável por instância**, em disco (auto-decrypt); env vars cifradas com flag `secret` (ver §7). |
| 4 | Chave em runtime | **Em disco**, auto-decrypt (conveniência). |
| 5 | Git/PR | **`gh` CLI (GitHub)**; **branch configurável** (`pr_branch`, default `agenthook/job-{id}`); **`GH_TOKEN` vem das variáveis da instância**. |
| 6 | Empacotamento | **`pipx install agenthook`**. |
| 7 | Container | **Efêmero por job** (`--rm`). Pool quente fica para Fase 5. |
| 8 | Logs | **Arquivo + `logs -f`** **e** **endpoint HTTP/SSE** para streaming remoto. |
| 9 | Distribuição | **Open-source self-hosted**; multi-engine via adapters (§16). |
| 10 | Erros | Taxonomia normalizada + **circuit breaker** em `AUTH`/`QUOTA`; retry em worktree fresco (§17). |
| 11 | Timeout | **Não-retenta por default** (opt-in `retry_on_timeout`). |
| 12 | Verificação | Loop self-heal; **gate ligado quando `verify` existe**, overridable (§18). |
| 13 | Resume | **Volume de sessão persistente por thread** + fallback replay (§19). |
| 14 | Aprovação | API assinada (token HMAC single-use) + **conector Slack de referência** (§19). |
| 15 | Deliverable | Dimensão ortogonal ao mode: `analysis`/`action`/`patch`/`commit`/`pr`; **repo opcional**; read-only forçado em `analysis` (§20). |
| 16 | Config | **`agenthook.yaml` declarativo + `apply`** (GitOps), além do CLI imperativo (§21). |
| 17 | Concorrência repo | **Serializa por repo** em deliverables que mutam código; paralelismo por path opt-in; sem merge auto (§22). |
| 18 | CLI UX | **Leve agora** (Typer+Rich+questionary, pickers por seta); dashboard Textual na Fase 5 (§23). |
| 19 | Auditoria | Registro de uso/custo por job em SQLite + audit log; **retenção metadados+truncado** por default (§24). |
| 20 | MCP | **Primeira classe**: instância declara servers, creds via env cifrada; capability-gated (§25). |
| 21 | Extensibilidade | **Entry points** para engines/channels/secrets/hooks; hooks de ciclo de vida (§26). |
| 22 | Segredos backend | Interface plugável; **`local-encrypted` (default) + `env`**; Vault/KMS/sops via plugin (§27). |
| 23 | Cron | **Scheduler interno** de jobs recorrentes reusando o pipeline (§28). |
| 24 | Sessões | **Thread-key acha-ou-cria (default)** + open-then-post; FIFO por sessão; resume (§29). |
| 25 | Anexos | **Inline base64 + por referência (URL)**; imagens só em engines com visão (§30). |
| 26 | Entrega | Persist-before-ack + idempotency; **recovery re-enfileira só read-only**; callbacks at-least-once HMAC+seq (§31). |
| 27 | Teste CLI | **`dry-run`** (render sem executar) + **`send`/`--replay`** (POST real) (§32). |

---

## 9. Roadmap sugerido

- **Fase 1 (núcleo):** `runner.py` + adapter `claude` (§16) rodando o engine num container
  isolado + captura de saída/erro normalizada (§17) + `dry-run` (§32). Peça central, testável.
- **Fase 2 (gestão):** CLI `instance`/`env` + persistência + chave de criptografia (§7) +
  `SecretsBackend` local/env (§27) + deliverables `analysis`/`patch`/`pr` (§20).
- **Fase 3 (webhook):** `serve` FastAPI + auth (§12) + persist-before-ack/idempotency (§31) +
  store/fila (SQLite) + async `?wait` + logs SSE + auditoria de uso/custo (§24).
- **Fase 4 (resultado e fluxo):** callback HMAC+seq (§31) + git_ops/PR (§22) + verify self-heal
  (§18) + sessões por `thread_key` (§29) + templates/contexto (§13/§14).
- **Fase 5 (humano + extras):** aprovação plan→apply + canal Slack (§19) + MCP (§25) + cron
  (§28) + multi-engine adicional (§16) + dashboard Textual (§23) + daemon/interativo (P1/P2).

> Eixos transversais presentes desde cedo (não são "fases"): taxonomia de erros/circuit
> breaker (§17), capability matrix (§16), pontos de extensão/plugins (§26).

---

## 10. Servidor standalone / daemon

- **HTTP embutido (uvicorn)** — o `serve` sobe um servidor próprio na porta; **não depende**
  de Apache/nginx estar instalado. Pode opcionalmente ficar atrás de um reverse proxy, mas
  funciona sozinho.
- **`install-service`** gera e instala uma **unit systemd** (`agenthook.service`) para
  subir no boot e reiniciar em falha; `service start/stop/status/logs` controla o daemon.
- **Endpoints de infra:** `GET /healthz` (liveness), `GET /readyz` (Docker disponível,
  instâncias carregadas), `GET /metrics` (Prometheus opcional).
- **Roteamento por instância:** `POST /hook/<instance>` resolve a instância pelo path; 404
  se não existir; cada instância tem auth e fila próprias.

## 11. Modos de execução (instância + override por request)

> **Duas dimensões ortogonais:** `mode` (quão autônomo — abaixo) **×** `deliverable`
> (o que sai do job — §20). Ex.: `mode=auto` + `deliverable=analysis` = roda sozinho mas
> só produz um parecer, sem tocar no repo.

Configuráveis na instância, com **override por request apenas se whitelisted**:

| Campo | Valores | Mapeia para |
|-------|---------|-------------|
| `mode` | `auto` (automode) | aplica mudanças sozinho → `--permission-mode acceptEdits` (ou `bypassPermissions` em sandbox) |
| | `plan` (playmode) | gera plano **sem aplicar** → `--permission-mode plan`; ideal para preview/aprovação |
| | `default` | pede permissão (uso interativo) |
| `model` | id do modelo | `--model` |
| `max_turns` | inteiro | `--max-turns` |
| `allowed_tools` / `disallowed_tools` | listas | `--allowedTools` / `--disallowedTools` |
| `timeout` | segundos | kill do job |

- **Whitelist de overrides:** a instância declara `allow_overrides: [mode, model, ...]`.
  Um request só consegue mudar o que estiver na lista — evita que um POST force
  `bypassPermissions` indevidamente.
- **Fluxo plan→apply (dois caminhos):** (1) **programático** — a app recebe o plano no callback
  e dispara um segundo POST com `mode=auto` referenciando o `job_id`; (2) **humano** — aprovação
  via URLs assinadas / bot Slack (§19). Ambos reusam a sessão.

## 12. Proteção dos endpoints (auth configurável por instância)

A instância escolhe um ou mais esquemas (`auth set`):

- **`bearer`** — `Authorization: Bearer <token>`; token guardado como variável `secret`.
- **`header`** — header custom (nome+valor) definido pela instância (ex.: `X-API-Key`).
- **`hmac`** — assinatura `X-Agenthook-Signature: sha256=<hmac(body, secret)>`.
- **`ip-allow`** — allowlist de IPs/CIDRs.
- Combináveis (ex.: `bearer` + `ip-allow`). Falha de auth → `401`/`403`, sem vazar detalhe.
- **Rate limit** por instância (req/min) e **Idempotency-Key** para deduplicar reenvios.

## 13. Arquivo de contexto e configuração injetada no workspace

- **`agenthook context set <name> --file ...`** registra um **template de arquivo de
  contexto** por instância. Antes do run, ele é **renderizado e gravado no workspace com o
  nome que o engine espera** (ver §16):
  - `CLAUDE.md` (Claude), `AGENTS.md` (Codex/Cursor), `GEMINI.md` (Gemini),
    `CONVENTIONS.md` (Aider), `.goosehints` (Goose) — resolvido pelo adapter do engine.
  - O mesmo template serve para todos; só o **nome do arquivo de destino** muda.
- Interpolação no template:
  - **variáveis de ambiente** da instância (as não-secretas; secretas ficam de fora do texto),
  - **dados do request** (`requester.name`, `request_type`, `answering_to`, `language`, ...).
- Exemplo de template:
  ```
  Você atende solicitações via {{ request_type }}.
  Responda SEMPRE em {{ language }}.
  Solicitante: {{ requester.name }} — resposta destinada a {{ answering_to }}.
  Projeto: {{ env.PROJECT_NAME }}.
  ```
- **Configs extras injetáveis** por instância (quando o engine suporta): `.mcp.json`
  (MCP servers), `settings.json` (allowed tools, hooks), `.claude/` — copiados para o
  workspace antes do run. A capability matrix (§16) diz o que cada engine aceita.

## 14. Templating de prompt por tipo de solicitação

- **`template set <name> <request_type>`** define como montar o prompt final a partir do
  payload, por tipo (`ticket`, `workflow`, `kanban`, `custom`).
- Se o request manda `prompt` explícito, ele tem prioridade; senão usa o template do
  `request_type`. Permite que a app cliente envie **só dados estruturados** e a instância
  saiba enquadrar a tarefa.
- Exemplo (`ticket.tmpl`):
  ```
  Atenda o ticket #{{ subject_ref.ticket_id }} solicitado por {{ requester.name }}.
  Prioridade: {{ priority }}. Idioma da resposta: {{ language }}.
  Contexto: {{ metadata.description }}
  ```

## 15. Backlog (ainda não promovido a seção)

> Itens já promovidos: audit log → §24 · callbacks de progresso e assinatura → §31 ·
> retry/DLQ → §17/§31 · dashboard → §23.

- **Plan-preview com diff** — em `mode=plan`, retornar também o diff proposto (depende de
  dry-run do engine, §16).
- **Multi-tenant** — namespaces de instâncias por cliente/projeto (orgs, isolamento mais forte).
- **Billing** — relatórios de custo por requester/instância sobre a contabilidade do §24.
- **Conectores nativos** — GitHub App / Jira / Linear escutando e respondendo direto (via
  plugins, §26).
- **Runners remotos / fila distribuída** — escalar além de um único host (Redis/Celery, k8s).

---

## 16. Engines / abstração de provedor (multi-engine)

O `agenthook` é **agnóstico de agente**: a instância escolhe um `engine` e o resto do sistema
(webhook, modos, container, callback, contexto) permanece idêntico. Só o **adapter** muda.

### Interface do adapter
```python
class Engine(Protocol):
    name: str                       # "claude" | "codex" | "gemini" | "aider" | ...
    context_filename: str           # CLAUDE.md | AGENTS.md | GEMINI.md | CONVENTIONS.md | .goosehints
    capabilities: Capabilities      # plan_mode, json_output, mcp, resume, cost, allowed_tools
    def build_argv(self, job) -> list[str]: ...   # mapeia prompt/mode/model/tools → flags do CLI
    def parse_output(self, raw) -> Result: ...     # normaliza → {text, files_changed, cost, turns}
    def auth_env(self, instance) -> dict: ...      # nome das env vars de auth do provedor
```

### Mapeamento dos modos genéricos (§11) por engine
| Engine | headless | `auto` | `plan` | JSON | modelo | env de auth |
|--------|----------|--------|--------|------|--------|-------------|
| **claude** (ref.) | `claude -p "…"` | `--permission-mode acceptEdits` / `--dangerously-skip-permissions` | `--permission-mode plan` ✅ | `--output-format json\|stream-json` ✅ | `--model` | `ANTHROPIC_API_KEY` (ou Bedrock/Vertex) |
| **codex** | `codex exec "…"` | roda até concluir | ⚠️ sem plan nativo (degrada) | `--json` (JSONL) ✅ | `--model`/config | `OPENAI_API_KEY` |
| **gemini** | `gemini -p "…"` | `--yolo --non-interactive` | ⚠️ workaround | `--output-format json` ✅ | `-m` | `GEMINI_API_KEY` |
| **aider** | `aider -m "…" --yes` | `--yes` | `--dry-run`/architect | ⚠️ só texto (parse heurístico) | `--model` | varia (OpenAI/Anthropic/…) |
| **cursor** | `cursor-agent -p "…"` | `--force`/`--yolo` | ⚠️ | print mode | config | conforme provider |
| **opencode** | `opencode run "…"` | `--permissions` | ⚠️ | server/API | config | agnóstico |
| **goose** | `goose run -t "…"` | config | ⚠️ | parcial | config | agnóstico |

✅ suportado · ⚠️ ausente/parcial → a **capability matrix** avisa e faz degradação graciosa
(ex.: pedir `plan` num engine sem plan retorna aviso ou cai para dry-run equivalente).

### Princípios
- **Claude é o engine de referência** (implementado na Fase 1); os demais entram via adapter
  sem tocar no núcleo.
- Recursos não-universais (plan, JSON, MCP, resume, custo) são **declarados em `capabilities`**;
  o servidor valida o request contra elas e responde `422` se pedir algo indisponível.
- O **arquivo de contexto** (§13) é resolvido por `engine.context_filename`.
- Cada adapter declara **suas env vars de auth**, decifradas das variáveis da instância (§7).

---

## 17. Tratamento de erros e timeouts

Cada adapter mapeia as falhas do seu CLI (exit code, stderr, campo JSON) para uma
**taxonomia normalizada** (`error_class`):

| Classe | Exemplos | Retryable | Ação |
|--------|----------|-----------|------|
| `AUTH` | 401/403, key/OAuth expirado | ❌ | **Circuit breaker**: pausa a instância + notifica. |
| `RATE_LIMIT` | 429 | ✅ | Backoff exponencial + jitter, respeita `Retry-After`, re-enfileira. |
| `SERVER` | 500/502/503, overloaded | ✅ | Retry com backoff, máx N tentativas. |
| `QUOTA` | 402, créditos esgotados | ❌ | Circuit breaker + notifica. |
| `BLOCKED` | recusa de safety / content policy | ❌ | Status `blocked` + motivo (mesmo input → mesmo bloqueio). |
| `CONTEXT_LIMIT` | prompt grande demais | ❌ | Não retenta; sugere reduzir escopo. |
| `TIMEOUT` | estourou wall-clock | ❌ (default) | Mata container, status `timeout`. Não retenta (≈ agente travado). |
| `ENGINE_CRASH` / `BAD_OUTPUT` | exit ≠ 0, JSON corrompido | ⚠️ 1x | Retry único; captura stderr. |
| `UNKNOWN` | resto | ❌ | DLQ + log cru para inspeção. |

Princípios:
- **Circuit breaker por instância** em `AUTH`/`QUOTA`: parar de aceitar jobs e avisar, em vez
  de queimar toda a fila com erros idênticos. Instância volta com `instance resume`.
- **Retry sempre em worktree fresco** a partir do base — nunca reaproveita worktree com edição
  parcial (evita compor mudanças quebradas).
- **Resultado parcial preservado:** se o agente editou e a engine morreu no meio, o diff fica
  anexado ao job para inspeção, mas **nunca vira PR automático**.
- **Timeout não-retenta por default**; uma instância pode marcar jobs idempotentes como
  retentáveis (`retry_on_timeout: true`).
- **Callback sempre dispara** com `error_class` + mensagem redigida, para a app reagir.
- Política de retry (backoff, máx tentativas) é **configurável por instância**.

## 18. Loop de verificação (self-heal)

A instância pode definir um bloco `verify` com comandos executados **dentro do container**
após o agente terminar:
```yaml
verify:
  setup: "npm ci"                 # roda uma vez antes (instala deps)
  checks: ["npm test", "npm run lint", "npm run typecheck"]
  max_fix_iterations: 3
  max_fix_cost_usd: 1.00          # cap de custo do loop de correção
  gate: true                      # bloqueia PR se terminar vermelho (default: true se 'verify' existe)
```
Fluxo: roda os `checks` → se algum falha, **realimenta a saída (truncada/sumarizada)** para o
agente corrigir, até `max_fix_iterations` ou `max_fix_cost_usd`. Verde → segue para PR/commit;
vermelho com gate → status `failed-checks`, sem PR.

Decisões:
- **Aplica-se só a deliverables que mutam código** (`patch`/`commit`/`pr`); `analysis`/`action`
  não rodam checks (§20).
- **Gate default ligado quando `verify` existe**; overridable por instância e por request.
- **Realimentação:** via **resume de sessão** quando o engine suporta (mais barato), senão
  **prompt fresco** com diff + erro (fallback universal) — decidido pela capability do adapter.
- **Anti-loop:** cap de iterações **e** de custo; "**mesma falha 2× sem progresso → desiste**".
- **Saídas longas** de teste são truncadas/sumarizadas antes de voltar ao agente (contexto).

## 19. Humano no loop

### Aprovação de plano (plan → apply)
- `mode=plan` produz um plano (+ diff preview se o engine faz dry-run); job fica
  **`awaiting_approval`**.
- Servidor emite **tokens assinados (HMAC), single-use, com expiração** →
  `POST /jobs/{id}/approve|reject?token=...`. Aprovar enfileira o `apply` reusando a sessão;
  rejeitar encerra (motivo opcional realimenta um novo plano).
- **Canal de aprovação** é uma abstração plugável (como os engines): API assinada é a base,
  com **conectores prontos** (ex.: bot de chat com botões approve/reject) por cima.

### Iteração por comentário (resume)
- Caso particular de **Sessões (§29)**: uma thread externa (PR/ticket) é a `thread_key`; novo
  comentário = novo POST no mesmo hook = novo turno continuando a sessão. Detalhes em §29.

### Persistência de sessão vs container efêmero  *(decisão)*
- **Volume persistente por sessão (opção a):** o container de trabalho continua **efêmero**
  (FS de trabalho descartável), mas monta um **volume por thread** contendo apenas o **estado
  de sessão do engine** (`~/.claude`, `~/.codex`, …), keyed por `session_id`.
- **Fallback stateless/replay** quando o engine não tem `resume`: reconstrói contexto via
  diff + histórico no prompt.
- Mapeamento `thread_key (ticket/PR) → session_id` vive na store (SQLite).

### Notificações / canais  *(abstração plugável)*
```python
class ApprovalChannel(Protocol):
    name: str                                  # "slack" | "discord" | "telegram" | "webhook"
    def request_approval(self, job, approve_url, reject_url): ...
    def notify(self, job, event): ...          # started | finished | error | blocked
```
Base = API assinada + HTML mínimo opcional; **o conector de referência é o Slack** (Block Kit
com botões approve/reject); Discord/Telegram/webhook entram via adapter da mesma interface.

---

## 20. Tipos de deliverable (saída do job)

Dimensão **ortogonal** ao `mode` (§11). Nem todo job edita código — alguns só analisam,
leem dados ou executam ações externas. A instância define um `deliverable` default,
sobrescrevível por request (se whitelisted):

| `deliverable` | Muta o repo? | Perfil de tools | Saída | Exemplo |
|---------------|--------------|-----------------|-------|---------|
| `analysis` | ❌ read-only | **só leitura** (edit/write proibidos) | texto/JSON via return+callback | "analise essa interação e dê um parecer" |
| `action` | ❌ no repo (efeitos externos via tools/MCP) | conforme allowlist | resumo do resultado | "leia o banco via env e responda X" |
| `patch` | ✏️ local, sem push | leitura+edição | artefato `.diff` anexado | "gera o patch, não dá push" |
| `commit` | ✅ push de branch | leitura+edição | branch | — |
| `pr` | ✅ push + abre PR (§ git_ops) | leitura+edição | PR | "corrige o bug e abre PR" |

Princípios:
- **Repo opcional.** `analysis`/`action` podem rodar com repo como **contexto read-only** ou
  **sem repo** (workspace vazio + credenciais via env). `patch`/`commit`/`pr` exigem repo.
- **Env vars como contexto de tarefa.** As variáveis cifradas (§7) não são só auth do engine:
  alimentam **credenciais de banco, endpoints, tokens** que o agente usa via tools/MCP em
  `action`. Decifradas em runtime, injetadas no container, nunca em claro fora de `env.enc`.
- **Read-only forçado em `analysis`.** Segurança não é só "não dar push" — é **desabilitar
  tools de escrita/edição** (governança, §17/D). O sandbox monta o repo read-only.
- **Gate de verificação (§18) só vale para `patch`/`commit`/`pr`.** `analysis`/`action` não
  rodam checks de código.

## 21. Config declarativa (GitOps) — opcional

Além do CLI imperativo (`instance add ...`), suportar um **`agenthook.yaml` declarativo** que
descreve todas as instâncias e pode ser **commitado num repo de config**:
```yaml
instances:
  suporte-tickets:
    engine: claude
    repo: git@github.com:acme/app.git
    deliverable: analysis
    auth: { scheme: bearer }
    on_result: [logs, callback]
  bugfix-bot:
    engine: claude
    repo: git@github.com:acme/app.git
    deliverable: pr
    verify: { checks: ["npm test"], gate: true }
```
- **`agenthook apply [-f agenthook.yaml]`** reconcilia o estado (cria/atualiza/remove
  instâncias). CLI imperativo continua como açúcar para uso rápido.
- **Segredos não vão no YAML** — só referências; valores via `env set` (cifrado, §7) ou
  injeção por env do processo. Mantém o arquivo seguro para versionar.

## 22. Concorrência no repositório

Worktree por job isola a **execução**, mas dois jobs editando o mesmo arquivo geram conflito
no merge. Política:
- **Serializa por repo (default):** fila por instância/repo para deliverables que mutam código
  (`patch`/`commit`/`pr`). Simples e seguro.
- **Paralelismo por path (opt-in avançado):** jobs que tocam áreas disjuntas rodam em paralelo.
- **`analysis`/`action` nunca serializam** (read-only) — rodam totalmente em paralelo.
- **Sem merge automático** — conflito real vira PR para humano resolver. Merge auto é cilada.

---

## 23. Interface do CLI (UX)

Dois níveis, sempre:
- **Comandos secos (Typer):** não-interativos, para automação/CI. Nenhum fluxo essencial
  depende de TUI (servidor/cron nunca travam esperando input).
- **Modo amigável:** `agenthook` sem args cai num **menu navegável por setas**; comandos com
  argumento omitido abrem um **picker** (ex.: `agenthook logs` → lista de jobs recentes;
  `agenthook run` → escolhe instância na seta).

Stack de UX:
- **Rich** — tabelas/painéis, status colorido, custo inline.
- **questionary / prompt_toolkit** — pickers, multi-select, autocomplete.
- **Textual** — dashboard ao vivo (`agenthook tui`): instâncias + stream de jobs + logs SSE +
  approve/reject na tela. **Fase 5** (cliente fino sobre store+SSE — sem retrabalho).

Decisão: **leve agora** (Typer+Rich+questionary), **dashboard Textual depois**. A camada de
dados (store/SSE) é desenhada primeiro para o TUI ser só uma view.

## 24. Auditoria e contabilidade de uso/custo

Cada adapter normaliza o uso reportado pelo engine num **registro único por job**:
```
{ input_tokens, output_tokens, cache_read, cache_write, cost_usd,
  num_turns, model, duration_s }   # inclui o custo do loop de verificação (§18)
```
- **Persistido em SQLite** (`jobs.db`), consultável por **instância / requester / request_type
  / engine·modelo / deliverable / período**.
- **Audit log append-only:** quem (requester), quando, instância/engine, **hash do prompt**,
  deliverable, status, `error_class`, custo, link do PR. Base de confiança (OSS) + custo.
- **Comandos:** `agenthook usage` / `agenthook audit` (filtros + export CSV/JSON). Alimenta
  `/metrics` (Prometheus) e os **caps de custo** do circuit breaker (§17).
- **Retenção (default): metadados + truncado** — guarda uso/custo/hash e trechos truncados;
  prompt/saída completos só se o operador habilitar. Configurável por instância.
- **Honestidade:** engine sem token reporting (ex.: Aider) → `cost: unknown`, nunca estimativa.

## 25. MCP de primeira classe

A instância declara servers MCP; injetados como `.mcp.json` no workspace antes do run, com
**credenciais vindas das variáveis cifradas (§7)** — o caminho limpo para o deliverable
`action` (ex.: ler banco) sem bash ad-hoc:
```yaml
mcp:
  postgres:
    command: "mcp-server-postgres"
    env: { DATABASE_URL: "{{ env.DATABASE_URL }}" }   # decifrado em runtime
  http-api:
    url: "https://api.interno/mcp"
    headers: { Authorization: "Bearer {{ env.API_TOKEN }}" }
```
- **Capability-gated:** engines sem MCP degradam (agente usa tools/bash). A matrix (§16) diz.
- Segredos nunca aparecem em claro no `.mcp.json` logado — interpolados só no container.

## 26. Plugins / extensibilidade (entry points)

Alavanca de comunidade do OSS. Pontos de extensão carregáveis de pacotes pip externos via
`importlib.metadata` entry points — **sem fork**:
| Grupo | Estende |
|-------|---------|
| `agenthook.engines` | novos adapters de engine (§16) |
| `agenthook.channels` | canais de aprovação/notificação (§19) |
| `agenthook.secrets_backends` | backends de segredo (§27) |
| `agenthook.hooks` | hooks de ciclo de vida do job |

**Hooks de ciclo:** `pre_run(job)`, `post_run(job, result)`, `on_result(job, result)`,
`on_error(job, error)` — para enriquecer prompt, validar guard-rails, notificar, etc.
Definir os grupos **cedo**, mesmo enviando poucas implementações de fábrica.

## 27. Backend de segredos plugável

A criptografia local (§7) vira o **default zero-config**, mas atrás de uma interface:
```python
class SecretsBackend(Protocol):
    name: str                      # "local-encrypted" | "env" | "vault" | "aws-kms" | "sops"
    def get(self, instance, key) -> str | None: ...
    def set(self, instance, key, value, secret: bool): ...
    def list(self, instance) -> list[EnvVar]: ...     # secretos ofuscados
```
- **`local-encrypted`** (default): chave imutável por instância, `env.enc` (§7).
- **`env`**: lê do ambiente do processo / `.env` (bom para containers/12-factor).
- **`vault` / `aws-kms` / `sops`**: para self-hosters com gestão de segredos própria — entram
  via entry point (§26). Desenhar a costura agora, implementar `local`+`env` primeiro.

## 28. Gatilhos agendados (cron)

Além do webhook, a instância pode declarar **jobs recorrentes** para manutenção autônoma:
```yaml
schedules:
  - name: bump-deps
    cron: "0 3 * * 1"            # seg 03:00
    deliverable: pr
    prompt: "Atualize dependências seguras e abra PR."
  - name: scan-todos
    cron: "0 6 * * *"
    deliverable: analysis
    prompt: "Liste TODOs antigos e riscos."
```
- Scheduler interno no daemon dispara o mesmo pipeline de job (reusa runner/verify/auditoria).
- Respeita concorrência (§22), caps de custo (§17/24) e governança como qualquer job.

---

## 29. Sessões (threads de múltiplas interações)

Um ticket de suporte ou item de kanban tem **várias interações ao longo do tempo** que devem
**compartilhar contexto**. A **Session** é um conceito de primeira classe:

- **Session** = conversa durável atrelada a uma thread lógica. Campos: `session_id`,
  `instance`, `thread_key`, `status` (open/active/idle/closed), histórico de jobs, e o
  **volume de sessão persistente** (§19) com o estado do engine.

**Roteamento (dois modos):**
- **Implícito por `thread_key` (default):** `POST /hook/<instance>` com `thread_key:"ticket-123"`
  → o servidor **acha-ou-cria** a sessão daquela chave. A app não precisa guardar `session_id`;
  o id do próprio ticket é a chave. *"Tudo que fizer POST nesse hook é do mesmo contexto."*
- **Explícito open-then-post:** `POST /hook/<instance>/sessions` abre e devolve `session_id` +
  URL dedicada `…/sessions/<id>`; cada POST ali é um novo turno.

**Regras:**
- **Cada POST = um turno** que **resume** a sessão (capability `resume`; fallback replay, §19).
- **Serializa por sessão (FIFO):** dois turnos da mesma conversa nunca rodam em paralelo.
- **Ciclo de vida:** open → active → idle (TTL) → closed (explícito via `close`, ou auto após
  inatividade; fechar pode gerar um resumo). Volume limpo no close conforme retenção (§24).
- **Cross-deliverable:** a sessão pode ter turnos `analysis` e depois um turno `pr`.
- **Crescimento de contexto:** tickets longos crescem o contexto → conta com a compactação do
  próprio engine; opcionalmente sumariza/trunca turnos antigos (capability-dependent).
- Mapeamento `thread_key → session_id` vive na store (SQLite).

## 30. Anexos no request

O payload pode trazer anexos (imagem, stack trace, log, arquivo) — forte para `analysis`:
```json
"attachments": [
  { "name": "erro.png", "type": "image/png", "inline_b64": "..." },
  { "name": "app.log", "url": "https://.../app.log", "headers": { "Authorization": "..." } }
]
```
- **Dois modos:** **inline base64** (pequenos) **e por referência** (URL que o runner baixa,
  com header de auth opcional); multipart para upload via CLI.
- **Destino:** gravados em `/workspace/.agenthook/attachments/` e referenciados no
  prompt/contexto. **Imagens** vão ao engine se ele tem **capability de visão** (§16); senão,
  aviso/fallback. **Texto** (logs/traces) entra como contexto textual.
- **Caps por instância:** máx. quantidade, tamanho por arquivo e total, tipos permitidos.
  Nunca executar anexo. Retenção segue §24 (default truncado/metadados).

## 31. Garantia de entrega

**Inbound (recebimento do webhook):**
- **Persist-before-ack:** grava o job durável no SQLite **antes** de responder `202` — crash
  após o ack não perde o trabalho.
- **Idempotency-Key (dedup):** mesma chave → retorna o job existente, não duplica.
- **Fila durável:** jobs sobrevivem a restart; no boot, `queued` é recuperado.
- **Jobs `running` interrompidos por restart:** **re-enfileira apenas `analysis`/`action`**
  (read-only, seguro); `pr`/`commit`/`patch` viram **`interrupted`** para inspeção (evita
  reaplicar mudança parcial).
- Payload acima do limite → `413`.

**Outbound (callbacks):**
- **At-least-once** com **retry + backoff + DLQ** de callbacks; **HMAC-assinado**; **número de
  sequência** por job (eventos `started → progress → finished/error` em ordem).
- Receiver deve ser **idempotente** (`job_id` + `event_id`).

## 32. Ferramentas de teste no CLI (DX)

- **`agenthook dry-run <instance> [...]`** — renderiza **tudo sem executar engine/container**:
  prompt final (template §14), arquivo de contexto (§13), **env resolvida com segredos
  mascarados**, config MCP (§25), **argv do engine** (§16), guard-rails aplicáveis e **custo
  estimado**. Ideal para depurar templates/auth.
- **`agenthook send <instance> [...] [--wait]`** — faz o **POST real** pelo servidor local,
  exercitando auth/HMAC/fila/deliverable ponta a ponta.
- **`agenthook send --replay <job_id>`** — reenvia um request passado para reproduzir.
- **Builder interativo** (questionary, §23) para compor o payload por setas.

## 33. Management API (control-plane HTTP)

Toda a configuração — historicamente só via CLI — é também exposta sobre HTTP sob `/admin/*`,
para gerenciar o agenthook a partir de um app/painel, não só do terminal. É uma casca fina
sobre a mesma camada de negócio que o CLI usa (`instances.*`, `secrets.*`, `config.*`), com
modelos pydantic apenas na borda; a validação autoritativa segue em `Instance.validate()`.

**Proteção (dois portões, ambos obrigatórios).**
- **Rede:** por padrão só responde a clientes **loopback**; acesso remoto é opt-in explícito
  (`admin_remote: true` em `config.yaml`).
- **Token:** **bearer** comparado em tempo constante — `AGENTHOOK_ADMIN_TOKEN` (env) ou
  `config.admin_token` (auto-gerado, como o `approval_secret`).

**Superfície.** Instances CRUD + pause/resume; sub-recursos `repos`, `auth` (webhook),
`verify`, `mcp`, `context` (CLAUDE.md), `templates`, `guardrails`, `skills`; `env` encriptada;
`config` global; e leituras de `jobs`/`sessions`/`usage`/`audit`. OpenAPI em `/docs`.

**Segredos nunca em claro.** Valores `env` marcados como `secret` voltam **mascarados**
(`secrets.obfuscate`); não há rota que devolva o valor pleno. O `config` mascara `admin_token`
e `approval_secret`.

**Guardrails são append-only / hardening-only.** O guardrail global do operador (§ runner) é um
**piso inviolável**: o overlay de instância (`guardrails.extra`, `guardrails.force_read_only`)
só **adiciona** regras ou **endurece** — nunca desliga um bloco de segurança. Na montagem do
system prompt o addendum da instância vem **antes** e a baseline global **por último** (e a
baseline já se declara não-sobreponível), então um addendum não consegue afrouxá-la. Chaves de
afrouxamento são rejeitadas na validação (`422`). Afrouxamento real ficaria atrás de uma flag
global explícita (`allow_guardrail_relaxation`), fora do escopo atual.

**Skills (novo conceito).** Uma instância declara `skills` (nome → corpo de `SKILL.md`),
entregues no workspace em `<engine.skills_dir>/<name>/SKILL.md` (Claude Code: `.claude/skills`)
no mesmo ponto onde CLAUDE.md e `.mcp.json` são materializados. Engines anunciam suporte via
`capabilities.skills` + `Engine.skills_dir`.

## 34. Painel web (React + shadcn/ui)

Um SPA em `web/` consome a Management API (§33) como alternativa de UI ao CLI/`curl`.
Stack: Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query + React Router +
CodeMirror. **Herda a identidade do design-system** (paleta âmbar sobre near-black, JetBrains
Mono e o vocabulário de status glyph+cor de `agenthook/tui.py` — o `StatusBadge` replica o
mapeamento exato).

**Integração.** Em dev, o Vite proxia `/admin`/`/jobs`/`/healthz` para o backend (mesma origem,
sem CORS). Em produção, `npm run build` emite para `agenthook/static/panel/` e o FastAPI
(`server.py:_mount_panel`) serve o build em **`/ui`** quando presente — mesma origem do `/admin`,
montado depois das rotas de API (que têm precedência). O artefato é gitignorado e incluído no
wheel via `[tool.hatch.build.targets.wheel] artifacts`.

**Auth.** Tela de login cola o admin token (§33), guardado em `sessionStorage` e enviado como
`Authorization: Bearer`. O gate loopback exige rodar em localhost; o login orienta sobre
`admin_remote` para acesso remoto. O stream ao vivo de jobs usa `EventSource` direto em
`/jobs/{id}/stream` (endpoint público — `EventSource` não envia headers).

**Cobertura.** Dashboard; Instances (CRUD + abas config/repos/env/auth/verify/mcp/CLAUDE.md/
guardrails/skills, com a modal de chave única na criação e a UI de guardrails reforçando o
modelo append-only); Jobs + viewer de stream; Sessions; Usage/Audit; Config global (segredos
mascarados). *Templates por-request_type* ficam como follow-up.
