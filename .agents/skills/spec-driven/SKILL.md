---
name: spec-driven
description: "Conduz feature ou mudança não trivial pelas fases Specify, Design, Tasks e Implement em specs/<feature>/, com gate determinístico e aprovação explícita do usuário entre as fases, usando os subagentes planner, implementer e code-reviewer. Use ao iniciar ou retomar uma feature, mudança de contrato ou arquitetura, refatoração ampla ou quando pedirem uma spec."
---

# Fluxo Spec-Driven (Tier 2)

Quatro fases em ordem: `Specify -> Design -> Tasks -> Implement`. Nunca inicie uma fase sem que o gate da anterior passe **e** sem aprovação explícita do usuário sobre o resultado da fase. Nunca pule um gate nem edite o validador para ele passar: corrija o documento.

**Triagem de Tier (economia de tokens):**
- **Tier 0 (Micro):** typo, texto ou flag isolada (1–2 arquivos) -> direto com `verify --fast` e inspeção do diff.
- **Tier 1 (Fast-Track):** tarefa focalizada até 3–5 arquivos sem novo contrato externo, dependência ou risco de segurança -> use `../spec-fast-track/SKILL.md` inline no chat, sem criar arquivos em `specs/`.
- **Tier 2 (este fluxo):** feature nova, quebra/criação de contrato ou schema, arquitetura, `>5` arquivos, dependência nova ou superfície sensível (auth, rede, PII, segredos, harness).

## Papéis e Roteamento de Modelo (Hydrogen)

| Papel | Quem | Modelo | Faz |
| :--- | :--- | :--- | :--- |
| Pesquisa | subagente `researcher` | `flash` / `flash_lite` | mapeia arquivos, contratos e riscos (somente leitura) |
| Planejamento | subagente `planner` | `inherit` (`pro`) | redige requirements, design e tasks e devolve o conteúdo ao coordenador |
| Implementação | subagente `implementer` | `flash` (escala para `inherit` após 1ª falha) | executa uma tarefa por vez, com testes primeiro |
| Avaliação | subagente `code-reviewer` (+ `security-auditor` se sensível) | `inherit` (`pro`) | revisão independente com `VEREDITO: PASS` ou `VEREDITO: FAIL` |

Você atua como coordenador: delega aos subagentes, grava os documentos, executa os gates e pede aprovação ao usuário. Os subagentes devolvem seus relatórios via `send_message`. Sem suporte a subagentes, execute os papéis em sequência lendo o arquivo de cada um como instrução de papel e releia o diff do zero na avaliação (regra `behavior.md`, seção 8).

- **Teto de concorrência:** limite a concorrência a no máximo `3` subagentes somente leitura simultâneos (`researcher` ou `Explore`) para perguntas disjuntas. Na fase `Implement`, use estritamente `1` subagente `implementer` por vez (1 tarefa por vez em ordem sequencial). Proibido paralelismo em lote mecânico.

## Validador de Specs

- Com o kit local no repositório: `python scripts/harness/validate_spec.py specs/<feature>`.
- Sem o kit local: utilitário do plugin `scripts/harness/validate_spec.py` (caminho relativo a este `SKILL.md`; resolva para caminho absoluto antes de executar), por exemplo `python scripts/harness/validate_spec.py specs/<feature>`.
- Resultado esperado: `SPEC VALID`. Qualquer outra saída reprova o gate.

## 0. Preparação

1. Escolha um nome kebab-case para a feature (por exemplo `exportar-relatorio`).
2. Crie `specs/<feature>/` na raiz do repositório.
3. Copie os modelos de `resources/` desta skill: `requirements.md`, `design.md`, `tasks.md` e `progress.md`. Para bug em caminho crítico, use também `bugfix.md` (skill `fix-bug`).
4. Delegue ao `researcher` o mapeamento de arquivos, contratos e riscos, em paralelo ao `planner` quando as perguntas forem independentes.

## 1. Specify -> `requirements.md`

- Cada requisito tem `### Requisito <n>: <título>`, a linha `**História:** Como <papel>, quero <capacidade>, para <benefício>.` e `#### Critérios de Aceite` com critérios EARS numerados:
  - `QUANDO <gatilho>, o sistema DEVE <resposta>.`
  - `SE <condição indesejada>, ENTÃO o sistema DEVE <tratamento>.`
  - `ENQUANTO <estado>, o sistema DEVE <comportamento>.`
  - `ONDE <recurso opcional ativo>, o sistema DEVE <comportamento>.`
  - `O sistema DEVE <comportamento ubíquo>.`
