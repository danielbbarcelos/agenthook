# agenthook — instruções do projeto

## Workflow de desenvolvimento

**Sempre que fizermos alterações no código aqui, reinstale o agenthook em seguida:**

```bash
pipx install --editable . --force
```

A instalação é editável (mudanças em `.py` valem na hora), mas o reinstall garante
que entry points, dependências e o binário em `~/.local/bin/agenthook` fiquem
consistentes. Rode após cada rodada de alterações, sem precisar pedir.

> Atenção ao caminho: o `.pth` do pipx deve apontar para o diretório real deste
> repositório. Confirme que aponta para cá após reinstalar.

## Design

A interface (TUI) segue a direção **Guided** documentada em `design-system/`
(ver `design-system/README.md` — paleta, padrões, mapa de navegação e as telas).
A spec de produto vive em `DESIGN.md`.

## Roadmap / produto (Agenthook como plataforma multi-projeto)

Plano de ação para usar o Agenthook como task runner por projeto (webhooks de
tickets/kanban → agente de código), integrado ao app `projector` do sistema
`dbmv/workspace`, com hardening de segredo/egress:

- [`docs/product-plan.md`](docs/product-plan.md) — plano faseado (Agenthook + Projector), sequência, decisões pendentes.
- [`docs/security-and-secrets.md`](docs/security-and-secrets.md) — modelo de ameaça, decisão de tier Infisical (Community vs Enterprise; por que **não** Pro), efemeridade de credencial sem Enterprise.
- [`docs/infisical-alternatives-prompt.md`](docs/infisical-alternatives-prompt.md) — prompt para pesquisar alternativas ao Infisical (dynamic DB secrets self-hosted grátis).
- [`deploy/go-live.md`](deploy/go-live.md) — deploy VPS (systemd + reverse proxy TLS), build das imagens (runner + egress broker), secrets por instância e checklist de go-live. Fases 1–3 de hardening já implementadas (egress `agenthook/egress/`, GitHub App `agenthook/github_app.py`, least-privilege in-app).
