# ADR-0015: Fluxo em 3 Tiers, Roteamento Hibrido de Modelos, Packs de Dominio e Refinamento de LEAK_TERMS

- Date: 2026-11-14
- Status: Accepted

## Context

A revisao da base de conhecimento interna de engenharia antes da Etapa 4 (deploy global) identificou tres atritos no uso diario do `ai-harness`:

1. Exigir o rito completo de `spec-driven` (4 arquivos em `specs/<feature>/` + auditoria obrigatoria do `code-reviewer`) para tarefas focalizadas do dia a dia eleva o consumo de tokens e atrasa entregas simples.
2. Nao havia orientacao explicita para rotear subagentes de pesquisa e implementacao bem delimitada para modelos economicos (`flash`/`flash_lite`) com escalonamento automatico para modelo principal (`inherit`/`pro`) em caso de falha de gate.
3. O termo `"databricks"` constava em `LEAK_TERMS` (`scripts/harness/check_structure.py` e `tests/harness/test_profiles.py`), bloqueando a publicacao de skills e packs genericos de engenharia de dados que citam plataformas publicas de mercado, embora o repositorio nao possua packs opt-in especificos para Engenharia de Dados nem para Power BI (`PBIP`/`TMDL`).

## Decision

1. **Fluxo proporcional em 3 Tiers e roteamento Hydrogen (`flash`/`flash_lite` -> `inherit`):** adotar formalmente Tier 0 (Micro), Tier 1 (`spec-fast-track` inline no chat, zero arquivos em `specs/`, `implementer` em `flash` com escalonamento para `inherit` na 1a falha de `verify --fast` e parada na 2a falha pelo Ciclo Anti-Loop) e Tier 2 (`spec-driven` completo em `specs/<feature>/` para features, contratos, arquitetura, seguranca ou >5 arquivos).
2. **Remocao de `"databricks"` de `LEAK_TERMS`:** remover `databricks` da regex `LEAK_TERMS` em `scripts/harness/check_structure.py` e da tupla `LEAK_TERMS` em `tests/harness/test_profiles.py`, mantendo bloqueados identificadores e caminhos de projetos privados legados, outros harnesses (`.claude`, `.kiro`, `.codex`), marcadores internos e placeholders nao resolvidos.
3. **Expansao de skills e packs opt-in:** adicionar `data-engineering` e `bi-pbip` em `scripts/harness/config.py` (`SUPPORTED_PACKS`) e expandir `plugin/skills/` com as 20 skills de fluxo, engenharia de dados, BI/dataviz, seguranca e arquitetura de software.

## Consequences

- Tarefas focalizadas (~80% do fluxo diario) ganham agilidade e economia de tokens via `spec-fast-track` e subagentes em `flash`, preservando sensores deterministas (`PreToolUse` e `verify --fast`) sem rebaixar a seguranca em Tier 2.
- O plugin global e os novos packs podem referenciar ecossistemas publicos de dados (como Spark, Delta Lake, Databricks, PBIP/TMDL) sem falsos positivos em `check_structure.py`.
- A baseline SHA-256 em `harness/baseline.json` e atualizada via `check_tamper.py --update` para refletir a edicao intencional de `scripts/harness/config.py` e `scripts/harness/check_structure.py`.
