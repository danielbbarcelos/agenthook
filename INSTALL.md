# Instalação e manutenção (dev)

Instalação **editável** via pipx: o comando `agenthook` fica global, mas aponta
para o código-fonte — alterações em arquivos `.py` valem **na hora**, sem reinstalar.

## Instalar

```bash
cd ~/dev/00_labs/claude-webhook
pipx install --editable . --force
```

- Comando global: `agenthook` (em `~/.local/bin/agenthook`)
- Estado/dados: `~/.agenthook/` (instâncias, segredos cifrados, `jobs.db`, logs, worktrees)

Confirmar:

```bash
agenthook --help
```

## Quando reinstalar — regra de ouro

| Você alterou…                                              | Reinstala? | O que fazer                                   |
|------------------------------------------------------------|:----------:|-----------------------------------------------|
| Qualquer arquivo `.py`                                     | ❌         | Nada — é editável. Só rodar `agenthook` de novo. |
| Um `agenthook serve` já rodando                            | ⚠️         | Reiniciar o processo (Python não recarrega vivo). |
| `pyproject.toml` — dependências                            | ✅         | `pipx install --editable . --force`           |
| `pyproject.toml` — entry points (engines/channels/secrets/script) | ✅  | `pipx install --editable . --force`           |

Comando único que cobre qualquer reinstalação:

```bash
cd ~/dev/00_labs/claude-webhook && pipx install --editable . --force
```

## Servidor

Se um `agenthook serve` estiver no ar e você mudar o código, reinicie para pegar as
alterações:

```bash
agenthook service stop && agenthook service start
# ou: Ctrl-C no processo em foreground e subir de novo
```

## Remover

```bash
pipx uninstall agenthook    # remove o comando (NÃO apaga ~/.agenthook)
rm -rf ~/.agenthook         # apaga dados/segredos/instâncias (opcional, destrutivo)
```

## Dia a dia (resumo)

- Editei lógica/`.py` → nada a fazer, só rodar.
- Mexi em deps ou entry points do `pyproject.toml` → `pipx install --editable . --force`.
- Servidor no ar e mudei código → reinicie o `serve`.
