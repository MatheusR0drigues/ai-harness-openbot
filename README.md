# ai-harness

Fonte canônica do harness pessoal de engenharia de software para **OpenBot** (IDE e CLI/2.0).

Este repositório consolida regras universais em PT-BR, skills de workflow, subagentes nativos, hooks de ciclo de vida, guardas de segurança e gates determinísticos em uma arquitetura híbrida composta por **Plugin Global** + **Kit Local por Repositório** ([ADR-0012](docs/adr/0012-antigravity-hybrid-consolidation.md)).

> [!NOTE]
> Em runtime, todos os scripts do harness (`scripts/harness/`, `plugin/scripts/` e `harness/packs/`) dependem apenas da biblioteca padrão do Python (`>= 3.11`, `[project] dependencies = []`). Ferramentas como `pytest`, `ruff` e `pyright` são usadas apenas no desenvolvimento do próprio `ai-harness` via `uv`.

---

## Como a arquitetura funciona

O `ai-harness` separa o que é **global para todas as conversas** do que é **específico de cada repositório**:

| Superfície | Origem no repo | Onde atua | O que entrega |
| :--- | :--- | :--- | :--- |
| **Plugin Global** | `plugin/` | `/data/OpenBot/Shared/ai-harness-openbot/` | Regras universais em PT-BR, 27 skills (`spec-driven`, `spec-fast-track`, `review`, `fix-bug`, `write-tests`, `verify-app`, `harness-setup`, `create-specialist` e 19 skills de domínio), 9 subagentes nativos e scripts auxiliares (`check_secrets.py`, `validate_spec.py`). **Não** injeta CI gate nem altera `mcp_config.json`. |
| **Kit Local** | `scripts/harness/` + `harness/` | Cada repositório alvo via `cli.py init` | Gate de CI em `.github/workflows/harness-verify.yml`, baseline obrigatório em `harness/core.toml`, motor DAG (`dag_runner.py`), `check_tamper.py` + `harness/baseline.json`, runner `verify.py` e packs opt-in por stack. |

Essa separação evita que hooks de código rodem em workspaces sem `scripts/harness/` e elimina sincronização automática entre múltiplos repositórios por CI ou GitHub App (o fluxo legado `propagate.yml` foi substituído por projeção explícita via `cli.py init`).

---

## Estrutura do repositório

| Caminho | Finalidade |
| :--- | :--- |
| `plugin/` | Pacote distribuível do Plugin Global OpenBot (`plugin/plugin.json`, `plugin/rules/`, `plugin/skills/`, `plugin/agents/`, `plugin/scripts/`). |
| `scripts/harness/` | Runtime `stdlib-only` dos hooks, guardas, scanners de segurança/estrutura, `verify.py`, `doctor.py`, `check_tamper.py` e instalador `init.py`. |
| `harness/core.toml` | Baseline obrigatório com os `required_gates` e `required_guards` mesclados antes do `harness.toml` de cada projeto ([ADR-0011](docs/adr/0011-split-core-and-project-config.md)). |
| `harness/baseline.json` | Hashes SHA-256 (LF) dos arquivos protegidos do kit para detecção de adulteração ([ADR-0014](docs/adr/0014-tamper-detection-baseline.md)). |
| `harness/templates/` | Templates limpos usados pelo `init.py` para inicializar novos projetos (`AGENTS.md`, `harness.toml`, `harness-verify.yml`, regras e `anti-patterns.md`). |
| `harness/packs/` | Packs opt-in por stack: `python`, `node`, `web-ui`, `research-guard`, `data-engineering` e `bi-pbip`. |
| `workflows/spec_dag_runner.py` | Entrypoint `run_workflow` para execução DAG Nível 2 (`specs/<feature>/tasks.md`) com SQLite compartilhado. |
| `docs/` | Decisões arquiteturais (`docs/adr/`), [guia de setup](docs/agent-setup.md), [princípios](docs/harness-principles.md) e [modelo de ameaças](docs/llm-threat-model.md). |
| `tests/` | Suíte determinística (`tests/harness/`) e fixtures de payloads/specs (`tests/fixtures/`), sem rede real, relógio real ou `sleep`. |

---

## Guia rápido de uso

### 1. Sincronizar o Repositório Compartilhado (`/data/OpenBot/Shared/ai-harness-openbot`)

No ambiente **OpenBot**, sincronize esta árvore exportada em `/data/OpenBot/Shared/ai-harness-openbot` como referência compartilhada única de regras, 27 skills (incluindo `verify-app`), 9 subagentes (`.agents/agents/` e `plugin/agents/`), kit local (`scripts/harness/`) e orquestrador DAG (`workflows/spec_dag_runner.py`).

### 2. Instalar o Kit Local em outro repositório (`cli.py init`)

Sempre simule primeiro com `--dry-run` e aplique escolhendo os packs adequados à stack do projeto (a partir do clone deste repositório ou substituindo pelo caminho local de `ai-harness`):

```powershell
# Simular sem gravar arquivos
python scripts\harness\cli.py init --target <caminho-do-projeto> --packs python --dry-run

# Instalar o kit + packs escolhidos
python scripts\harness\cli.py init --target <caminho-do-projeto> --packs python,web-ui

# Atualizar arquivos gerenciados pelo kit em projeto existente
python scripts\harness\cli.py init --target <caminho-do-projeto> --packs python --force
```

