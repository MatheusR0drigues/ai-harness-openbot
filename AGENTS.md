# AGENTS.md

Contrato operacional para agentes no **OpenBot** (`ai-harness-openbot`).
Modo **hookless / CI-first**: `1 Gerente por repositório`, sem hooks locais; a verificação determinística roda via `verify.py`, `run_workflow` e `.github/workflows/harness-verify.yml`.

## Projeto

`ai-harness-openbot` é o pacote OpenBot derivado do `ai-harness`, servindo como fonte compartilhada em `/data/OpenBot/Shared/ai-harness-openbot` para regras, skills, subagentes e kit local.

## Stack

- Runtime de guardas, gates e DAG (`scripts/harness/`, `workflows/`): Python `>= 3.11`, `stdlib-only` (`[project] dependencies = []`).
- Ferramentas de desenvolvimento (`uv` / `python -m`): `pytest`, `ruff` e `pyright` (modo `strict`).

## Comandos

| Objetivo | Comando |
| :--- | :--- |
| Gate completo (CI e conclusão) | `python scripts/harness/verify.py` |
| Gate rápido (entre tarefas) | `python scripts/harness/verify.py --fast` |
| Diagnóstico do ambiente | `python scripts/harness/doctor.py` |
| Integridade SHA-256 | `python scripts/harness/check_tamper.py` |
| Estrutura do harness e plugin | `python scripts/harness/check_structure.py` |
| Validação de specs | `python scripts/harness/validate_spec.py --all` |
| Orquestrador DAG Nível 2 (`run_workflow`) | `python workflows/spec_dag_runner.py --tasks specs/<feature>/tasks.md` |

## Topologia do Repositório

- `.agents/rules/`, `.agents/skills/`, `.agents/agents/`: espelho operacional OpenBot.
- `claude/agents/`: 9 subagentes com `tools` no vocabulário Claude Code para symlink em `/data/.claude/agents/`.
- `plugin/`: pacote distribuível de regras, 27 skills, 9 subagentes e scripts.
- `scripts/harness/`: runtime `stdlib-only` (`dialect.py` hookless, `dag_runner.py`, `verify.py`, `init.py`, `doctor.py`, `check_tamper.py`).
- `workflows/spec_dag_runner.py`: entrypoint `run_workflow` para ondas topológicas.
- `harness/`: `core.toml`, `baseline.json`, `templates/` (inclui `harness-verify.yml`) e `packs/`.
- `docs/` e `specs/`: ADRs em `docs/adr/`, guias em `docs/` e specs em `specs/`.

## Convenções Críticas

- **Zero credenciais hardcoded:** nunca exponha segredos ou PII em código, logs ou prompts.
- **Evidência ou zero:** conclusão e vereditos exigem saída real executada após a última edição.
- **Integridade dos sensores:** nunca desative ou contorne `verify.py`, `check_tamper.py`, `.github/workflows/harness-verify.yml` ou testes.
- **Isolamento OpenBot:** `1 Gerente por repositório`; tarefas usam `start_task` em `git worktree` isolada (`../wt-<feature>`) e `harness/core.toml` é protegido.

## Comportamento do Agente

1. Leia os arquivos relevantes antes de editar e faça mudanças cirúrgicas no escopo pedido.
2. Simplicidade primeiro: zero abstrações ou configurações não solicitadas.
3. **Ciclo anti-loop (2 falhas):** após 2 falhas consecutivas na mesma abordagem, pare, registre em `progress.md` e mude a estratégia ou consulte o usuário.
4. Releia `git diff --stat` e inspecione as alterações antes de concluir.

## Fluxo de Trabalho

1. **Tier 0 (Micro):** 1–2 arquivos triviais -> edição direta + `verify.py --fast`.
2. **Tier 1 (Fast-Track):** até 3–5 arquivos sem contrato/segurança -> `spec-fast-track` inline (`start_task` em `git worktree`, `verify.py --fast`, `git diff --stat`).
3. **Tier 2 (`spec-driven`):** feature, contrato, segurança ou `>5` arquivos -> `specs/<feature>/`, execução em ondas via `run_workflow` (`workflows/spec_dag_runner.py`), `verify.py` completo e revisão independente (`code-reviewer` + `security-auditor`).
4. **Bug:** skill `fix-bug` com teste de regressão que falha antes da correção.

## Critério de Pronto

- [ ] `python scripts/harness/verify.py` retorna `ALL GATES PASSED` e `.github/workflows/harness-verify.yml` verde.
- [ ] `git diff --stat` revisado, sem segredos, desvios de escopo ou sensores enfraquecidos.

## Mapa de Conhecimento

- Setup hookless e DAG OpenBot: `docs/agent-setup.md`.
- Princípios e modelo de ameaças: `docs/harness-principles.md` e `docs/llm-threat-model.md`.
- Origem compartilhada do kit: `/data/OpenBot/Shared/ai-harness-openbot`.
