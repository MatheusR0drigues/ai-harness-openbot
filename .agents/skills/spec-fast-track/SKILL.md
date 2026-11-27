---
name: spec-fast-track
description: "Fluxo inline para tarefas Tier 1 (escopo fechado em poucos arquivos, sem mudança de contrato ou superfície de segurança), com plano curto no chat, zero arquivos em specs/ e verify --fast."
---

# Spec Fast-Track (Tier 1)

Fluxo econômico para aproximadamente 80% das tarefas do dia a dia: correções pontuais, melhorias localizadas e ajustes de baixo risco que não alteram contratos externos, esquemas de dados, dependências ou controles de segurança.

## Critério de Entrada (Triagem Tier 1)

Use esta skill **somente** quando todas as condições forem verdadeiras:

1. Mudança estimada em poucos arquivos relacionados (tipicamente 1 a 5 arquivos no mesmo módulo ou domínio).
2. Nenhum contrato público de API, esquema de dados, migração de banco ou arquitetura alterada.
3. Nenhuma nova dependência, superfície de autenticação, rede, entrada externa, PII, segredo, permissão, hook ou regra de segurança envolvida.
4. Requisitos claros sem ambiguidade estrutural.

Se qualquer item falhar, promova imediatamente para `../spec-driven/SKILL.md` (Tier 2).

## Protocolo de Execução (Inline)

1. **Plano curto no chat (3 a 6 linhas):**
   - **Objetivo:** uma frase direta sobre o resultado esperado.
   - **Escopo:** lista exata dos arquivos-alvo e o que fica explicitamente fora.
   - **Critérios verificáveis (EARS curto):** 1 a 3 bullets no formato `QUANDO <evento> O sistema DEVE <comportamento>`.
   - **Não crie** pasta ou arquivo em `specs/` para economizar contexto e evitar churn documental.

2. **Localização econômica (opcional):**
   - Para 1–2 arquivos conhecidos, leia apenas os trechos relevantes diretamente (`StartLine`/`EndLine`).
   - Para localizar símbolos em múltiplos módulos sem poluir o contexto principal, delegue ao subagente `researcher` com `Model="flash"` ou `"flash_lite"` pedindo apenas lista de `arquivo:linha` e assinaturas.

3. **Implementação delegada com Hydrogen Routing:**
   - Para tarefa simples e bem delimitada, invoque o subagente `implementer` com `Model="flash"`, passando apenas o mini-plano e os trechos necessários (Observation Masking).
   - Se o `verify --fast` ou teste unitário falhar na 1ª tentativa, escale a próxima tentativa para `Model="inherit"` (modelo principal/pro).
   - Se falhar 2 vezes consecutivas pela mesma causa, pare pelo ciclo Anti-Loop e reavalie a abordagem com o usuário.

4. **Verificação rápida e fechamento:**
   - Execute os testes direcionados à mudança e o sensor rápido (`uv run python scripts/harness/verify.py --fast` ou equivalente do projeto).
   - Revise `git diff --stat` e o diff alterado garantindo zero código morto, zero comentários temporais e nenhum arquivo fora do escopo.
   - Faça `git commit` na branch da worktree após o `verify --fast` verde; ao encerrar a demanda, faça push da branch e peça permissão explícita antes de abrir o PR.
   - Não é obrigatório acionar `code-reviewer` ou `security-auditor` em Tier 1 puro, salvo dúvida objetiva do autor ou risco percebido.

## Critério de Pronto (Tier 1)

- [ ] Critérios EARS do mini-plano cobertos por testes determinísticos (ou teste de regressão em caso de bug).
- [ ] `verify --fast` (e suíte afetada) com código de saída `0` após a última edição.
- [ ] `git diff --stat` conferido, sem alterações fora do escopo nem artefatos residuais em `specs/`.

## Orquestração OpenBot (`start_task`, `git worktree` e `run_workflow`)

- Isole cada execução em `git worktree` dedicada (`../wt-<repo>-<slug>`) via `start_task` (mantendo `1 Gerente por repositório`); nunca edite no checkout principal nem em `main`/`master`.
- Commits por tarefa concluída e push em branch de feature são livres; para abrir PR ao fim da demanda, execute `pr_via_rest_api.py --request-approval`, marque `PR_PENDING_APPROVAL` via `workflows/spec_dag_runner.py mark-pr` e aguarde aprovação explícita.
- Em ondas Topológicas Nível 2, acione `run_workflow` executando `workflows/spec_dag_runner.py` (`python workflows/spec_dag_runner.py --tasks specs/<feature>/tasks.md --feature <feature>`), que coordena `dag_runner.py` e persiste estado e vereditos vinculados a `commit_sha` nas tabelas SQLite `harness_tasks` e `harness_verdicts`.
