# ADR-0018: Retirada do acervo bruto da Etapa 1 (`raw/`), catálogos de migração e `docs/research/`

- Date: 2026-11-15
- Status: Accepted

## Context

Durante as Etapas 1 a 3 da consolidação do `ai-harness` ([ADR-0012](0012-antigravity-hybrid-consolidation.md)), o repositório preservou em modo somente leitura:

- `raw/` (287 arquivos extraídos dos repositórios originais);
- os catálogos de mapeamento da Etapa 1 (`docs/INVENTARIO.md`, `docs/COMPATIBILITY_MATRIX.md`, `docs/inventory.json`, `docs/roadmap.md`);
- `docs/research/` (3 sínteses técnicas importadas e posteriormente alinhadas à base de conhecimento interna).

Com a consolidação e o deploy global concluídos (e com o exportador `tools/export_claude.py` já omitindo esses artefatos per [ADR-0017](0017-claude-sync-exporter.md)), manter ~2,2 MB de arquivos históricos da migração e notas de pesquisa já absorvidas pelas regras e skills do harness adiciona ruído de contexto e manutenção desnecessária ao repositório canônico.

## Decision

Retirar `raw/`, os catálogos da Etapa 1 (`docs/INVENTARIO.md`, `docs/COMPATIBILITY_MATRIX.md`, `docs/inventory.json`, `docs/roadmap.md`) e `docs/research/` do repositório `ai-harness`, removendo em conjunto:

- `PRESERVED_DOCS` em `scripts/harness/check_structure.py` (atualizando `harness/baseline.json` via `check_tamper.py --update`);
- os testes de integridade da Etapa 1 em `tests/harness/test_smoke.py` e `tests/harness/test_check_structure.py`;
- as isenções e referências em `harness.toml`, `.gitattributes`, `AGENTS.md`, `README.md` e `docs/llm-threat-model.md`.

## Consequences

- O repositório passa a conter apenas o runtime do kit local (`scripts/harness/`, `harness/`), o plugin global (`plugin/`), ferramentas (`tools/`), testes e documentação operacional/arquitetural (`docs/adr/`, `docs/agent-setup.md`, `docs/harness-principles.md`, `docs/llm-threat-model.md`).
- O histórico completo da Etapa 1 permanece preservado nos commits anteriores do Git caso seja necessário consultá-lo.
- Todos os arquivos em `docs/*.md` passam a ter suas referências locais verificadas sem exceções por `scripts/harness/check_structure.py`.
