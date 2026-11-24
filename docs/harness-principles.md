# Princípios do Harness (`ai-harness`)

Este documento resume a fundamentação técnica adotada na arquitetura híbrida **Plugin Global OpenBot (`plugin/`) + Kit Local Stdlib (`scripts/harness/`)**, atualizada com base nos estudos de cibernética, engenharia de contexto, roteamento de modelos e segurança agêntica consolidados antes da Etapa 4 (`docs/adr/0015-domain-packs-and-3-tier-routing.md`).

## Agente = Modelo + Harness

Modelos de fronteira atingiram comoditização próxima em tarefas isoladas; a diferença real em produção vem do ambiente que orienta, restringe e verifica o agente. O harness converte disciplina de engenharia em mecanismos reproduzíveis, reduzindo a variância estocástica sem transformar o dia a dia em burocracia.

## Teoria Cibernética de Controle: Guias e Sensores

Um harness opera como regulador cibernético ancorado na **Lei da Variedade Requisita de Ashby** e em malhas de retroalimentação (**Wiener**):

1. **Guias (*Feedforward*):** `AGENTS.md`, regras em `plugin/rules/` e regras locais do repositório, skills em `plugin/skills/` e definições em `plugin/agents/` maximizam a chance de acerto na primeira tentativa (`Pass@1`).
2. **Sensores computacionais (*Feedback* determinístico):** hooks (`PreToolUse`, `Stop`, `SessionStart`) e gates em `harness/core.toml` + `harness.toml` (`scripts/harness/verify.py`) verificam determinismo, segredos, riscos estáticos, especificações EARS, estrutura e integridade SHA-256 (`scripts/harness/check_tamper.py`). Mensagens de falha incluem dicas acionáveis para o próximo turno.
3. **Sensores inferenciais (*Feedback* semântico):** revisão independente (`plugin/skills/review/SKILL.md` com `code-reviewer` e `security-auditor`) executada apenas quando os sensores computacionais estão verdes e o risco da tarefa (Tier 2) exige auditoria completa.

## Três Pilares de Regulação

1. **Engenharia de Contexto e Manutenibilidade:** manter janelas enxutas (`AGENTS.md` alvo `<= 150` linhas, limite `200`; regras `< 24000` bytes), formatação/lint/tipagem estrita (`ruff`, `pyright`), limpeza de comentários temporais e controle explícito de memória entre sessões.
2. **Restrições Arquiteturais (*Fitness Functions*):** `scripts/harness/check_structure.py` valida contratos estruturais, isolamentos do plugin e referências; analisadores AST dos packs verificam runtime `stdlib-only`, determinismo de testes e anti-padrões específicos de domínio.
3. **Controle de Entropia e Comportamento:** requisitos EARS bilíngues (`DEVE` / `SHALL`), seção `## Segurança` obrigatória no design, DAG de tarefas sem ciclos ou dependências de opcionais e ciclo anti-loop de 2 falhas consecutivas.

## Arquitetura Defensiva de Contexto

Para evitar degradação por contexto longo (*context rot*), *lost-in-the-middle* e desperdício de tokens:

- **Ordenação para *Prefix Caching*:** regras universais estáticas no início, contexto do projeto em seguida e diffs/tarefa atual sempre ao final, sem timestamps ou IDs voláteis antes de blocos fixos.
- **Anti-*Lost-in-the-Middle*:** critérios de aceite e restrições críticas aparecem nas extremidades do prompt (início e fim), nunca soterrados no meio de blocos longos.
- **Revelação Progressiva (*Progressive Disclosure*):** regras sob demanda (`glob` / `model_decision`), skills carregadas apenas quando acionadas e mapeamento sintético de código antes de leituras amplas (`repo-map`).
- **Paginação de Memória Virtual (`progress.md`):** bloco de estado ativo enxuto no topo (`Core State`), decisões recentes em seguida (`Recall`) e histórico antigo arquivado em ADRs ou no `design.md`.
- ***Observation Masking*:** subagentes e ferramentas reportam apenas achados estruturados com `arquivo:linha` e trechos mínimos relevantes, nunca despejando arquivos inteiros no coordenador.

## Fluxo Operacional em 3 Tiers e Roteamento Híbrido (Hydrogen)

O rigor do harness é proporcional ao risco e ao raio de explosão da tarefa, evitando revisões massivas em mudanças simples:

| Tier | Escopo típico | Planejamento & Memória | Modelo nos Subagentes | Verificação |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 0 — Micro** | 1–2 arquivos triviais (texto, flag, ajuste local) | Direto no chat, zero arquivos em `specs/` | Sem subagentes | `verify.py --fast` e inspeção do diff |
| **Tier 1 — Fast-Track** | ~80% do dia a dia: tarefa focalizada até 3–5 arquivos sem novo contrato externo, dependência ou risco de segurança | Plano curto inline no chat via `spec-fast-track`, zero arquivos em `specs/` | `researcher` em `flash`/`flash_lite`; `implementer` em `flash` (escala para `inherit`/`pro` na 1ª falha de gate) | `verify.py --fast` + releitura de `git diff --stat` (dispensa `code-reviewer`) |
| **Tier 2 — Spec-Driven Completo** | Feature nova, contrato/schema, arquitetura, >5 arquivos, dependência ou superfície sensível | `specs/<feature>/` (`requirements.md`, `design.md`, `tasks.md`, `progress.md`) + ADR se arquitetural | `planner` (`inherit`/`pro`), `researcher` (`flash`), `implementer` (`flash` por tarefa fechada; escala para `inherit`/`pro` se falhar) | `verify.py` completo + `code-reviewer` (`inherit`/`pro`) + `security-auditor` quando aplicável |

