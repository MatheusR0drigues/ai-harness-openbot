---
name: create-specialist
description: "Cria e padroniza subagentes especialistas consultivos somente leitura (<dominio>-architect) com grounding híbrido em skills do harness, servidores MCP, documentação oficial e canais de release notes. Use quando pedirem para criar um novo subagente especialista de tecnologia ou domínio (ex: databricks, powerbi, mcp, cloud)."
---

# Criação de Subagentes Especialistas (`<dominio>-architect`)

Padroniza a criação de subagentes especialistas **consultivos somente leitura** (`tools: [read_file, search_web]`) voltados à higiene de contexto (*Prefix Caching* & *Observation Masking*), garantindo que o especialista absorva a leitura pesada de skills, metadados MCP, documentação oficial e *Release Notes* e devolva apenas o parecer técnico destilado ao coordenador.

Use [databricks-architect.md](../../agents/databricks-architect.md) como **exemplar canônico** de referência e [resources/specialist-template.md](resources/specialist-template.md) como molde estrutural.

## Regra de Alocação (Global vs. Repositório)

Escolha onde salvar o arquivo `<dominio>-architect.md` antes de gerá-lo:

| Cenário | Destino Canônico | Critério |
| :--- | :--- | :--- |
| **Tecnologia ou padrão puro** (reutilizável entre projetos, zero dado interno) | `plugin/agents/<dominio>-architect.md` | Ex.: `databricks-architect`, `powerbi-architect`, `mcp-architect`. Deve passar por `check_structure.py` e sem vazamentos de domínio privado. |
| **Domínio ou negócio específico** (ontologias, tabelas, filas ou sistemas internos de um projeto) | `.agents/agents/<dominio>-architect.md` | Especializa o projeto alvo sem poluir o plugin global; lê regras locais em `.agents/rules/tech.md` e `structure.md`. |

## Roteiro de Criação (5 Passos)

### 1. Mapear os 4 Eixos do Especialista

Se houver ambiguidade sobre escopo, MCP ou stack, entreviste o humano antes de gerar o arquivo para fechar os 4 eixos:

1. **Eixo 1 — Base de Engenharia (`ai-harness` + Packs Locais):**
   - Liste as skills do plugin (`../<skill>/SKILL.md`) e as regras de pack local (`data-engineering`, `bi-pbip`, `python`, `node`, `web-ui`, `research-guard`) que regem o domínio.
2. **Eixo 2 — Grounding Híbrido (MCP + Plugins de Parceiro):**
   - Defina os plugins oficiais do Marketplace aplicáveis (quando ativos na sessão) e os servidores MCP do domínio.
   - Estruture o protocolo em **Modo Híbrido**: consulta direta ao MCP quando acessível no subagente, ou lista objetiva do que o coordenador deve consultar no MCP antes de enviar ao `implementer`.
3. **Eixo 3 — Mapa de Documentação Oficial e Canal de Release / Patch Notes:**
   - Restrinja `search_web` a domínios oficiais explícitos (`domain="<dominio-oficial>"`).
   - Mapeie explicitamente ao menos 1 URL de **Release Notes / Patch Notes / Changelog** para checar versões vigentes, recursos em Preview vs. GA, depreciações e breaking changes pós-corte de treinamento.
4. **Eixo 4 — Invariantes Inegociáveis e Guia para o `implementer`:**
   - Escreva 4 a 6 invariantes técnicas objetivas e verificáveis (sem prosa genérica) e defina como o especialista deve orientar o `implementer` em código modular e testes determinísticos.

### 2. Instanciar o Template Canônico

1. Leia [resources/specialist-template.md](resources/specialist-template.md) e o exemplar [databricks-architect.md](../../agents/databricks-architect.md).
2. Mantenha o frontmatter estritamente aderente ao contrato do harness:
   - `name`: igual ao nome do arquivo sem `.md`, em kebab-case (`<dominio>-architect`), nunca colidindo com nomes reservados (`self`, `browser`, `research`, `deepagent`, `review-agent`).
   - `description`: entre 30 e 1024 caracteres, **sempre entre aspas duplas**, explicando o domínio, o grounding híbrido e quando invocar.
   - `subagent: true`, `mainAgent: false`.
   - `tools: [read_file, search_web]` (somente leitura + web).
