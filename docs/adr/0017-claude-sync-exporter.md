# ADR-0017: Exportador Unidirecional, Sincronizacao Continua e Modelo de Seguranca para Claude Code

- Date: 2026-11-14
- Status: Accepted

## Context

A adocao do Claude Code como ambiente de desenvolvimento assistido por IA ao lado do Google Antigravity trouxe a necessidade de disponibilizar as mesmas regras de engenharia, skills especializadas, subagentes nativos e o runtime deterministico de hooks e guardas do `ai-harness` para desenvolvedores que utilizam a interface do Claude Code.

Entretanto, as duas plataformas possuem dialetos e contratos distintos:
1. **Formato de instrucao e contexto:** Antigravity utiliza `AGENTS.md` e regras ativadas por `trigger: glob` em `.agents/rules/`; Claude Code utiliza `CLAUDE.md`, regras em `.claude/rules/` com frontmatter YAML `paths:` e configuracoes em `.claude/settings.json`.
2. **Subagentes e ferramentas:** Antigravity expressa subagentes com `mainAgent`, `subagent` e comunicacao via `send_message`; Claude Code utiliza campos nativos `tools:` e `model:` (com nomes de modelos especificos da familia Claude como `haiku` e `sonnet`).
3. **Contrato de hooks:** PreToolUse no Antigravity responde em JSON via `stdout` (`{"decision": "deny"}`) com exit code `0`; Claude Code exige encerramento com codigo de saida `2` e mensagem explicativa em `stderr` para bloquear a chamada da ferramenta.
4. **Acoplamento de repositorios:** Misturar a configuracao das duas ferramentas na mesma arvore Versionada poluiria os arquivos de instrucao, aumentaria o overhead de contexto (*Lost-in-the-Middle* e *Context Rot*) e violaria o principio de separacao limpa e a proibicao de edicao de `scripts/harness/cli.py` na Fonte Canonica (`ADR-0009`).

## Decision

1. **D1 — Fonte Canonica Unica e Transpilador Unidirecional (`tools/export_claude.py`):**
   Manter `ai-harness` como a Fonte Canonica unica e verdadeira do harness. Criar um transpilador deterministico `tools/export_claude.py` que gera o repositorio derivado e independente `ai-harness-claude` a cada atualizacao na branch `main`. A Fonte Canonica mantem seu `cli.py` e estruturas Antigravity intocados (`ADR-0009`), eliminando o custo e o risco de manutencao manual duplicada. Alternativa descartada: repositorio unico hibrido in-place, que misturaria dialetos e degradaria a janela de contexto de ambas as IDEs.

2. **D2 — Isolamento Puro por Repositorio:**
   Separacao estrita por repositorio: `ai-harness` inicializa e atende apenas o Google Antigravity; `ai-harness-claude` inicializa e atende apenas o Claude Code. O pacote exportado omite os arquivos brutos da Etapa 1 (`raw/`), os catalogos de migracao (`docs/INVENTARIO.md`, `docs/COMPATIBILITY_MATRIX.md`, `docs/inventory.json`, `docs/roadmap.md`) e os diretorios de governanca Antigravity (`.agents/`). Alternativa descartada: flag `--agent both` no mesmo script de inicializacao.

3. **D3 — Suporte Duplo de Consumo Global no Claude Code:**
   Disponibilizar no `ai-harness-claude` tanto o manifesto `.claude-plugin/plugin.json` (para utilizacao como plugin nativo do Claude Code) quanto o subcomando `cli.py install-global` (que projeta `CLAUDE.md`, regras de baseline e subagentes nativos em `~/.claude/`). Isso garante paridade com o modelo global do Antigravity, cobrindo sessoes globais em qualquer projeto local. Alternativa descartada: disponibilizar apenas `.claude-plugin/plugin.json`, que deixaria instrucoes globais fora do alcance do usuario.

