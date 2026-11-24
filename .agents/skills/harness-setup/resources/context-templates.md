# Templates de Contexto e Guia de Migração (Perfil 3)

Use estes moldes apenas quando o repositório for classificado como **Perfil 3 — Domínio Rico / Plataforma** (ou ao migrar uma estrutura legada), mantendo a **Camada Quente** (`AGENTS.md`, `product.md`, `tech.md`, `structure.md`) enxuta para preservar *Prefix Caching* e evitar *Context Rot*.

---

## Template 1 — Regra de Subdomínio/Camada (`trigger: glob`) em `.agents/rules/<camada>.md`

Crie apenas para camadas ou subdomínios com invariantes próprias que não devem carregar quando o agente trabalha em outros módulos (**Camada Morna**). Mantenha abaixo de `24000` bytes.

```markdown
---
trigger: glob
globs: "src/<camada>/**"
description: "Invariantes e contratos especificos da camada ou subdominio <camada>."
---

# Regras da Camada `<camada>`

## Fronteira e Responsabilidade

- **Pertence aqui:** <tipos de componentes, jobs ou módulos desta pasta>.
- **Não pertence aqui:** <responsabilidades de outras camadas ou serviços>.

## Invariantes Obrigatórias

- <Regra verificável 1 (ex.: granularidade, chave primária, idempotência ou validação de schema).>
- <Regra verificável 2 (ex.: tratamento de NULL, quarentena, mascaramento de PII).>

## Proibições

- <Anti-padrão crítico 1 (ex.: nunca cruzar fronteira direta para camada/schema vizinho sem contrato).>
- <Anti-padrão crítico 2.>
```

---

## Template 2 — Resumo de Pipelines / Mapa de Domínio (`docs/context/pipeline-summary.md`)

**Camada Fria (leitura sob demanda via `read_file`).** Indexe no `AGENTS.md` indicando ao agente ler antes de criar ou alterar fluxos de dados.

```markdown
# Resumo de Pipelines e Fluxos de Domínio

> **Quando consultar:** antes de adicionar, alterar ou depurar pipelines, jobs ou agendamentos.

| Pipeline / Fluxo | Origem -> Destino | Grão / Chave | Cadência / SLA | Regras Críticas |
| :--- | :--- | :--- | :--- | :--- |
| `<nome-pipeline>` | `<fonte>` -> `<tabela/tópico destino>` | `<1 linha por ... / chave>` | `<ex.: horário, diário>` | `<idempotência, quarentena, backfill>` |
```

---

## Template 3 — Catálogo de Dados (`docs/context/data-catalog.md`)

**Camada Fria (leitura sob demanda).** Evita despejar nomes de tabelas e esquemas nas regras `always_on`.

```markdown
# Catálogo de Dados e Ativos

> **Quando consultar:** ao modelar queries, contratos, transformações ou investigar linhagem de tabelas.

| Tabela / Ativo | Camada | Chave Primária / Partição | PII / Mascaramento | Consumidores |
| :--- | :--- | :--- | :--- | :--- |
| `<catalogo.schema.tabela>` | `<bronze / silver / gold / app>` | `<chave / cluster / partição>` | `<nenhum / hash / mascarado>` | `<BI, API, MCP, downstream>` |
```

---

## Template 4 — Integrações Externas (`docs/context/integrations.md`)

**Camada Fria (leitura sob demanda).** Documenta fronteiras externas sem expor valores de credenciais (apenas nomes de variáveis de ambiente ou segredos).

```markdown
# Integrações Externas e Fronteiras de Rede

> **Quando consultar:** ao alterar clientes HTTP, webhooks, conectores, filas ou provedores externos.

| Sistema / API | Autenticação (env / Secret Manager) | Timeouts / Limites | Contrato em `contracts/` ou `schemas/` |
| :--- | :--- | :--- | :--- |
| `<nome-servico>` | `<NOME_VAR_ENV ou secret-id>` | `<timeout Xs, rate limit, retry c/ jitter>` | `contracts/<dominio>.yaml` |
```

---

## Mapeamento para Migração de Repositórios Existentes

Ao adotar o padrão do `ai-harness` em um repositório que já acumulou arquivos de contexto em pastas ad-hoc (`memory/`, `context/`, `knowledge/` ou pastas de outros agentes), consolide seguindo esta tabela:

| Origem Legada | Destino Canônico (`ai-harness`) | Camada / Trigger | Regra de Higienização |
| :--- | :--- | :--- | :--- |
| `memory/tech-stack.md` | `.agents/rules/tech.md` | Camada Quente (`always_on`) | Enxugar para linguagens, versões fixadas e gerenciador de pacotes (`<= 80` linhas) |
| `memory/architecture-decisions.md` | `docs/adr/NNNN-<titulo>.md` | Camada Fria (`read_file`) | Quebrar decisões históricas em ADRs individuais ou consolidar histórico congelado |
| `knowledge/mistakes.md` | Manter: o próprio arquivo. Adotar: `.agents/rules/anti-patterns.md` | Camada Morna (`model_decision`) | Duas opções de `M-06` em `resources/adocao.md`. Manter: `[init] skip_templates = ["anti-patterns"]` e ponteiro no `AGENTS.md`, sem converter o formato. Adotar: converter as entradas para o formato `AP-NNN` (`Sintoma / Causa raiz / Correção / Prevenção`) só quando o humano escolhe adotar `anti-patterns.md` |
| `context/<topologia>.md` | `docs/context/<topologia>.md` | Camada Fria (`read_file`) | Indexar na seção `## Mapa de Conhecimento` do `AGENTS.md` com critério explícito de consulta |
| Regras locais de subdomínio/camada | `.agents/rules/<camada>.md` | Camada Morna (`trigger: glob`) | Declarar `globs` estrito (ex.: `"src/silver/**"`) e manter abaixo de `24000` bytes |
| Contratos/ontologias lidos em produção | `contracts/<dominio>.*` ou `schemas/<dominio>.*` | Artefato de código / runtime | Remover imediatamente de pastas de governança de agente para evitar quebra em produção |
