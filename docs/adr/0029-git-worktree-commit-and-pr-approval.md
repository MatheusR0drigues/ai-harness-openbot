# ADR-0029: Fluxo Git com Worktrees Obrigatórias, Commit Livre e PR com Permissão

- Date: 2026-11-27
- Status: Accepted

## Context

A política anterior (`plugin/rules/AGENTS.md` §9 e `AGENTS.md`) proibia commits sem pedido explícito do usuário e não impunha o uso de `git worktree` isolada nos guardas de Antigravity e Claude Code. Além disso, `guards.repo_relative` resolvia caminhos apenas contra `REPO_ROOT`, fazendo com que edições em worktrees irmãs (`../wt-*`) ficassem invisíveis para `privileged_config` e `harness_integrity`. Por fim, no OpenBot (modo hookless sem `PreToolUse`), faltava uma trilha auditável para solicitação e aprovação humana antes da criação de Pull Requests via REST API.

## Decision

Adotar o fluxo **worktree dedicada -> commit livre por tarefa -> PR com permissão explícita** nos três alvos (Antigravity, Claude Code e OpenBot), com os seguintes controles:

1. **Visibilidade em worktrees (`guards.repo_relative`):** resolver caminhos dentro de worktrees vinculadas cujo `.git` aponte para `<root>/.git/worktrees/` usando apenas `stdlib`.
2. **Guarda `git_workflow` (`guards.ALL` e `harness/core.toml`):** bloquear `write` e `git commit` no checkout principal ou nas branches `main`/`master`, e bloquear `git push` envolvendo `main`/`master`, mantendo commits e pushes em branches de feature livres.
3. **Guarda `pr_confirmation` (`guards.CONFIRM` e `harness/core.toml`):** interceptar criação de PR (`gh pr create`, `pr_via_rest_api.py` sem `--request-approval`, `watch_worktree.py publish` e ferramentas MCP de criação de PR) emitindo `force_ask` no Antigravity e `hookSpecificOutput.permissionDecision = "ask"` no Claude Code, com `deny` tendo precedência e falha fechada em exceções.
4. **Aprovação auditável no OpenBot:** exigir `--request-approval` (sem rede) antes de `--approved-by` e `--approval-ref` em `plugin/scripts/pr_via_rest_api.py`, e registrar `PR_PENDING_APPROVAL` / `PR_OPENED` na tabela `harness_tasks` via `workflows/spec_dag_runner.py mark-pr`.

## Consequences

- Edições e commits em Antigravity e Claude Code passam a ocorrer exclusivamente em worktrees irmãs (`../wt-<repo>-<slug>`) em branches de feature, preservando `privileged_config` e `harness_integrity`.
- Commits por tarefa concluída e pushes em branches de feature ficam livres; abrir PR exige confirmação interativa (AGY/Claude) ou aprovação registrada (OpenBot).
- **Limite no modo hookless (OpenBot):** como o OpenBot não possui `PreToolUse` local, um agente autônomo tecnicamente consegue preencher `--approved-by` e `--approval-ref` por conta própria; a barreira criptográfica/hard-enforcement para bots sem hook depende de escopo restrito do token GitHub, proteção de branch no remoto ou política CEL no gateway externo (fora do escopo deste repositório).
