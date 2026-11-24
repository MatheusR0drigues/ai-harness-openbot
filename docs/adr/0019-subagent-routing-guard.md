# ADR-0019: Guarda de Roteamento de Subagentes, Prevenção de Colisões e Proteção de Modelos

- Date: 2026-11-15
- Status: Accepted

## Context

O uso de subagentes no desenvolvimento assistido por IA traz ganhos expressivos de produtividade, mas expõe superfícies críticas de custo e segurança operacional quando não delimitado por controles determinísticos:

1. **Esgotamento de cota e consumo descontrolado (OWASP LLM10):** No Google Antigravity, subagentes do plugin não fixavam o parâmetro `Model` no frontmatter e chamadas à ferramenta `invoke_subagent` utilizavam `inherit` por padrão, herdando silenciosamente o modelo principal da sessão (frequentemente modelos pesados da família `pro`). No Claude Code, ferramentas nativas de subagente (`Agent` e `Task`) com tipos nativos (`general-purpose`, `Explore`, `Plan`, `claude`) herdavam o modelo da sessão (`opus`, `fable`). Em ambos os casos, tarefas puramente econômicas de leitura, pesquisa ou mapeamento (`researcher`, `Explore`) podiam disparar chamadas a modelos pesados e caros, resultando em risco concreto de denial-of-wallet e esgotamento precoce de cota.
2. **Vazamento de credenciais em prompts e briefs (OWASP LLM02):** Anteriormente, o despachante de eventos (`scripts/harness/payload.py`) não conhecia ferramentas de subagente (`invoke_subagent`, `swarm`, `Agent`, `Task`), classificando-as como `kind = "other"`. Como argumentos de subagentes trafegam prompts, instruções de contexto e briefs detalhados, era imprescindível assegurar que nenhuma credencial ou segredo literal pudesse ser encaminhado a um subagente sem passar pela guarda de segredos (`secret_in_write`).
3. **Colisões silenciosas de nomes locais vs. globais (OWASP ASI03):** O validador de estrutura (`scripts/harness/check_structure.py`) não auditava agentes criados localmente nos projetos (subpastas de agentes locais como .agents/agents/ ou .claude/agents/). Isso permitia que um arquivo local sobrescrevesse acidental ou intencionalmente agentes globais canônicos do plugin (`researcher`, `planner`, `implementer`, `code-reviewer`, `security-auditor`, `databricks-architect`, `claude-architect`, `github-architect`) ou agentes reservados da plataforma (`self`, `browser`, `research`, `deepagent`, `review-agent`), alterando instruções de segurança ou enfraquecendo papéis como o `security-auditor`.
4. **Desvios de fluxo e paralelismo não supervisionado:** O modo de planejamento nativo das IDEs (`/plan` ou Plan Mode) não possuía uma ponte determinística para o ciclo formal `spec-driven` e carecia de limites explícitos de concorrência, abrindo brechas para execuções paralelas em lote mecânico fora do plano.

## Decision

Em resposta aos riscos identificados, foram tomadas as seguintes decisões arquiteturais e operacionais:

### 1. Sondagem Empírica de Payloads em PreToolUse (D7)
Em estrita conformidade com a diretriz "Evidência ou Zero", antes de projetar os contratos e testes foi executada uma sondagem empírica dos formatos reais emitidos pelo runtime Antigravity no evento `PreToolUse`:
- `invoke_subagent`: tool call contendo no dicionário `args` os campos `TypeName` (tipo do subagente), `Model` (identificador do modelo solicitado), `Prompt` (instrução da tarefa) e `Role` (papel do subagente).
- `swarm`: tool call contendo no dicionário `args` os campos `action` (ações como `status`, `models`, `title`, `kill`, `add`, `model`), `brief` (descrição da atribuição) e `model` (modelo configurado para o worker).
- Paridade com o ecossistema Claude Code: as ferramentas nativas correspondentes `Agent` e `Task` (`subagent_type`, `model`, `prompt`, `description`) foram mapeadas com a mesma semântica. Fixtures de payload sintéticas foram gravadas em `tests/fixtures/payloads/antigravity/invoke_subagent.json` e `tests/fixtures/payloads/antigravity/swarm.json`.