O `init.py` separa estritamente dois grupos de arquivos no repositório de destino (`<alvo>`):
- **`kit-owned` (atualizáveis com `--force`; conflito aborta sem `--force`):** `scripts/harness/`, `harness/core.toml`, `harness/baseline.json`, pastas de packs instalados em `harness/packs/` e regras dos packs gravadas em `<alvo>/.agents/rules/`.
- **`project-owned` (criados uma vez a partir de `harness/templates/` e nunca sobrescritos, nem com `--force`):** `AGENTS.md`, `harness.toml`, `.github/workflows/harness-verify.yml`, `<alvo>/.agents/rules/{product,tech,structure,anti-patterns}.md`, `docs/adr/0000-template.md` e `<alvo>/docs/links.txt` (quando `research-guard` está selecionado).

### 3. Desenvolver e verificar dentro deste repositório

Pré-requisito de desenvolvimento local: `uv` + Python `>= 3.11`.

```powershell
uv sync
```

| Objetivo | Comando |
| :--- | :--- |
| Gate rápido (entre tarefas) | `uv run python scripts/harness/verify.py --fast` |
| Gate completo (conclusão) | `uv run python scripts/harness/verify.py` |
| Diagnóstico do ambiente | `uv run python scripts/harness/doctor.py` |
| Integridade SHA-256 dos controles | `uv run python scripts/harness/check_tamper.py` |
| Suíte de testes | `uv run pytest` |
| Lint e formatação | `uv run ruff check .` e `uv run ruff format --check .` |
| Checagem de tipos estrita | `uv run pyright` |
| Validação das specs | `uv run python scripts/harness/validate_spec.py --all` |
| Estrutura do harness e do `plugin/` | `uv run python scripts/harness/check_structure.py` |

---

## Controles, guardas e packs incluídos

### Modo Hookless e CI-First OpenBot (`workflows/spec_dag_runner.py` e `.github/workflows/harness-verify.yml`)
- **Sem hooks locais bloqueantes:** `scripts/harness/dialect.py` opera em modo hookless (`HOOKS_REL = ""`, `IS_HOOKLESS = True`); não há arquivo local de hooks nem interceptação local bloqueante de ferramentas.
- **Orquestração DAG Nível 2 (`workflows/spec_dag_runner.py`):** executa `specs/<feature>/tasks.md` em ondas topológicas via `scripts/harness/dag_runner.py` com semáforo `1..4` workers (padrão `2`), escalonamento `flash` -> `pro` -> `ANTI_LOOP_BLOCKED`, persistência SQLite (`harness_tasks` / `harness_verdicts` vinculados a `commit_sha`) e detecção *Ratchet*.
- **Integridade SHA-256 (`scripts/harness/check_tamper.py`):** valida hashes LF-normalizados de `harness/core.toml` e `scripts/harness/*.py` contra `harness/baseline.json`.
- **Gate de CI projetado (`harness/templates/harness-verify.yml`):** `cli.py init` grava `.github/workflows/harness-verify.yml` com `permissions: contents: read`, Actions fixadas por SHA-40 e zero secrets, executando `python scripts/harness/check_tamper.py` e `python scripts/harness/verify.py`.

### Gates obrigatórios (`harness/core.toml`)
`secrets`, `untrusted`, `controls`, `code-risks`, `specs` e `structure` — todos marcados `fast = true`, complementados neste repositório pelos gates `harness` definidos em `harness.toml` (`ruff-format`, `ruff-lint`, `pyright`, `pytest`, `test-determinism`).

### Packs opt-in (`harness/packs/`)

| Pack | Regras incluídas | Gates / Hooks adicionados |
| :--- | :--- | :--- |
| `python` | `python.md` | `py-format`, `py-lint` (`ruff`), `py-types` (`pyright`), `py-tests` (`pytest`), `py-audit`, `py-determinism` e `py-comments` (AST). |
| `node` | `node.md` | `node-lint`, `node-types`, `node-tests` e `node-audit` via scripts do `package.json`. |
| `web-ui` | `ui_ux_design.md` | Sem gates próprios; regras de acessibilidade WCAG 2.2 AA e Core Web Vitals. |
| `research-guard` | `research-policy.md` | Política declarativa (`research-policy.md`) restringindo consulta a `docs/` e sites autorizados em `<alvo>/docs/links.txt` (modelo em `harness/templates/links.txt`), sem hook local. |
| `data-engineering` | `data-engineering.md` | `spark-antipatterns` (AST PySpark/Delta). |
| `bi-pbip` | `bi-pbip.md` | `pbip-sanity` (indentação TMDL e proteção contra PII em filtros JSON). |

---

## Governança e documentos de referência

- **Raiz de recuperação ([ADR-0009](docs/adr/0009-lock-the-bootstrap-root.md)):** `scripts/harness/cli.py` é protegido contra edição por agentes; qualquer ajuste intencional deve ser feito pelo humano fora da sessão, seguido de `uv run python scripts/harness/check_tamper.py --update` e `uv run python scripts/harness/verify.py`.
- **Documentação completa:** consulte [AGENTS.md](AGENTS.md), [docs/agent-setup.md](docs/agent-setup.md), [docs/harness-principles.md](docs/harness-principles.md), [docs/llm-threat-model.md](docs/llm-threat-model.md) e as ADRs em `docs/adr/`.