Na regra de escalonamento, se o `implementer` em modelo leve falhar 1 vez no `verify.py --fast`, a tentativa seguinte escala para `inherit` (`pro`); persistindo o mesmo erro na 2ª falha, o Ciclo Anti-Loop interrompe para análise de causa raiz ou consulta ao humano.

## Segurança Mecânica e Packs Opt-In

Instruções em linguagem natural falham sob pressão ou injeção indireta. Guardas `PreToolUse` falham fechados e bloqueiam segredos, exfiltração zero-click, comandos destrutivos e edição de superfícies privilegiadas (`.github/workflows/harness-verify.yml`, `harness/core.toml`, `harness/baseline.json`, `*mcp*.json`, `/data/OpenBot/Shared/ai-harness-openbot/`).

Os packs opcionais permanecem desacoplados em `harness/packs/` e entram apenas quando habilitados em `harness.toml`: `python`, `node`, `web-ui`, `research-guard`, `data-engineering` e `bi-pbip`. Os gates rápidos (`fast = true`) privilegiam análises `stdlib-only` em até poucos segundos para não travar o ciclo iterativo.

## 11. Arquitetura de Memória de Repositório (3 Camadas e 3 Perfis)

Para estender a higiene de contexto da sessão para o nível de cada repositório sem impor burocracia uniforme a projetos de portes diferentes (`docs/adr/0016-repository-context-profiles.md`), o `ai-harness` adota dois eixos complementares baseados em evidências empíricas (estudo da ETH Zurich mostrando que arquivos de instruções extensos degradam a inferência e elevam o custo de tokens em `+20%`, perda por *Context Rot* de `~2%` a cada `100k` tokens acumulados, *Lost-in-the-Middle* e particionamento estilo MemGPT/Letta em *Core*, *Recall* e *Archival Memory*):

1. **Particionamento em 3 Camadas de Memória:**
   - **Camada Quente (`Core Memory` — `always_on`):** `AGENTS.md` (`<= 150` linhas, limite `200`) como mapa topográfico estático e regras base em `.agents/rules/<core>.md` curtas, garantindo prefixo estável para *Prefix Caching* e proibindo dicionários de dados ou listas extensas inline.
   - **Camada Morna (`Scoped & Recall Memory` — `trigger: model_decision` / `glob`):** catálogo de falhas evitáveis (baseado em `harness/templates/anti-patterns.md`), regras dos packs ativos, regras segmentadas por subdomínio/camada via `trigger: glob` (`.agents/rules/<camada>.md`) e o estado ativo em `specs/<feature>/progress.md`.
   - **Camada Fria (`Archival Context` — sob demanda via `read_file`):** documentação topológica detalhada em `docs/context/<arquivo>.md` (catálogo de dados, resumo de pipelines, integrações externas) e decisões históricas em `docs/adr/`, listadas no `AGENTS.md` apenas como ponteiros com o critério exato de consulta.

2. **Escala de Maturidade em 3 Perfis (`harness-setup`):**
   - **Perfil 1 — Essencial (Low Ceremony):** utilitários, scripts, POCs e bibliotecas pequenas; apenas Camada Quente enxuta, catálogo de anti-padrões e packs, sem pastas extras em `docs/context/<arquivo>.md`.
   - **Perfil 2 — Engenharia Padrão (Standard):** microsserviços, APIs, BFFs, servidores MCP e apps web; Camada Quente completa, packs da stack, `docs/adr/` e `specs/` nos fluxos Tier 2.
   - **Perfil 3 — Domínio Rico / Plataforma (High-Context):** lakehouses, monólitos modulares, plataformas multi-domínio e projetos BI complexos; emprega as 3 camadas completas com regras por `trigger: glob`, `docs/context/<arquivo>.md` e avaliação de subagentes especialistas locais.

3. **Isolamento de Contratos de Runtime e Integridade de Ponteiros:**
   - Contratos, esquemas e ontologias consumidos em produção por outros sistemas ou servidores MCP residem exclusivamente em `contracts/<dominio>.*` ou `schemas/<dominio>.*` na raiz do repositório, nunca dentro de `.agents/` ou misturados em `docs/context/<arquivo>.md`.
   - O sensor `scripts/harness/check_structure.py` verifica deterministicamente que caminhos citados em crases (incluindo `contracts/<dominio>.*` e `schemas/<dominio>.*`) e alvos locais de links Markdown nos arquivos de governança (`AGENTS.md`, `README.md`, regras, skills e `docs/context/<arquivo>.md`) apontam para arquivos existentes no disco.