### 2. Trava Determinística no Kit Local e Transpilação Claude (D1, D4)
Implementar a guarda `subagent_routing` diretamente no runtime do kit local (`scripts/harness/guards.py`) e na camada de parse de eventos (`scripts/harness/payload.py`). O plugin global (`plugin/`) permanece livre de hooks para preservar a conformidade com a [ADR-0012](0012-antigravity-hybrid-consolidation.md).
As políticas de roteamento de ambos os dialetos (Antigravity e Claude Code) residem unificadas no módulo canônico `scripts/harness/guards.py`, indexadas pelos nomes das ferramentas. O exportador `tools/export_claude.py` transpila a guarda e adapta apenas `KNOWN_KINDS` e caminhos de diretório, evitando substituições de código frágeis via `str.replace`.
*Alternativa descartada:* hooks globais em `~/.claude/settings.json` ou `~/.gemini/config/`, que violariam o isolamento por repositório e exigiriam configuração manual externa.

### 3. Normalização Estruturada e Varredura de Segredos (D6)
No módulo `scripts/harness/payload.py`:
- `KNOWN_KINDS` classifica `invoke_subagent`, `swarm`, `Agent` e `Task` com `kind = "subagent"`.
- O dataclass `Event` ganha campos tipados: `subagent_type`, `model` e `action`.
- Para chamadas com `kind == "subagent"`, o campo `content` é populado recursivamente com todas as strings dos argumentos (`_all_strings`), garantindo que a guarda `secret_in_write` (Guarda 1) inspecione integralmente prompts, briefs e descrições antes de permitir a chamada, prevenindo regressões de segurança.
- Chamadas malformadas (sem tipo de subagente identificável, ou `swarm` sem ação) falham fechado com `PayloadError` em `PreToolUse`.

### 4. Política de Modelos por Plataforma e Papel (D2, D5)
A guarda `subagent_routing` aplica a seguinte matriz de decisão determinística:
- **Claude Code (`Agent`, `Task`):**
  - Tipos nativos (`general-purpose`, `Explore`, `Plan`, `claude`): exigem modelo leve explícito contendo `haiku` ou `sonnet`. Omissão de modelo ou modelos pesados (`fable`, `opus`, `pro`, `inherit`) provocam bloqueio imediato (`exit code 2` com motivo em `stderr`).
  - Agentes especializados do plugin: modelos permitidos, pois já fixam modelo adequado no frontmatter.
- **Antigravity (`invoke_subagent`):**
  - Tipos nativos (`self`, `research`): exigem modelo leve explícito (`flash` ou `flash_lite`).
  - Subagente `researcher`: exige modelo leve explícito (`flash` ou `flash_lite`).
  - Subagente `implementer`: exige modelo explícito entre `flash`, `flash_lite` ou `inherit` (permitindo a escalada de Tier autorizada após falha de gate).
  - Outros subagentes (`planner`, `code-reviewer`, especialistas): execução permitida com os modelos previstos em seus papéis.
- **Antigravity (`swarm`):**
  - Ações somente leitura e encerramento (`status`, `models`, `title`, `kill`): liberadas.
  - Ações mutantes (`add` e `model`): exigem modelo leve explícito (`flash` ou `flash_lite`), fechando qualquer brecha de escalada de modelo após o worker ser instanciado.
*Alternativa descartada:* emitir apenas avisos não bloqueantes (warnings), o que não impediria a perda de cota.

