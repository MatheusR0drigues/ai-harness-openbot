---
name: harness-setup
description: "Diagnostica o porte do repositório (Perfis 1, 2 e 3), instala o harness local via cli.py init com os packs adequados e organiza as camadas Quente, Morna e Fria de contexto e contratos, validando com doctor e verify. Use ao inicializar, especializar ou migrar o harness e a arquitetura de contexto de um projeto."
---

# Configuração do Harness e Arquitetura de Contexto (`harness-setup`)

O código do harness permanece genérico; o projeto é especializado editando dados (`AGENTS.md`, `harness.toml`, `.agents/rules/` e, quando aplicável, `docs/context/`). Entreviste o humano quando houver ambiguidade; nunca adivinhe propósito, stack ou fronteiras de domínio.

## Arquitetura de Memória em 3 Camadas (`Core`, `Scoped/Recall`, `Archival`)

Baseado em evidências de engenharia de contexto (estudo da ETH Zurich sobre arquivos de agente inflados, degradação por *Context Rot* de ~2% por 100k tokens, *Lost-in-the-Middle*, *Prefix Caching* e memória virtual em camadas), distribua o conhecimento do repositório segundo a frequência e o custo de carregamento:

| Camada | Papel Cognitivo | Onde Vive | Carregamento | Orçamento |
| :--- | :--- | :--- | :--- | :--- |
| **Camada Quente (`Core Memory`)** | Mapa topográfico, comandos exatos, propósito e stack | `AGENTS.md` + `.agents/rules/{product,tech,structure}.md` | `always_on` (prefixo estático para *Prefix Caching*) | `AGENTS.md <= 150` linhas (teto `200`); cada regra `always_on <= 80` linhas, sem catálogos inline |
| **Camada Morna (`Scoped / Recall Memory`)** | Armadilhas passadas, regras por camada/subdomínio e estado ativo | `.agents/rules/anti-patterns.md`, `.agents/rules/<escopo>.md`, `specs/<feature>/progress.md` | *Progressive Disclosure*: `trigger: model_decision` ou `trigger: glob` (ex.: `src/silver/**`) | Abaixo de `24000` bytes por arquivo; carregado só no escopo pertinente |
| **Camada Fria (`Archival Context`)** | Catálogo de tabelas, resumo de pipelines, integrações e histórico | `docs/context/<arquivo>.md` e `docs/adr/` | Sob demanda via `read_file`, indexado na seção `## Mapa de Conhecimento` do `AGENTS.md` | `0` tokens no prompt base até ser explicitamente lido |

> [!IMPORTANT]
> Contratos, ontologias e esquemas consumidos em **produção** por outros sistemas ou servidores MCP vivem sempre em `contracts/` ou `schemas/` na raiz do repositório — nunca dentro de `.agents/` nem misturados em `docs/context/`.

## Árvore de Decisão: Os 3 Perfis de Maturidade do Repositório

Nem todo repositório precisa da mesma burocracia. Avalie **4 sinais objetivos** (subdomínios/camadas independentes, catálogo de dados/APIs que não cabe na Camada Quente, contratos externos consumidos por outros repositórios e criticidade/cadência de mudança) para recomendar um perfil e confirmar com o humano:

