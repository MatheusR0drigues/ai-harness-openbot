# ADR-0027: Exportador Unidirecional, Dialeto Hookless CI-First e Workflows DAG para OpenBot

- Date: 2026-11-23
- Status: Accepted

## Context

A adoção do **Nightly Labs OpenBot** (`openbot-devinato`) ao lado do Google Antigravity e do Claude Code trouxe a necessidade de distribuir as regras universais em PT-BR, skills especializadas, subagentes nativos e sensores determinísticos do `ai-harness` para sessões gerenciadas pelo OpenBot.

Entretanto, o runtime do OpenBot possui restrições arquiteturais e operacionais próprias:

1. **Modelo *hookless*:** o OpenBot não executa `PreToolUse` local bloqueante baseado em `.agents/hooks.json`; a garantia determinística depende de execução explícita via `run_workflow`, verificação de adulteração (`check_tamper.py`) e gates de CI em Pull Requests.
2. **Primitivas de isolamento e colaboração:** o OpenBot opera com 1 Gerente por repositório, despacho de tarefas via `start_task` em *git worktrees* (`../wt-<feature>`), subagentes via `invoke_subagent` com `workspace: "share" | "inherit"`, entrada de workflow `run_workflow` e clone compartilhado em `/data/OpenBot/Shared/ai-harness-openbot`.
3. **Orçamento rígido de container:** o ambiente `openbot-devinato` opera com limites estreitos de memória (`4g` RAM) e processos (`512` PIDs), exigindo controle estrito de concorrência para evitar exaustão de recursos (`LLM10`).
4. **Integridade da Fonte Canônica (`ADR-0009` e `ADR-0017`):** misturar dialeto *hookless* na mesma árvore canônica degradaria a ergonomia e os hooks locais do Antigravity, além de violar a proibição de editar `scripts/harness/cli.py` na Fonte Canônica (`ADR-0009`).

## Decision

1. **D1 — Fonte Canônica Única (SSOT) e Transpilador Unidirecional (`tools/export_openbot.py`):**
   Manter `ai-harness` como SSOT Canônico do harness e criar o transpilador determinístico `stdlib-only` `tools/export_openbot.py` para gerar a árvore independente `ai-harness-openbot`, preservando `scripts/harness/cli.py` intocado na Fonte Canônica (`ADR-0009`). O espelho omite `raw/`, `tools/`, `.agents/hooks.json`, `harness/templates/hooks.antigravity.json`, `.claude/`, `.kiro/`, `.codex/`, catálogos da Etapa 1 e specs internas da Fonte Canônica, e recalcula `harness/baseline.json` com hashes SHA-256 em LF. Alternativa descartada: tornar o `ai-harness` *hookless* e extrair um espelho Antigravity, o que quebraria o fluxo local e `sync-claude.yml`.

2. **D2 — Dialeto Hookless / CI-First (`tools/openbot_dialect.py`) e Projeção de `.github/workflows/harness-verify.yml`:**
   Substituir apenas a costura de dialeto no alvo (`scripts/harness/dialect.py` $\leftarrow$ `tools/openbot_dialect.py`, com `DIALECT = "openbot"`, `AGENT = "openbot"` e `HOOKS_REL = ""`) para operar sem `.agents/hooks.json`. No alvo exportado, `cli.py init` projeta `.github/workflows/harness-verify.yml` (Actions fixadas por SHA-1 de 40 caracteres, `permissions: contents: read`, zero secrets, executando `check_tamper.py` e `verify.py` com Python `stdlib`), enquanto `check_tamper.py` e `harness/baseline.json` seguem protegendo `harness/core.toml` e `scripts/harness/*.py`. Alternativa descartada: manter `.agents/hooks.json` inerte no repositório OpenBot, o que geraria ruído em `check_structure.py` e `doctor.py`.

3. **D3 — Motor DAG Nível 2 (`dag_runner.py` e `workflows/spec_dag_runner.py`), Semáforo e Escalonamento Hydrogen:**
   Implementar o executor determinístico de `specs/<feature>/tasks.md` em **Ondas Topológicas Nível 2** combinadas com `start_task` em *git worktrees*. O motor rejeita ciclos, dependências desconhecidas e valores inválidos de paralelismo antes de invocar subagentes; aplica semáforo rígido `max_parallel_workers = 2` (teto máximo `4`, faixa permitida `1..4`) para proteger RAM/PIDs; e aplica escalonamento Hydrogen executando `implementer` em `flash` seguido de `python scripts/harness/verify.py --fast`, escalando uma única vez para `pro` (`inherit`) na 1ª falha e encerrando com `ANTI_LOOP_BLOCKED` na 2ª falha consecutiva.

4. **D4 — Skill `verify-app` (*Control-Glass*), Tabelas SQLite com `commit_sha` e Detecção *Ratchet*:**
   Incorporar a skill universal `plugin/skills/verify-app/SKILL.md` (protocolo *Control-Glass* em 5 etapas com porta isolada por *worktree*, checagem HTTP/TCP, mapa de rotas/seletores, browser integrado e encerramento apenas dos processos iniciados), exigindo saída estrita `VEREDITO: PASS`, `VEREDITO: FAIL` ou `VEREDITO: BLOCKED` (nunca `PASS` quando faltar ambiente ou credencial). Persistir em `sqlite3` (`stdlib`, queries parametrizadas) as tabelas compartilhadas `harness_tasks` e `harness_verdicts`, vinculando aprovações ao `commit_sha` via `is_verdict_current` e sinalizando candidatos *Ratchet* (`detect_ratchet_candidates`) quando uma `failure_category` acumular `>= 3` registros `FAIL`.

5. **D5 — Publicação Contínua via CI (`.github/workflows/sync-openbot.yml`) e Deploy Key SSH:**
   Sincronizar `ai-harness-openbot` em `push` para `main` e `workflow_dispatch` seguindo o modelo de segurança do `ADR-0017`: `permissions: contents: read`, todas as Actions fixadas por SHA-1 completo de 40 caracteres, sem interpolação de `${{ ... }}` em blocos `run:`, gate duplo obrigatório (`uv run python scripts/harness/verify.py` na Fonte Canônica e `verify.py` + `pytest` no pacote exportado em `$RUNNER_TEMP/ai-harness-openbot`) antes de qualquer operação de rede, e push autenticado exclusivamente por Deploy Key SSH (`OPENBOT_SYNC_SSH_KEY`) para `OPENBOT_SYNC_REPO` com diretório temporário `mktemp -d` (`chmod 700`/`600`), limpeza via `trap`, validação do fingerprint oficial do GitHub (`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`), `StrictHostKeyChecking=yes`, `IdentitiesOnly=yes` e proibição de `--force` ou `--no-verify`.

## Consequences

- A evolução de regras, skills, subagentes e sensores permanece centralizada em `ai-harness`, propagando automaticamente para `ai-harness-openbot` após gate duplo verde.
- Projetos inicializados pelo `ai-harness-openbot` recebem proteção determinística em CI (`.github/workflows/harness-verify.yml`) sem exigir configuração manual de secrets nem depender de hooks locais.
- A execução paralela de tarefas em Ondas DAG respeita o orçamento do container `openbot-devinato` e bloqueia aprovações obsoletas após novos commits.
- Fica proibido editar `ai-harness-openbot` diretamente no repositório espelho, alterar `scripts/harness/cli.py` na Fonte Canônica (`ADR-0009`), usar tokens amplos (PATs) ou `push --force` na sincronização e enfraquecer o limite do semáforo (`1..4`) ou o ciclo anti-loop.