4. **D4 — Roteamento de Modelos em Subagentes Claude:**
   Definir modelos especificos nos subagentes do Claude Code para balancear custo de leitura e taxa de sucesso na primeira tentativa (`Pass@1`):
   - `researcher`: modelo `haiku` (leitura barata de tokens e mapeamento eficiente);
   - `implementer`: modelo `sonnet` (alta precisao e fidelidade na geracao e edicao cirurgica de codigo);
   - `planner`, `code-reviewer`, `security-auditor` e especialistas de arquitetura: modelo `inherit` (utilizam o modelo principal configurado pelo usuario).
   Alternativa descartada: `implementer` em `haiku` (menor acuracia) ou todos em `inherit` (consumo excessivo de tokens em buscas).

5. **D5 — Publicacao Continua via Push Direto no CI e Modelo de Seguranca com Deploy Key SSH:**
   Publicar continuamente as alteracoes na branch `main` do `ai-harness-claude` via workflow GitHub Actions (`.github/workflows/sync-claude.yml`), acionado em `push` na branch `main` e `workflow_dispatch`. O workflow implementa o seguinte modelo de seguranca:
   - **Menor Privilegio (SSH Deploy Key):** A autenticacao utiliza uma Deploy Key SSH dedicada (`CLAUDE_SYNC_SSH_KEY`) com permissao de escrita restrita exclusivamente ao repositorio `ai-harness-claude`. Nao ha permissao de acesso ao repositorio canônico `ai-harness` nem a outros repositorios da conta (eliminando os riscos de vazamento de um Personal Access Token com escopo amplo).
   - **Isolamento Efemero no Runner:** O segredo `CLAUDE_SYNC_SSH_KEY` e injetado via variavel de ambiente do step (`env:`), gravado em diretorio temporario criado com `mktemp -d` (`chmod 700`) e arquivo de chave com permissoes restritas `chmod 600`. Ao finalizar o step (com sucesso ou falha), o diretorio e removido deterministicamente via `trap 'rm -rf "$SSH_DIR"' EXIT`.
   - **Verificacao Criptografica de Host (`known_hosts`):** Em conformidade com as regras de seguranca de rede, a chave publica do host `github.com` e obtida via `ssh-keyscan -t ed25519` e tem seu fingerprint SHA256 validado estritamente contra o fingerprint oficial do GitHub (`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`) com `ssh-keygen -lf` antes de ser aceita no `UserKnownHostsFile`. Conexoes SSH utilizam `StrictHostKeyChecking=yes` e `IdentitiesOnly=yes`.
   - **Gate Duplo Pre-Push:** Antes de qualquer conexao SSH ou operacao de rede, o workflow executa a suite de verificacao completa (`uv run python scripts/harness/verify.py`) na Fonte Canonica E executa a verificacao completa (`verify.py` e `pytest`) dentro do pacote Claude recem-exportado em `$RUNNER_TEMP/ai-harness-claude`. Se qualquer teste ou gate falhar, a pipeline encerra imediatamente e nada e publicado.
   - **Sincronizacao Idempotente e Segura:** O commit e o push ocorrem somente se `git status --porcelain` detectar modificacoes reais no diretorio de sincronizacao. E proibido o uso de `--force` ou `--no-verify`.

## Consequences

- O desenvolvimento de novas capacidades, regras e skills continua centralizado em um unico repositorio canonico (`ai-harness`), mantendo total fidelidade arquitetural.
- Os usuarios do Claude Code recebem atualizacoes automaticas sem intervencao manual e com garantia de verificacao previa por todos os gates do harness.
- O repositorio exportado permanece enxuto e livre de dados brutos ou artefatos legados.
- Fica proibido editar o pacote Claude diretamente no repositorio espelho: toda e qualquer alteracao deve ser feita na Fonte Canonica e propagada via pipeline.
- Fica proibido o uso de tokens pessoais amplos (PATs), bypass de verificacao de host SSH ou execucao de push forcado na sincronizacao.