| Dimensão | **Perfil 1 — Essencial (Low Ceremony)** | **Perfil 2 — Engenharia Padrão (Standard)** | **Perfil 3 — Domínio Rico / Plataforma (High-Context)** |
| :--- | :--- | :--- | :--- |
| **Quando escolher** | Utilitários, scripts, CLIs internas, POCs, bibliotecas pequenas (`0`–`1` sinal) | Microsserviços, APIs, BFFs, servidores MCP, apps web (`1`–`2` sinais) | Lakehouses, monólitos modulares, plataformas multi-domínio e projetos BI complexos (`3`–`4` sinais) |
| **Camada Quente (`always_on`)** | `AGENTS.md` (`<= 100` linhas) + `tech.md` + `product.md` (1 parágrafo) + `structure.md` enxuto | `AGENTS.md` + `product.md`, `tech.md`, `structure.md` completos | `AGENTS.md` como roteador estrito + `product.md`, `tech.md`, `structure.md` concisos (zero tabelas extensas inline) |
| **Camada Morna (`Scoped / Recall`)** | `anti-patterns.md` + regras dos packs ativos | `anti-patterns.md` + regras dos packs ativos | `anti-patterns.md` + packs + regras segmentadas por `trigger: glob` (`.agents/rules/<camada>.md`) |
| **Camada Fria (`docs/context/`)** | Nenhuma (evite pastas extras) | Apenas `docs/adr/` quando houver decisão arquitetural | `docs/context/` estruturado (`pipeline-summary.md`, `data-catalog.md`, `integrations.md`) + `docs/adr/` |
| **Contratos externos** | N/A | `contracts/` ou `schemas/` na raiz, se aplicável | Obrigatório isolar em `contracts/` ou `schemas/` |
| **Especialistas locais** | Não necessário | Opcional | Recomendado via [create-specialist](../create-specialist/SKILL.md) em `.agents/agents/<dominio>-architect.md` |
| **Fluxo predominante** | Tier 0 e Tier 1 (`spec-fast-track`, sem pasta em `specs/`) | Tier 1 no dia a dia; Tier 2 (`specs/<feature>/`) em mudança de contrato/segurança/`>5` arquivos | Tier 1 para ajustes pontuais; Tier 2 (`specs/<feature>/`) para novas pipelines, tabelas, contratos ou refatorações amplas |

## Packs Disponíveis

| Pack | Quando ativar | O que adiciona |
| :--- | :--- | :--- |
| `python` | Código Python | `ruff`, `pyright` em modo strict, `pytest`, auditoria de dependências, determinismo de testes, verificação de comentários e regras contra `eval`, `exec`, `pickle` e `verify=False` |
| `node` | Código JavaScript ou TypeScript | Lint, checagem de tipos, testes e auditoria de dependências |
| `web-ui` | Interfaces web | Regra de UI com tokens DTCG, contraste WCAG 2.2 AA (`4.5:1` / `3:1`), paleta acessível e Core Web Vitals |
| `research-guard` | Pesquisa com fontes restritas | Regra de pesquisa (`research-policy.md`) que limita busca e leitura web às fontes aprovadas em `docs/links.txt` |
| `data-engineering` | Pipelines PySpark / SQL / Delta | Regra de dados (invariante `entrada == limpos + quarentena`, lógica `NULL`) e gate AST `spark-antipatterns` |
| `bi-pbip` | Projetos Power BI (`.pbip`/`.tmdl`) | Regra PBIP/DAX/Dataviz e gate `pbip-sanity` (indentação `.tmdl` por tab e detecção de PII em filtros JSON salvos) |

## Passos

1. **Diagnosticar o repositório e classificar o Perfil (1, 2 ou 3).** Inspecione a árvore de arquivos (sem despejar arquivos inteiros no contexto) e avalie com o humano os 4 sinais objetivos para fechar o **Perfil 1**, **Perfil 2** ou **Perfil 3**, além de stack, gerenciador de pacotes, comandos de teste, restrições de segurança e quais packs ativar.
2. **Simular a instalação (`cli.py init --dry-run`).** Confirme com o humano o caminho do clone do `ai-harness` e do repositório alvo e rode:

   ```bash
   python /data/OpenBot/Shared/ai-harness-openbot/scripts/harness/cli.py init --target <repo> --packs <lista> --dry-run
   ```

   `<lista>` é separada por vírgulas (por exemplo `python,data-engineering`). Mostre ao humano o plano de arquivos que serão gravados. Quando o Sinal de harness próprio está presente, execute o roteiro de [adocao.md](resources/adocao.md) antes do `init` sem `--dry-run`, nas fases Inventário, Decisões, Aplicação e Verificação.
