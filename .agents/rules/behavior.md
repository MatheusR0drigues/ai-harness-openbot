---
trigger: model_decision
description: "Regras detalhadas de comportamento do agente: fluxo em 3 Tiers, roteamento Hydrogen (flash/inherit), higienização de contexto (Prefix Caching e anti-lost-in-the-middle), simplicidade, mudança cirúrgica, invariantes de dados, ciclo anti-loop de 2 falhas e critério de pronto."
---

# Comportamento do Agente

Expande os princípios resumidos em `AGENTS.md`. Estas regras equilibram velocidade, economia de tokens e correção.

## 0. Fluxo Proporcional (3 Tiers) e Roteamento de Modelos

- **Tier 0 (Micro — 1–2 arquivos triviais):** execute diretamente, rode `python scripts/harness/verify.py --fast` e inspecione o diff.
- **Tier 1 (Fast-Track — ~80% do dia a dia):** mudança focalizada até 3–5 arquivos sem novo contrato externo, dependência ou risco de segurança. Use a skill `spec-fast-track` inline no chat (zero arquivos em `specs/`), rode `python scripts/harness/verify.py --fast` e releia `git diff --stat`; dispensa `code-reviewer`.
- **Tier 2 (`spec-driven` completo):** feature nova, contrato/schema, arquitetura, `>5` arquivos ou superfície sensível -> fluxo em `specs/<feature>/`, `verify` completo e revisão independente (`code-reviewer` + `security-auditor` quando aplicável). Aprovado plano no modo de planejamento nativo (`/plan` ou Plan Mode), a primeira ação obrigatória antes de editar arquivos é carregar a skill `spec-driven`, validar a pasta `specs/<feature>/` com `validate_spec.py` (`SPEC VALID`) e executar a fase `Implement` exclusivamente via `implementer` em ordem sequencial (1 tarefa por vez).
- **Roteamento Hydrogen (`flash` / `flash_lite` vs. `inherit`):** delegue leituras (`researcher`) e tarefas de escopo fechado (`implementer`) usando modelo leve (`flash` ou `flash_lite`). Se `verify --fast` falhar **1 vez**, escale a 2ª tentativa para `inherit` (`pro`) com a saída exata do sensor; na **2ª falha consecutiva**, interrompa pelo Ciclo Anti-Loop.
- **Teto de concorrência e proibição de lote mecânico:** limite a concorrência a no máximo `3` subagentes somente leitura simultâneos (`researcher` ou `Explore`) para perguntas disjuntas e `1` subagente `implementer` por vez na fase `Implement` (1 tarefa por vez). É expressamente proibido disparar subagentes em paralelo para executar a mesma transformação mecânica repetitiva em lote de múltiplos arquivos ou especificações (lote mecânico paralelo); use fatias pequenas sequenciais ou um script determinístico.

## 1. Pensar Antes de Codificar e Higienização de Contexto

- Escreva as premissas antes de editar arquivos. Premissa oculta é a principal fonte de retrabalho.
- **Anti-*Lost-in-the-Middle* e *Prefix Caching*:** posicione restrições críticas e critérios de aceite no início ou no fim do contexto de tarefa (nunca no meio de blocos longos) e evite inserir timestamps ou IDs voláteis antes de regras estáticas.
- ***Observation Masking* e Leitura Cirúrgica:** prefira mapear assinaturas (`repo-map`) e ler blocos com `StartLine`/`EndLine` a carregar arquivos inteiros; ao relatar achados de subagentes, devolva apenas referências `arquivo:linha` e resumos acionáveis.
- Pedido subespecificado: faça uma pergunta objetiva em vez de escolher uma interpretação.
- Vários desenhos viáveis (em memória ou persistido, síncrono ou assíncrono): liste prós e contras e deixe o humano decidir.
- Se existe caminho muito mais simples que o pedido, diga isso antes de investir esforço.

## 2. Simplicidade Primeiro

- Implemente o que foi pedido e nada mais: sem flags especulativas, pontos de extensão ou camadas genéricas.
- Sem código defensivo para situações impossíveis. Valide nas fronteiras e confie no interior.
- Autoverificação antes de entregar: um engenheiro sênior acharia isto inchado? Se 200 linhas cabem em 50, reescreva.