3. Use apenas marcadores `<placeholder>` ao editar rascunhos; nunca deixe placeholders não resolvidos ou chaves duplas no arquivo final.
4. Garanta que o corpo preserve as seções de **Grounding Híbrido**, **Guardrails OWASP (`LLM01`/`MCP03`/`LLM02`)** e **Entrega via `send_message`** com exatamente uma linha `VEREDITO: PASS` ou `VEREDITO: FAIL`.

### 3. Tabela de Referência Rápida para Futuros Especialistas

| Especialista | Base `ai-harness` (Eixo 1) | Grounding Híbrido / MCP (Eixo 2) | Docs Oficiais e Release Notes (Eixo 3) | Invariantes-Chave (Eixo 4) |
| :--- | :--- | :--- | :--- | :--- |
| `databricks-architect` | `medallion-lakeflow`, `spark-delta-optimization`, `pipeline-ci-cd`, `data-contracts-odcs`, `schema-drift-gatekeeper`, pack `data-engineering` | Plugin `databricks` + MCP Unity Catalog / SQL Warehouse / catálogo de ontologia | `docs.databricks.com`, `learn.microsoft.com`, `docs.delta.io`, `spark.apache.org` + DBR/Platform/CLI Release Notes | `entrada == limpos + quarentena`, `NULL` ternário, Liquid Clustering, zero `.toPandas()` sem `.limit()`, DABs + OIDC |
| `powerbi-architect` | `powerbi-pbip-tmdl`, `dataviz-accessibility-darkmode`, `dtcg-design-tokens`, `data-contracts-odcs`, pack `bi-pbip` | MCP de Modelo Semântico / Linhagem + leitura de `.tmdl`/`.pbir` | `learn.microsoft.com` (Power BI, DAX, TMDL, PBIP) + Power BI Monthly Release Notes / Desktop Changelog | Star Schema, DAX com `VAR/RETURN` e `DIVIDE()`, `.tmdl` indentado por tab (como o Desktop grava), zero PII em filtros JSON, WCAG 2.2 AA |
| `mcp-architect` | `mcp-governance`, `resilience-patterns`, `auth-bff-oauth`, packs `python`/`node` | Inspecionar schemas locais de MCP (`list_resources`, contratos JSON-RPC) | `modelcontextprotocol.io`, SDK oficial Python/TypeScript + MCP Spec Changelog / Releases | Pin exato (zero `@latest` / `npx -y`), OAuth 2.1 escopo mínimo, higiene STDIO sem logs espúrios, `MCP03`/`MCP09`/`MCP10` |
| `claude-architect` | `mcp-governance`, `resilience-patterns`, `secure-rag-design`, `auth-bff-oauth`, `spec-driven`, packs `python`/`node` | MCP inspect schemas + SDKs oficiais (`anthropic`, `@anthropic-ai/sdk`, Claude Code CLI) | `docs.anthropic.com`, `claude.ai`, `modelcontextprotocol.io` + API Changelog, Models Matrix e Claude Code Releases | Prompt Caching (prefixo estático), Extended Thinking com temp 1.0, Tool Use estrito, limite 200 linhas de contrato, Messages API e retries 429/529 |
| `github-architect` | `pipeline-ci-cd`, `data-contracts-odcs`, `schema-drift-gatekeeper`, `powerbi-pbip-tmdl`, `medallion-lakeflow`, packs `python`/`data-engineering`/`bi-pbip` | Inspeção de workflows/DABs/ODCS/PBIP + MCP GitHub/catálogo + CLIs (`gh`, `databricks`, `uv`) | `docs.github.com`, `github.blog`, `docs.databricks.com`, `github.com` + GitHub Actions Changelog & Runner Images | Pinning SHA-40, OIDC (`id-token: write`), `persist-credentials: false`, zero script injection em `run:`, Reusable Workflows, `concurrency` e WAP |

### 4. Registrar no Plugin e nos Testes (quando alocado em `plugin/agents/`)

Se o especialista for global (em `plugin/agents/`):

1. Adicione o nome do subagente na linha `Subagentes nativos` em `plugin/rules/AGENTS.md`.
2. Adicione o nome na tupla `SUBAGENTS` e valide seu conteúdo em `tests/harness/test_rule_content.py`.

### 5. Validar com os Sensores

Após criar ou atualizar o especialista, execute os sensores obrigatórios na raiz do repositório:

```bash
uv run python scripts/harness/check_structure.py
uv run python scripts/harness/verify.py
```

Nenhum especialista está pronto enquanto `check_structure.py` não imprimir `STRUCTURE VALID` e os testes/gates aplicáveis não fecharem com código `0`.
