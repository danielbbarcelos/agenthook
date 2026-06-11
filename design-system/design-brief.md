# agenthook — design brief (prompt para o Claude Design)

> Cole o bloco abaixo no Claude Design. Ele pede que a ferramenta primeiro
> **entreviste** você e só depois produza o design da TUI. O ponto crítico é
> deixar explícito que o alvo é uma **interface de terminal em Python** (não
> web/React) — caso contrário o entregável vem como componentes web inúteis aqui.

---

```
Quero que você me ajude a (re)desenhar a interface de um aplicativo de TERMINAL
(TUI), não uma web app. Antes de propor qualquer coisa, me ENTREVISTE com
perguntas objetivas até ter clareza suficiente; só então produza o design.

## Restrição de meio (importante)
- O alvo é uma interface de LINHA DE COMANDO / TUI rodando no terminal.
- Stack: Python — Typer (comandos), Rich (tabelas/painéis/cores ANSI),
  questionary (menus navegáveis por seta, prompts, confirmações). Há intenção
  de evoluir para um dashboard ao vivo com Textual numa fase futura.
- Portanto o ENTREGÁVEL não são componentes React/HTML. Quero:
  (1) mockups em ASCII/monoespaçado de cada tela,
  (2) o mapa de navegação (árvore de menus e transições),
  (3) hierarquia de informação e o que cada tela mostra,
  (4) paleta de cores ANSI e estilos (estados: ok/erro/aviso/muted/destaque),
  (5) microcopy (textos das opções, mensagens, confirmações) — em inglês,
  (6) padrões de interação no terminal (setas, Enter, atalhos, voltar/sair).

## O que é o produto
"agenthook" — um runner de tarefas agênticas self-hosted. A partir de um único
CLI instalado no servidor, o usuário registra "instâncias" (repositório + auth +
config) e sobe um servidor de webhook que dispara um "engine" de coding agent
(Claude Code como referência; também Codex, Gemini, Aider, …) em modo headless,
dentro de um container Docker isolado por execução. Cada execução é um "job".
Tarefas podem ser puramente analíticas (read-only) ou mutar código (abrir PR).

## Conceitos centrais (vocabulário da interface)
- Instância: unidade de config persistente = repo(s) + engine + auth + parâmetros.
  Campos: engine, engine_auth (subscription | api-key), deliverable padrão
  (analysis | action | patch | commit | pr), branch base, model opcional,
  pool de repositórios (0..N), variáveis de ambiente cifradas, paused on/off.
- Job: uma execução concreta. Tem id, instância, status (queued → running →
  success|failed-checks|blocked|error|timeout|interrupted; e plan→awaiting_approval),
  deliverable, custo/uso.
- Session (thread): conversa durável atrelada a um thread_key (ex.: ticket),
  compartilhando contexto entre vários jobs ao longo do tempo.

## Princípios de UX já decididos
- Dois níveis SEMPRE: comandos secos (não-interativos, para automação/CI) e um
  modo amigável — rodar "agenthook" sem args cai num menu navegável por setas;
  comandos com argumento omitido abrem um picker.
- Isolamento de auth é um princípio de segurança: nenhuma instância herda
  subscription ou api-key do host. Cada instância tem login próprio e isolado.
- Segredos nunca aparecem em claro: variáveis cifradas, exibidas ofuscadas.
- "Entrar na instância" abre um container Docker efêmero e isolado (shell ou
  chat REPL multi-turno com o agente).

## Telas / fluxos que JÁ existem hoje (quero refinar, não inventar do zero)
1. Hero/banner de entrada (logo de nó "●─╮", nome, versão, tagline, linha de
   status com contagem de instâncias/jobs e dica de navegação). Desenhado uma
   única vez na entrada; a navegação NÃO limpa a tela (mantém o histórico).
2. Menu principal: instances · jobs · sessions · quit.
3. Submenu de instâncias, agrupado por seções:
   - interact: chat (REPL com o agente), shell (container)
   - manage: add, view, edit, env vars
   - list / remove: list, delete
4. Add instância: nome, engine, engine auth, model, branch base, pool de repos,
   geração da chave de criptografia (exibida UMA vez), setup de auth isolado.
5. View instância: tabela de campos + pool de repos + env vars (ofuscadas) +
   jobs recentes.
6. Edit instância: escolher campo (deliverable, engine, authentication, model,
   branch base, repos, env vars, pause/resume).
7. Tela de authentication da instância: status (logged in / not logged in /
   via api-key), log in isolado, set/change api-key, switch de método, log out
   (limpa dados e permite novo login).
8. Editor de env vars (set com flag secret, remove; listagem ofuscada).
9. Editor do pool de repos (add/remove).
10. Listagens: jobs (id/instância/status/deliverable) e sessions
    (id/instância/thread_key/contagem de jobs).

## Estética atual (ponto de partida, aberta a mudança)
- Cor de destaque: lavanda #b48ead. Verde ok #a3be8c, ciano resposta #88c0d0,
  muted/cinza #6b7280.
- Ponteiro de menu "●". Opção de "voltar" fica muted com seta "←".
- Espaçamento: quebra de linha antes de cada menu para dar respiro; opções
  agrupadas por separadores rotulados.

## O que eu quero de você
1. Primeiro, me faça as perguntas necessárias (objetivos, prioridades de fluxo,
   o que falta, o que está confuso, dores de navegação, quais telas merecem o
   dashboard ao vivo do Textual, densidade de informação desejada, etc.).
2. Depois das minhas respostas, produza o design completo no formato de
   entregável descrito acima (mockups ASCII por tela + mapa de navegação +
   paleta + microcopy + padrões de interação), pronto para um desenvolvedor
   implementar em Typer/Rich/questionary (e Textual onde fizer sentido).

Comece me entrevistando.
```