### 5. Detecção e Governança de Colisões de Nomes Locais (D3)
- `scripts/harness/config.py` define a constante `GLOBAL_AGENT_NAMES` com os 8 subagentes canônicos do plugin (`researcher`, `planner`, `implementer`, `code-reviewer`, `security-auditor`, `databricks-architect`, `claude-architect`, `github-architect`).
- `scripts/harness/check_structure.py` define a constante `RESERVED_AGENT_NAMES` (`self`, `browser`, `research`, `deepagent`, `review-agent`).
- O sensor `check_structure.py` (`check_local_agents`) e o diagnóstico `scripts/harness/doctor.py` (`check_local_agents`) validam arquivos locais em subpastas de agentes (.agents/agents/ ou .claude/agents/).
- Qualquer colisão de nome (`stem` ou campo `name` do frontmatter) com `GLOBAL_AGENT_NAMES` é reprovada no gate de estrutura, a menos que o projeto declare expressamente o nome na lista `allow_override` da seção `[agents]` em `harness.toml`.
- Colisões com nomes reservados da plataforma (`RESERVED_AGENT_NAMES`) são estritamente proibidas e falham mesmo se constarem em `allow_override`.
*Alternativa descartada:* proibição absoluta de sobrescrita (inviabilizaria adaptações legítimas por projeto) ou verificação puramente informativa no `doctor` (fácil de ser ignorada).

### 6. Ponte Plan Mode para spec-driven e Tetos de Concorrência (D8)
Formalizar nas regras `plugin/rules/AGENTS.md`, `plugin/rules/behavior.md` e na skill `plugin/skills/spec-driven/SKILL.md`:
- Uma vez aprovado um plano no modo nativo de planejamento (`/plan` ou Plan Mode) para tarefas Tier 2, é obrigatório carregar a skill `spec-driven`, validar a especificação com `scripts/harness/validate_spec.py` (`SPEC VALID`) e executar a fase `Implement` de forma sequencial pelo subagente `implementer` (uma tarefa por vez).
- Tetos comportamentais de concorrência: no máximo 3 subagentes somente leitura simultâneos (`researcher` ou `Explore`) para perguntas disjuntas, e estritamente 1 subagente `implementer` por vez.
- Proibição absoluta de disparar subagentes em lote paralelo para transformações mecânicas repetitivas em múltiplos arquivos.
*Alternativa descartada:* contador de processos concorrentes persistido em disco nos hooks (complexidade desproporcional e riscos de race conditions entre processos efêmeros).

### 7. Integridade e Posição da Guarda
A guarda `subagent_routing` é integrada à tupla `guards.ALL` em `scripts/harness/guards.py` na 7ª posição (imediatamente antes de `harness_integrity`) e declarada na lista `required_guards` em `harness/core.toml`, sendo validada pelo sensor `scripts/harness/check_controls.py`.

## Consequences

- **O que se torna mais fácil:**
  - Garantia determinística contra esgotamento acidental de tokens e custos elevados por herança silenciosa de modelos pesados em subagentes.
  - Varredura automática contra vazamento de segredos em prompts de subagentes antes que a chamada seja despachada.
  - Detecção imediata de colisões acidentais que poderiam substituir agentes críticos como `security-auditor`.
  - Transpilação consistente e testada para o ecossistema Claude Code per [ADR-0017](0017-claude-sync-exporter.md).
- **O que se torna mais difícil / o que passa a ser proibido:**
  - É proibido invocar subagentes nativos (`general-purpose`, `Explore`, `Plan`, `claude`, `self`, `research`) sem definir expressamente um modelo leve (`sonnet`/`haiku` ou `flash`/`flash_lite`).
  - É proibido utilizar modelos pesados (`fable`, `opus`, `pro`, ou `inherit` em subagentes nativos ou no `researcher`).
  - É proibido sobrescrever agentes globais canônicos sem declarar explicitamente `[agents].allow_override` em `harness.toml`.
  - É proibido sobrescrever nomes reservados da plataforma (`self`, `browser`, `research`, `deepagent`, `review-agent`), mesmo com declaração em `allow_override`.
  - É proibido despachar subagentes em lote paralelo para executar tarefas mecânicas ou repetitivas.
