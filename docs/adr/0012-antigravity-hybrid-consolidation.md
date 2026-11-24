# ADR-0012: Consolidação Antigravity-First (Plugin Global e Kit Local)

- Date: 2026-11-12
- Status: Accepted (supersedes multi-IDE sync in ADR-0001 and CI push distribution in ADR-0010)

## Contexto

A extração dos 144 itens lógicos (`docs/COMPATIBILITY_MATRIX.md`) demonstrou que o fluxo ativo deste ambiente opera exclusivamente no **Google Antigravity** (CLI, IDE e plataforma 2.0). A manutenção paralela de adaptadores para `.claude/`, `.codex/` e `.kiro/` (`sync_adapters.py`), bem como automação de PRs via `.github/workflows/propagate.yml`, GitHub App e `.harness/lock.toml` (ADR-0010), adicionava acoplamento frágil sem ganho operacional.

Além disso, a análise cruzada dos payloads reais e da especificação oficial do Antigravity identificou pontos críticos:
1. Em `PreToolUse`, respostas `{"decision": "allow"}` pulavam confirmações do usuário.
2. No Antigravity IDE, `PostToolUse` pode omitir `toolCall` e espera `{}`; `SessionStart` usa `{"injectSteps": ...}`.
3. `Stop` exige avaliação conjunta de `continuationActive` e `terminationReason` (incluindo variantes CLI uppercase e IDE lowercase).

## Decisão

1. Adotar modelo híbrido nativo Antigravity:
   - **`plugin/`** empacota regras universais em PT-BR (`<= 24000` bytes), skills sem scripts duplicados e subagentes nativos (`agents/*.md` com `subagent: true`, `mainAgent: false`, ferramentas em lista YAML).
   - **`scripts/harness/init.py` (`cli.py init`)** projeta sob demanda `.agents/hooks.json`, `harness/core.toml`, `harness.toml`, runtime `stdlib-only` e packs opt-in (`python`, `node`, `web-ui`, `research-guard`).
2. Remover completamente `sync_adapters.py`, `.claude/`, `.kiro/`, `.codex/`, `.harness/lock.toml`, `distribute.py`, `distribution.toml` e `.github/workflows/propagate.yml`.
3. Preservar gerenciamento manual externo de servidores MCP (como `notebooklm`) fora de `plugin/`.

## Consequências

- Eliminação de código morto multi-IDE e fim da necessidade de sincronização entre cópias de regras/skills.
- Manutenção e testes concentrados exclusivamente nos contratos reais do Antigravity CLI/IDE/2.0.
- Reposicionamento dos documentos de pesquisa em `docs/research/`, isentos no `harness.toml` apenas deste repositório fonte.
