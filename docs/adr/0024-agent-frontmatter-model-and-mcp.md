# ADR-0024: Frontmatter de agentes: `model` ausente e ferramentas MCP

- Date: 2026-11-18
- Status: Accepted

## Context

No Export Claude, o frontmatter dos agentes em `plugin/agents/*.md` e `.claude/agents/*.md` é validado por dois patches de `tools/export_claude.py` sobre `scripts/harness/check_structure.py`: `check_structure:plugin-agent-fields` e `check_structure:check-agent-tools`. Sem `model`, o valor virava `""` e o gate `structure` reprovava com ```model `` must be haiku, sonnet or inherit```, embora o Claude Code trate `model` ausente como herança do modelo da sessão. Ferramenta fora de `ANY_AGENT_TOOLS` gerava `unknown tools ... (known: ...)`, o que reprovava agentes locais dos adotantes com ferramentas MCP de leitura no formato `mcp__<servidor>__<ferramenta>`.

O upstream não lê `model` em `_check_plugin_agent` e valida ferramentas pela matriz fechada `AGENT_TOOLS`. O dialeto Antigravity não tem nome de ferramenta MCP documentado para frontmatter de agente; a forma `mcp_<servidor>_<ferramenta>` só aparece em payloads sintéticos de hook nos testes, sem contrato.

## Decision

No dialeto Claude, `model` ausente equivale a `inherit` e ferramentas MCP bem formadas são aceitas, exceto nos agentes de revisão.

1. O patch `check_structure:plugin-agent-fields` lê `meta.get("model", "inherit")`. `model` presente fora de `haiku`, `sonnet` e `inherit` mantém a mensagem anterior.
2. O patch `check_structure:check-agent-tools` emite `MCP_TOOL_PATTERN = re.compile(r"^mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+$")`. Ferramenta que casa por `fullmatch` é aceita como conhecida. Nome iniciado por `mcp__` que não casa (por exemplo `mcp__a`, `mcp__a__` ou `mcp__a b__c`) continua gerando `unknown tools ... (known: ...)`.
3. Em `AUDITOR_AGENTS` (`code-reviewer` e `security-auditor`), cada ferramenta MCP gera `<where>: review agent <nome> must not use MCP tool <ferramenta>`. A regra de agentes somente leitura e a matriz `CLAUDE_AGENT_TOOLS` não mudam, então o revisor com MCP também recebe a mensagem de ferramenta não permitida.
4. O dialeto Antigravity não muda: o upstream continua sem validar `model`, e revisor com ferramenta fora da matriz continua reprovado. `tests/harness/test_check_structure.py::test_plugin_agent_without_model_passes` e `::test_reviewer_with_mcp_tool_fails` fixam esse comportamento.
5. No export, `TEST_CHECK_STRUCTURE_PY` em `tools/_claude_templates.py` cobre os itens 1 a 3 com `test_local_agent_without_model_passes`, `test_invalid_model_fails`, `test_mcp_tool_accepted`, `test_malformed_mcp_tool_fails` e `test_reviewer_with_mcp_tool_fails`.

## Consequences

- Agentes locais sem `model` e com ferramentas MCP de leitura passam no gate `structure` do Export Claude sem edição do projeto.
- O kit confere só a forma do nome da ferramenta. Qual servidor MCP existe e o que a ferramenta faz continuam decisão do humano: o kit não adiciona servidor nem `mcp_config.json`, e a aprovação de servidor segue as regras de MCP09 e MCP03.
- Fica proibido usar ferramenta MCP em `code-reviewer` e `security-auditor`, para que a auditoria não dependa de ferramenta externa nem a exponha ao conteúdo revisado.
- Se o Antigravity documentar um formato de nome MCP para frontmatter de agente, a aceitação nesse dialeto exige outra ADR.
- A decisão vive só nos dois patches do export; reverter os patches desfaz a ADR sem tocar no upstream.