- Cada critério é observável e testável: números, limites de tempo, códigos de retorno, mensagens exatas.
- Termos vagos reprovam o gate: rápido, adequado, fácil, amigável, intuitivo, eficiente, robusto, escalável, otimizado.
- Seção `## Fora de Escopo` obrigatória.
- Pergunte sobre qualquer ambiguidade; nunca invente escopo.
- **Gate 1:** validador imprime `SPEC VALID` e o usuário aprova explicitamente os requisitos.

## 2. Design -> `design.md`

- Arquitetura (mermaid quando ajudar), componentes e contratos públicos, modelo de dados e tratamento de erros.
- Tabela de decisões (`D1`, `D2`, ...) com data, motivo e alternativa descartada. Apresente alternativas com prós e contras e deixe o usuário escolher.
- Seção `## Segurança` obrigatória: modelo de ameaças OWASP LLM/ASI/MCP desta mudança, uma linha por ameaça (ameaça -> controle -> gate ou teste que verifica), mais as ameaças consideradas e não cobertas, com motivo. O checklist é a regra `ai-security.md`.
- Estratégia de testes mapeando cada critério de aceite a um teste planejado.
- **Gate 2:** validador imprime `SPEC VALID` (ele confere `## Segurança`) e o usuário aprova explicitamente o design.

## 3. Tasks -> `tasks.md`

- Fatias verticais pequenas; a tarefa de teste vem antes da implementação; cada tarefa tem demo ou comando de verificação.
- `_Requisitos: 1.1, 1.2_` cita IDs de critérios existentes; `_Depende de: 1.1_` cita só tarefas anteriores (sem dependência para frente e sem ciclos).
- Tarefas opcionais são marcadas `- [ ]* <id>`; tarefa obrigatória nunca depende de opcional.
- **Gate 3:** validador imprime `SPEC VALID` e o usuário aprova explicitamente o plano.

## 4. Implement

- Delegue ao `implementer` em `Model="flash"` uma tarefa por vez, em ordem, com as dependências concluídas.
- Se `verify --fast` falhar 1 vez no modelo leve, escale a 2ª tentativa para `Model="inherit"` (`pro`) levando o erro do sensor; na 2ª falha consecutiva da mesma abordagem, pare pelo ciclo anti-loop, registre em `progress.md` e mude a estratégia ou pergunte ao usuário.
- Entre tarefas: `python scripts/harness/verify.py --fast` verde antes de seguir (sem kit local, os testes e lint rápidos do projeto).
- Ao fim de cada tarefa, marque-a como `[x]` em `tasks.md` e atualize o bloco ativo de `progress.md` (paginação: mantenha o estado atual enxuto no topo).
- Após a última tarefa: `python scripts/harness/verify.py` completo, `git diff --stat` relido e skill `review` com o `code-reviewer` em contexto novo, mais `security-auditor` se a mudança tocar autenticação, rede, entrada externa, segredos, permissões ou o harness.
- **Gate 4:** `verify` completo verde, `VEREDITO: PASS` do revisor independente e aprovação do usuário para encerrar.

## Memória de Progresso

`specs/<feature>/progress.md` é a memória entre sessões (modelo em `resources/progress.md`). Registre estado e decisões, nunca logs. Atualize ao fim de cada fase e antes de compactar o contexto; ao retomar, leia-o primeiro, junto com a spec.

## Contrato de Saída

- `requirements.md`, `design.md`, `tasks.md` e `progress.md` em `specs/<feature>/`.
- Saída real do validador em cada gate e registro da aprovação do usuário em `progress.md`.
- Saída real do `verify` completo.
- Relatório do revisor independente com `VEREDITO: PASS`.

## Checklist

- [ ] Gates 1, 2 e 3 com `SPEC VALID` e aprovação explícita do usuário
- [ ] Cada critério de aceite rastreável até um teste
- [ ] `verify --fast` verde entre tarefas e `verify` completo verde no fim
- [ ] Nenhum arquivo fora do escopo e nenhum gate afrouxado
- [ ] Revisão feita em contexto independente do autor

## Orquestração OpenBot (`start_task`, `git worktree` e `run_workflow`)

- Isole cada execução em `git worktree` dedicada (`../wt-<feature>`) via `start_task` (mantendo `1 Gerente por repositório`).
- Em ondas Topológicas Nível 2, acione `run_workflow` executando `workflows/spec_dag_runner.py` (`python workflows/spec_dag_runner.py --tasks specs/<feature>/tasks.md --feature <feature>`), que coordena `dag_runner.py` e persiste estado e vereditos vinculados a `commit_sha` nas tabelas SQLite `harness_tasks` e `harness_verdicts`.
