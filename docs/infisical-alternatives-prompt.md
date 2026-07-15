# Prompt de pesquisa — alternativas ao Infisical

> Para colar numa conversa nova do Claude e comparar alternativas de gerenciador de
> segredos para o Agenthook. Contexto: ver [`security-and-secrets.md`](./security-and-secrets.md) §3.
> O eixo decisivo é **dynamic DB secrets self-hosted, grátis/barato** — onde o Infisical
> falhou (só no tier Enterprise). Contrataria uma solução dedicada só ao Agenthook.

```
Preciso escolher um gerenciador de segredos para um caso específico e quero
alternativas comparadas. Contexto e requisitos abaixo — me traga opções (incluindo
as que eu não listei), uma tabela comparativa e uma recomendação final justificada.

## O que estou construindo
Um "task runner" self-hosted de agentes de código (estilo Agenthook): recebe webhooks
do meu sistema (tickets de suporte e cards de kanban) e roda um agente de IA num
container Docker isolado, UM container/instância por projeto. Sou um único operador
com MULTI-PROJETOS (hoje penso em algo entre 5 e 20 projetos). Quero contratar/pagar
uma solução de segredos DEDICADA a esse task runner apenas — não para uma empresa
inteira, então preço por-seat ou por-identity que escala com nº de projetos é ruim.

## O problema central (o que a solução PRECISA resolver)
O agente dentro do container usa credenciais reais (GitHub token, credenciais de banco
de produção/staging, API keys de terceiros). O risco nº1 é PROMPT INJECTION via o
conteúdo do ticket/card (texto controlado pelo atacante) fazendo o agente exfiltrar
segredos. A verdade dura: um segredo que o agente USA, ele pode ser induzido a VAZAR.
Então preciso MINIMIZAR o valor de um segredo vazado e o raio de explosão.

## Requisitos obrigatórios (must-have)
1. Self-hostável na minha infra (Docker), ou muito barato para single-tenant.
2. DYNAMIC SECRETS / credenciais de vida curta para BANCO DE DADOS (Postgres/MySQL):
   gerar credencial temporária por job com TTL de minutos e auto-revogar. Este é o
   ponto decisivo — o Infisical só oferece isso no tier Enterprise (pago, "contact
   sales"); o HashiCorp Vault OSS oferece de graça. Quero mapear quem oferece isso
   grátis/barato self-hosted.
3. Isolamento por projeto: credencial/identidade de máquina por projeto, de forma que
   comprometer o projeto A não dê acesso aos segredos do projeto B.
4. Acesso via machine identity / token de máquina (sem humano no loop para o runtime),
   com API/CLI para o host resolver segredos no início de cada job.
5. Custo previsível e baixo para um operador solo multi-projeto (evitar preço por
   identity que multiplica pelo nº de projetos).

## Desejável (nice-to-have)
- Rotação automática de segredos estáticos.
- Auditoria de acesso a segredo (quem/quando/qual).
- Suporte a credencial dinâmica também para outros alvos (AWS, cloud APIs).
- Integração fácil como "secret backend" plugável (o runner tem uma interface de
  backend de segredos; um backend novo é get/set/list/delete via API).
- Licença open-source permissiva de preferência.

## Fora de escopo
Não preciso de SSO/SAML/LDAP corporativo, SCIM, nem UI de aprovação corporativa — o
runner já tem seu próprio fluxo de aprovação humano (plan→apply) e seu próprio gateway
que mantém API keys HTTP fora do container.

## Candidatos que já conheço (avalie e vá além)
HashiCorp Vault OSS, OpenBao (fork do Vault), Infisical, Doppler, Akeyless, CyberArk
Conjur OSS, AWS Secrets Manager, GCP Secret Manager, Pomerium, Teleport Machine ID,
Boundary. Me diga quais têm DYNAMIC DB SECRETS grátis/self-hosted, quais cobram, e o
custo real para o meu cenário.

## Formato da resposta
1. Tabela: solução × (dynamic DB secrets self-hosted grátis? | isolamento por projeto |
   modelo de custo | licença | esforço de operação | maturidade).
2. Top 3 recomendações com prós/contras para o MEU caso específico.
3. Recomendação final + o que eu perderia escolhendo a mais simples vs a mais completa.
```
