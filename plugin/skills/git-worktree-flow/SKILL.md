---
name: git-worktree-flow
description: "Padroniza o ciclo Git com worktree dedicada (../wt-<repo>-<slug>), commits livres após tarefas com verify --fast verde, push livre em branch de feature e pedido explícito de permissão para abrir Pull Request ao fim da demanda."
---

# Fluxo Git com Worktree e Permissão de PR (`git-worktree-flow`)

Define o ciclo padrão para qualquer alteração de código ou documentação no repositório, garantindo isolamento em `git worktree`, commits frequentes e controle humano na abertura de Pull Requests.

## 1. Preparação da Worktree

1. **Verifique o contexto atual** (guarda anti-aninhamento):
   - Compare `git rev-parse --git-dir` e `git rev-parse --git-common-dir`. Se forem iguais, você está no checkout principal — **não edite nem commite aí**.
2. **Crie uma worktree irmã fora da árvore principal:**
   ```bash
   git fetch origin
   git worktree add ../wt-<repo>-<slug> -b <feat|fix|chore>/<slug> origin/main
   ```
   (Em repositórios locais sem remoto `origin`, use `main` como base.)
3. **Instale dependências por worktree:**
   - Execute `uv sync` (ou `pnpm install` / `npm ci`) dentro da própria worktree.
   - **Nunca** crie symlinks de `.venv` ou `node_modules` entre worktrees.

## 2. Cadência de Commit e Push

- **Commit livre:** após concluir uma tarefa relevante ou um fluxo com `verify --fast` (ou suíte/lint rápido) verde, faça `git add` seletivo e `git commit` na branch da worktree.
- **Push livre em branch de feature:** `git push -u origin <feat|fix|chore>/<slug>` é livre para checkpoint remoto.
- **Proibido em `main`/`master`:** nunca edite, commite ou faça push direto para `main` ou `master`.

## 3. Abertura de Pull Request (Fim da Demanda)

- **Nunca abra PR sem permissão explícita.**
- No fim da demanda, após `verify` completo verde (e `review` / `security-auditor` com `VEREDITO: PASS` em Tier 2):
  1. Em **OpenBot / Claude Code**, o hook `PreToolUse` (`pr_confirmation`) solicita confirmação interativa (`force_ask` / `ask`) ao tentar abrir o PR.
  2. Em **OpenBot (sem hooks)**, execute `pr_via_rest_api.py --request-approval`, registre `PR_PENDING_APPROVAL` via `workflows/spec_dag_runner.py mark-pr` e aguarde aprovação explícita no canal antes de executar com `--approved-by` e `--approval-ref`.
  3. Apresente sempre: resumo objetivo, lista de commits, saída real de `verify` e veredito da revisão.

## 4. Limpeza Pós-Merge

- Nunca apague worktrees com `rm -rf`:
  ```bash
  git worktree remove ../wt-<repo>-<slug>
  git worktree prune
  ```
