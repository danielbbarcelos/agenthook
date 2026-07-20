# Segredos & credenciais de banco no Agenthook — decisão

> Registro de decisão. Autossuficiente. Companheiros:
> [`product-plan.md`](./product-plan.md) e
> [`security-and-secrets.md`](./security-and-secrets.md).
> Última revisão: 2026-07-20.

## 0. Decisão (o que fica)

**Nenhuma mudança arquitetural.** O Agenthook já cobre o caso de credenciais de
banco. A regra é:

- Segredos vivem no store nativo do Agenthook: **SQLite + Fernet** (`env.enc` por
  instância). É a metade "guardar" do OpenBao, feita local. Já existe.
- A **credencial de banco é um secret comum da instância**. O operador faz
  `agenthook env set <inst> DATABASE_URL <cred>`; `resolve_env()` injeta como env
  var no container do job; **o agente lê do env, conecta e roda SQL**. Nunca via
  arquivo — a credencial é sempre para o agente usar.
- A credencial pode ser **read-only OU de escrita** — **escolha do operador** ao
  criar o role no Postgres. Não é um knob do Agenthook; é provisionamento no banco.
- O **banco é sempre remoto**, nunca no host do Agenthook. O Agenthook não instala
  nem hospeda Postgres.

## 1. Descartado

- **OpenBao (e Vault/Infisical):** desnecessário. A metade "store" já é nativa
  (SQLite+Fernet); a metade "dynamic secret" (credencial efêmera) não paga o custo
  para este uso. Reabrir só se virar multi-operador/multi-tenant real (aí o
  isolamento forte por AppRole/namespace passa a valer).
- **M5 — credencial de banco efêmera (mint host-side + `db_lease.py` + `psycopg`):**
  descartado como caminho padrão. Fica como **opção futura** apenas para
  time-boxar uma credencial **de escrita** por compliance. Não é necessário: a
  credencial que o operador guarda já pode ser um role read-only (ou de escrita
  escopado), e isso resolve sem código novo.

## 2. Camadas de segurança que já existem (nada a construir)

| Controle | Onde | O que faz |
|---|---|---|
| `guardrails.force_read_only` | `instances.py`, `runner.py:502` | trava de **ferramentas** (não de SQL): remove `Bash`/`Edit`/`Write`/`NotebookEdit`, restringe a `Read`/`Grep`/`Glob`/`LS`. Ver §4 — não é um switch "SQL só-leitura" |
| Guardrail anti-destruição | `runner.py:435-439` | bloqueia `DROP DATABASE/SCHEMA`, `TRUNCATE`, `DELETE/UPDATE` sem `WHERE` (ou `1=1`) |
| Egress allowlist por instância | `egress_allow()`, `runner.py:632` | container só alcança o host do banco declarado — sem exfiltração para fora |
| Exclusão control-plane | `secrets.is_agent_visible()`, `secrets.py:199` | segredos `AGENTHOOK_*` (ex.: auth de webhook) nunca entram no container |

**Verdade aceita:** o segredo que o agente USA, um agente vítima de
prompt-injection VAZA. Como a credencial de banco *tem* que ir ao agente, a defesa
não é escondê-la — é **egress lockdown** (não sai do host do banco) + **escopo
mínimo do role** (o operador decide o poder) + **guardrail anti-destruição**.

## 3. Limitação honesta — credencial de escrita

Com credencial **de escrita**, o agente roda `INSERT/UPDATE/DELETE` **ao vivo
durante o job**, e isso **não** passa pelo plan→apply (o plan→apply do M1 coage
deliverables de **código/PR**, não SQL ao vivo). A rede de proteção para escrita é:
guardrail anti-destruição + egress lockdown + **o operador escopar o role de
escrita ao mínimo** (schema/tabelas específicos). É risco consciente da escolha
"credencial de escrita" — não há gate humano por query.

Se algum dia isso não bastar, o M5 efêmero (§1) ou um gate plan→apply para SQL
mutante entram como extensão — mas nenhum é necessário para o uso atual.

## 4. Read-only por padrão, escrita só com autorização explícita

Objetivo: priorizar leitura, mas permitir escrita quando o usuário autorizar
explicitamente na conversa. Isso tem **duas camadas** — e a soft já existe.

### O que `force_read_only` NÃO é

Não é um switch "SQL lê mas não escreve". É trava de **ferramentas** (`base.py:145`):
remove `Bash`/`Edit`/`Write`/`NotebookEdit` e restringe a `Read`/`Grep`/`Glob`/`LS`.
Efeito no banco é grosseiro e depende do caminho de acesso:

- **Via `Bash`+`psql`:** mata o caminho **inteiro** — inclusive a leitura (sem
  `Bash`, não roda `psql` nem para `SELECT`). É "sem banco por shell", não "banco
  só-leitura".
- **Via ferramenta MCP de banco:** `force_read_only` **não** toca no MCP; aí
  read/write dependem da capability do MCP + do privilégio da credencial.

### A política que você quer JÁ existe (soft, zero código)

O baseline do guardrail (`runner.py:435-442`) já codifica exatamente isto:

- **Regra 9** — nunca destrutivo em massa (`DROP`/`TRUNCATE`/`DELETE`/`UPDATE` sem `WHERE`).
- **Regra 10** — mudanças pontuais (`UPDATE`/`DELETE` com `WHERE` limitado, `ALTER`,
  migrations) permitidas **APENAS quando o usuário pede explicitamente e nomeia o
  objeto**; usar transação e declarar o escopo antes.

Ou seja: com uma credencial **de escrita**, o agente por padrão **não escreve**
(postura de leitura pela regra 10) e só escreve quando você, na conversa, **pede
explícito e nomeia** o alvo.

### Reforçar a postura padrão por instância (config, não código)

Via `guardrails.extra` (o campo que **só adiciona** restrição, `runner.py:478`):

```yaml
guardrails:
  extra: >
    Trate o banco como somente-leitura por padrão. Só execute escrita
    (INSERT/UPDATE/DELETE/DDL) depois que o operador, nesta conversa,
    autorizar explicitamente a mudança específica e nomear o objeto.
```

### O teto hard é a credencial

Tudo acima é **soft** (nível de prompt): o agente *obedece* a política. O teto
**hard** é o **privilégio do role** — o Postgres é quem recusa de fato. Uma
credencial estática **não pode** ser "hard read-only" e escalar para escrita no
meio da conversa (privilégio de role é fixo). Um "hard" com escalonamento exigiria
**duas credenciais** (RO default + escrita sob autorização) + seletor — que é o
M5/dinâmico (§1), deliberadamente evitado. Regra prática: se o dano de uma escrita
indevida for inaceitável, use **credencial read-only** (teto hard); se escrita for
esperada, use credencial de escrita **escopada ao mínimo** + a política soft acima.

## 5. Ação do operador (não é código)

- Criar o role no Postgres com o privilégio desejado (read-only por padrão; de
  escrita escopado onde necessário) e guardar a credencial via
  `agenthook env set <inst> DATABASE_URL ... --secret`.
- Adicionar o host do banco ao egress allowlist da instância.
- Para reforçar a postura read-only-por-padrão, ver §4 (`guardrails.extra`).
  Nota: `guardrails.force_read_only` é trava de ferramentas (§4), não um switch de
  SQL — não confie nele como controle de escrita no banco.
