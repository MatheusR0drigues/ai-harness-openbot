# ADR-0016: Arquitetura de Memoria em 3 Camadas, 3 Perfis de Contexto de Repositorio e Integridade de Ponteiros

- Date: 2026-11-14
- Status: Accepted

## Context

A avaliacao comparativa entre a literatura de engenharia de contexto/harness (estudo da ETH Zurich, *Context Rot*, *Lost-in-the-Middle*, *Prefix Caching* e *Memória Virtual* estilo MemGPT/Letta) e repositorios reais do ecossistema identificou tres problemas estruturais na forma como o contexto interno de cada repositorio vinha sendo organizado:

1. **Burocracia uniforme:** `harness/templates/` e `plugin/skills/harness-setup/SKILL.md` projetavam a mesma cerimonia para qualquer projeto, sem distinguir entre scripts/POCs leves, servicos padrao e plataformas de dominio rico (como lakehouses e monolitos modulares com dezenas de tabelas e pipelines).
2. **Inflacao de arquivos `always_on` vs. fragmentacao ad-hoc:** a ausencia de um padrao para conhecimento topologico sob demanda leva times a despejar dicionarios de dados em regras sempre ativas (degradando a janela de contexto e aumentando consumo de tokens) ou a inventar pastas distintas por projeto (`memory/`, `context/`, `knowledge/`). Alem disso, estudos empiricos mostram perda aproximada de `2%` de acuracia por `100k` tokens acumulados (*Context Rot*) e queda de desempenho quando arquivos extensos de instrucao poluem o prompt base.
3. **Acoplamento de contratos de producao e links quebrados:** em repositorios reais, contratos e esquemas consumidos em runtime por servicos irmaos (ex.: servidores MCP) acabavam hospedados dentro de pastas de governanca do agente, e ponteiros em `AGENTS.md` podiam ficar obsoletos sem deteccao deterministica.

## Decision

1. **Arquitetura de Memoria do Repositorio em 3 Camadas:**
   - **Camada Quente (`Core Memory` — `always_on`):** `AGENTS.md` (`<= 150` linhas, limite rigido `200`) como mapa topografico estatico, acompanhado de `.agents/rules/product.md`, `.agents/rules/tech.md` e `.agents/rules/structure.md` curtos, sem catalogos extensos inline.
   - **Camada Morna (`Scoped & Recall Memory` — `trigger: glob` / `model_decision`):** `.agents/rules/anti-patterns.md` (`model_decision`), regras dos packs ativos, regras de subdominio/camada com `trigger: glob` (ex.: `.agents/rules/<camada>.md`) e `specs/<feature>/progress.md`.
   - **Camada Fria (`Archival Context` — leitura sob demanda):** conhecimento topologico detalhado em `docs/context/<arquivo>.md` (ex.: catalogo de dados, resumo de pipelines, integracoes) e `docs/adr/`, listados no mapa de conhecimento do `AGENTS.md` com indicacao de *quando consultar*.
   - **Isolamento de Contratos de Runtime:** artefatos consumidos em producao por outros sistemas ou servicos vivem obrigatoriamente em `contracts/<dominio>.*` ou `schemas/<dominio>.*` na raiz do repositorio, nunca dentro de `.agents/` ou `docs/context/`.

2. **Escala de Maturidade em 3 Perfis de Repositorio (`harness-setup`):**
   - **Perfil 1 — Essencial (Low Ceremony):** utilitarios, scripts, POCs e bibliotecas pequenas; Camada Quente minima + `anti-patterns.md` + packs; sem `docs/context/`.
   - **Perfil 2 — Engenharia Padrao (Standard):** microsservicos, APIs, BFFs, servidores MCP e apps web; Camada Quente completa + packs + `docs/adr/` e `specs/` quando Tier 2.
   - **Perfil 3 — Dominio Rico / Plataforma (High-Context):** lakehouses, monolitos modulares, plataformas multi-dominio e projetos de BI complexos; todas as 3 camadas, incluindo regras por `trigger: glob`, `docs/context/<arquivo>.md`, contratos em `contracts/` ou `schemas/`, e avaliacao de subagente especialista via `create-specialist`.
   - Incluir em `plugin/skills/harness-setup/SKILL.md` e `plugin/skills/harness-setup/resources/context-templates.md` o guia de decisao passo a passo e o mapeamento de migracao a partir de estruturas legadas.

3. **Sensor de Integridade de Ponteiros (`scripts/harness/check_structure.py`):**
   - Estender `guidance_files` para incluir `docs/context/*.md`.
   - Estender `PATH_REF` para cobrir `contracts/` e `schemas/`.
   - Estender `check_references` com `_local_markdown_refs` para validar alvos locais de links Markdown `[label](alvo)` em arquivos de governanca (`AGENTS.md`, `README.md`, `.agents/rules/*.md`, `.agents/skills/`, `docs/*.md`, `docs/context/*.md`), atualizando `harness/baseline.json` via `check_tamper.py --update`.

## Consequences

- O prefixo do prompt permanece estavel e enxuto, preservando *Prefix Caching* e mitigando *Context Rot* e *Lost-in-the-Middle*.
- Repositorios simples evitam burocracia desnecessaria enquanto repositorios criticos ganham estrutura uniforme, rastreavel e auditavel.
- Links quebrados e referencias para arquivos inexistentes em `AGENTS.md`, regras, skills ou `docs/context/` falham deterministicamente no gate `structure`.
- A atualizacao de `scripts/harness/check_structure.py` exige regenerar `harness/baseline.json` com `python scripts/harness/check_tamper.py --update`.
