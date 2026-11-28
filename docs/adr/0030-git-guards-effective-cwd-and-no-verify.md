# ADR-0030: Diretório Efetivo em Comandos Encadeados e `--no-verify` em Todos os Subcomandos de Git

- Date: 2026-11-28
- Status: Accepted

## Context

A auditoria da adoção do kit no `databricks-etl` mostrou duas lacunas em `scripts/harness/guards.py`:

1. `git_workflow` (ADR-0029) tirava o diretório de `git commit`/`git push` só do `cwd` do evento ou de `git -C`. `cd <checkout principal> && git commit -m x`, disparado de uma worktree de feature, saía com `0`. O mesmo valia para alvos relativos de `privileged_config` e `harness_integrity` (`cd scripts/harness && git diff --output guards.py`).
2. `dangerous_shell` só tratava `--no-verify` em `git commit`. `git push --no-verify`, `git merge --no-verify`, `git rebase --no-verify`, `git pull --no-verify` e `git am --no-verify` pulavam hooks.

## Decision

Rastrear o diretório efetivo de cada segmento encadeado e bloquear `--no-verify` em todo subcomando de git que o aceita:

- `_parse_commands` marca cada segmento com escopo de shell (wrapper ou `$(...)` abre escopo filho) e com a marca de segundo plano (`&`). `_segment_cwds` aplica `cd`, `chdir`, `pushd`, `popd`, `Set-Location`, `sl`, `Push-Location` e `Pop-Location`, resolvendo caminho relativo contra o diretório corrente do encadeamento.
- Diretório não resolvido (variável, `$(...)`, crase, `~`, `-`, sem argumento, `popd` sem `pushd`, `cd` em grupo, pipeline, segundo plano ou shell aninhado) falha fechado para `git commit` e `git push`, salvo `git -C` absoluto.
- Todas as guardas passam a ver o comando dentro de `builtin`/`time` e de corpos de palavra-chave (`then`, `do`, `else`, braços de `case`, `if (...) { ... }`) e de funções (`f() { ... }`, `function f { ... }`); `cd` nesses corpos deixa o diretório não resolvido, e `git commit`/`git push` dentro de função são avaliados com diretório não resolvido, porque a função pode rodar depois de outro `cd`. `&` em redirecionamento (`2>&1`, `&>arquivo`) deixa de ser lido como job em segundo plano.
- `privileged_config` e `harness_integrity` avaliam cada segmento contra o `cwd` do evento **e** o diretório efetivo; nunca menos do que antes.
- `dangerous_shell` bloqueia `--no-verify` (e prefixos não ambíguos como `--no-verif`) em `commit`, `push`, `merge`, `rebase`, `pull` e `am`; `-n` só conta em `commit` (em `push` é `--dry-run`; em `merge`/`rebase`, `--no-stat`).

## Consequences

- `cd <principal> && git commit`, `bash -c "cd <principal> && git commit"` e `git push --no-verify` passam a ser bloqueados; `cd <worktree-feature> && git commit` continua livre.
- Falsos positivos aceitos por falha fechada: `(cd x) && git commit`, `cd $X && git commit` mesmo quando `$X` é a worktree certa, e linhas de mensagem de commit iniciadas por `cd` dentro de `$(...)`. O contorno é rodar na worktree ou usar `git -C <caminho absoluto>`.
- `env -C`/`--chdir`, `git --work-tree` e `GIT_DIR`/`GIT_WORK_TREE` exportados continuam fora do rastreio, assim como funções definidas em chamadas anteriores e scriptblocks em variável.
- `required_guards` em `harness/core.toml` não muda; `harness/baseline.json` precisa de refresh pelo humano no mesmo conjunto de mudanças.
- Repositórios com o kit (ex.: `databricks-etl`) recebem a correção com `python scripts/harness/cli.py init --force`.