## 3. Mudança Cirúrgica

- Toque só as linhas que a tarefa exige. Sem refatoração oportunista, renomeação ou polimento de comentários alheios.
- Imite o estilo existente, mesmo que você fizesse diferente.
- Remova só imports, funções ou variáveis que a sua própria mudança deixou sem uso.
- Se a spec se revelar errada, pare e reporte; não improvise um desvio silencioso.

## 4. Execução Orientada a Metas

- Converta pedido vago em meta verificável: "adicionar validação" vira escrever testes para entrada inválida, vê-los falhar, implementar e vê-los passar.
- Use os sensores como ciclo: `verify --fast` após cada passo relevante e `verify` completo no fim (sem kit local, os comandos de teste e lint do projeto).
- Leia a saída do sensor por inteiro e corrija a causa que a dica aponta, não o sintoma.

## 5. Ciclo Anti-Loop (2 Falhas)

- Conte as falhas por abordagem: o mesmo gate falhando pelo mesmo motivo, ou a mesma hipótese de correção sem efeito, é falha consecutiva.
- Na segunda falha consecutiva, pare. Não tente uma terceira variação às cegas.
- Escreva a hipótese descartada e a evidência (saída do sensor), identifique a causa raiz e então mude a estratégia ou pergunte ao humano.
- Registre a pergunta ou o bloqueio em `progress.md` da spec antes de parar.

## 6. Quando Parar e Perguntar

- A mesma abordagem falhou 2 vezes seguidas.
- A correção exigiria enfraquecer teste, gate, hook ou checagem de tipos.
- A tarefa precisa de credenciais, serviço pago, acesso a produção ou julgamento jurídico.
- A mudança toca histórico do git, dependências, arquivos gerados, configuração de hooks ou MCP, ou algo fora do workspace.
- Requisitos conflitam entre si ou com `AGENTS.md`.
- A decisão é arquitetural e difícil de reverter.

## 7. Critério de Pronto e Invariantes de Dados

- **Em pipelines de dados:** preserve invariantes explícitos de conservação (`count(entrada) == count(limpos) + count(quarentena)`) e trate a lógica ternária de `NULL` explicitamente em joins e filtros de qualidade (`IS DISTINCT FROM`, `coalesce`), pois predicados simples `col != val` descartam nulos silenciosamente.
- **Tier 0/1:** `python scripts/harness/verify.py --fast` (ou lint/testes rápidos) com código `0` e `git diff --stat` relido.
- **Tier 2:** `verify` completo terminando com código `0` após a última edição, saída real colada na resposta, `git diff --stat` e `git diff` conferidos, ADR em `docs/adr/` se arquitetura/dependência mudou e `VEREDITO: PASS` do revisor independente (`review` / `code-reviewer`).

## 8. Releitura do Diff em Contexto Único (fallback)

Quando não houver subagente disponível, ou a revisão precisar acontecer no mesmo contexto de quem escreveu:

- Execute os papéis em sequência (`researcher`, `planner`, `implementer`, `code-reviewer`), lendo o arquivo de cada subagente como instrução de papel.
- Na fase de avaliação, releia o diff do zero (`git diff --stat` e depois `git diff` completo) em vez de confiar na memória do que acabou de escrever.
- Rode os sensores de novo nessa fase, mesmo que já tenham passado durante a implementação.
- Declare na seção "Não verificado" do relatório que a revisão ocorreu no mesmo contexto do autor e recomende uma revisão em contexto novo.

## 9. Relato

- Comece pelo resultado. Diga o que foi verificado (comandos executados e resultado) e o que não foi.
- "O comando terminou sem erro" não prova que a meta foi atingida.

## 10. Fluxo Git

- Trabalhe sempre em worktree irmã dedicada (`../wt-<repo>-<slug>`, branch `feat|fix|chore/<slug>`), seguindo `git-worktree-flow`.
- Faça commits livres na branch da worktree ao concluir tarefas relevantes ou fluxos com `verify --fast` verde; push na branch de feature também é livre.
- Nunca edite, commite ou faça push direto em `main`/`master`. Peça permissão explícita para abrir o PR somente ao concluir a demanda.
