# Setup Hookless, CI Gate e Workflows DAG — OpenBot

Este guia documenta o contrato **hookless / CI-first** do pacote `ai-harness-openbot` para o runtime **OpenBot**.

## Repositório Compartilhado e Modo Hookless

- **Origem compartilhada:** `/data/OpenBot/Shared/ai-harness-openbot` (referência única de regras, skills, subagentes e `cli.py init`).
- **Sem arquivo local de hooks:** o dialeto `scripts/harness/dialect.py` define `HOOKS_REL = ""` e `IS_HOOKLESS = True`.
- **Trava determinística em CI:** `cli.py init` projeta `.github/workflows/harness-verify.yml` com `permissions: contents: read`, Actions fixadas por SHA-40, sem secrets, executando `scripts/harness/check_tamper.py` e `scripts/harness/verify.py`.

## Subagentes e Skills no Runtime Claude Code (Container OpenBot)

- No container OpenBot (`$HOME = /data`), o Claude Code carrega skills e subagentes globais de `/data/.claude/skills/` e `/data/.claude/agents/`.
- As skills em `.agents/skills/` funcionam via symlink em `/data/.claude/skills/`.
- Os 9 subagentes em `claude/agents/*.md` possuem `tools` traduzidos para o vocabulário Claude Code (`Read`, `Grep`, `Glob`, `Bash`, `Edit`, `Write`) e devem ser linkados em `/data/.claude/agents/`.

## Orquestração DAG Nível 2 (`workflows/spec_dag_runner.py`)

- O workflow `workflows/spec_dag_runner.py` aciona `scripts/harness/dag_runner.py` em ondas topológicas, respeitando semáforo `1..4` workers (padrão `2`), escalonamento `flash` -> `pro` -> `ANTI_LOOP_BLOCKED`, tabelas SQLite `harness_tasks` / `harness_verdicts` vinculadas a `commit_sha` e detecção *Ratchet*.

## Adoção em repositório existente

Use estas regras ao instalar o kit num repositório que já tem instruções, specs ou regras próprias. O roteiro de migração completo está em `plugin/skills/harness-setup/resources/adocao.md`.

1. **Propriedade do CI e grupos legados (`harness-*`, `pack-<nome>`).** No modo hookless OpenBot, `cli.py init` não grava arquivo local de hooks e projeta `.github/workflows/harness-verify.yml` como `project-owned`; regras com aspas duplas em hooks legados do alvo devem ser inspecionadas antes da migração.
2. **Specs legadas.** Mova as specs que não seguem o formato do kit para uma pasta `specs/_<nome>/` (exemplo: `_legado`). O `validate_spec.py --all` pula toda pasta de `specs/` cujo nome começa com `_`.
3. **Templates opcionais.** Liste em `[init] skip_templates` no `harness.toml` os templates (`product`, `structure`, `tech`, `anti-patterns`) que o `init` não deve gravar.