3. **Instalar o kit local.** Com aprovação, execute o mesmo comando sem `--dry-run`. Use `--force` apenas com autorização explícita do humano para atualizar arquivos `kit-owned`.
4. **Preencher a Camada Quente (`Core Memory`) proporcional ao Perfil.**
   - Substitua todo "A definir" em `.agents/rules/product.md`, `.agents/rules/tech.md` e `.agents/rules/structure.md` respeitando o teto enxuto (`<= 80` linhas cada).
   - No **Perfil 1**, mantenha `product.md` em 1 parágrafo e não adicione detalhes redundantes.
   - No `AGENTS.md`, preencha `## Projeto`, `## Stack`, `## Comandos` e `## Mapa de Conhecimento`, mantendo o arquivo em até `150` linhas (`200` no máximo) como roteador puro, sem catálogos inline.
5. **Configurar a Camada Morna (`Scoped / Recall Memory`).**
   - Mantenha `.agents/rules/anti-patterns.md` (`trigger: model_decision`) como catálogo ativo de falhas evitáveis.
   - No **Perfil 3** (e quando houver subdomínios isolados no **Perfil 2**), crie regras por escopo em `.agents/rules/<camada>.md` com `trigger: glob` e `globs` estrito usando o Template 1 de [context-templates.md](resources/context-templates.md). Valores de frontmatter com `: ` devem vir entre aspas duplas e cada arquivo deve permanecer abaixo de `24000` bytes.
6. **Estruturar a Camada Fria (`docs/context/`) e Contratos (`contracts/` ou `schemas/`).**
   - Apenas para **Perfil 3**: instancie somente os arquivos necessários em `docs/context/` (`pipeline-summary.md`, `data-catalog.md`, `integrations.md`) a partir dos Templates 2–4 de [context-templates.md](resources/context-templates.md) e indexe cada arquivo na seção `## Mapa de Conhecimento` do `AGENTS.md` dizendo exatamente **quando** o agente deve lê-lo.
   - Isole qualquer schema, ontologia ou contrato consumido em produção por outros sistemas em `contracts/` ou `schemas/` na raiz do projeto.
7. **Migrar contexto legado (quando aplicável).** Se o repositório já possuir pastas ad-hoc (`memory/`, `context/`, `knowledge/` ou pastas de outros agentes), aplique a **Tabela de Mapeamento para Migração** de [context-templates.md](resources/context-templates.md) e remova duplicatas obsoletas após confirmar com o humano.
8. **Avaliar subagente especialista local (Perfil 3).** Em plataformas ou domínios ricos que dependam de MCP, ontologia interna ou regras profundas de stack, avalie com o humano criar `.agents/agents/<dominio>-architect.md` seguindo a skill [create-specialist](../create-specialist/SKILL.md).
9. **Configurar `harness.toml`, revisar o workflow de CI e registrar ADR.**
   - Ajuste `[project].name`, `[packs].enabled`, `[secrets].extra_patterns` (sem valores reais) e gates da stack em `harness.toml` (lista `argv`, `fast = true` apenas nos rápidos), sem enfraquecer `harness/core.toml`.
   - Revise `.github/workflows/harness-verify.yml`: verifique se o gate de CI está íntegro (sem secrets, Actions fixadas por SHA). Nunca enfraqueça o workflow de CI sem aprovação explícita do humano.
   - Registre o perfil escolhido, packs ativos e convenções de contexto/contratos em `docs/adr/`.
10. **Validar nos sensores.** No repositório alvo, execute `python scripts/harness/doctor.py`, `python scripts/harness/check_structure.py` e `python scripts/harness/verify.py`. Todos devem retornar código `0` (incluindo verificação de integridade de ponteiros no `AGENTS.md`); apresente a saída real.

## Contrato de Saída

- Perfil selecionado (**Perfil 1**, **Perfil 2** ou **Perfil 3**) com justificativa objetiva pelos 4 critérios.
- Lista de arquivos gravados pelo `init` e packs ativos em `harness.toml`.
- Camada Quente (`AGENTS.md`, `product.md`, `tech.md`, `structure.md`) sem "A definir" e dentro do orçamento de linhas/bytes.
- Camada Morna (`trigger: glob`) e Camada Fria (`docs/context/` + `contracts/`/`schemas/`) criadas ou migradas quando **Perfil 3**, devidamente indexadas no `AGENTS.md`.
- ADR registrada em `docs/adr/` e saída real de `doctor.py`, `check_structure.py` e `verify.py` com código `0`.
