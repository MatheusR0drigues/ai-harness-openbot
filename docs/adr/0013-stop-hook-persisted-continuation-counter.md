# ADR-0013: Contador de continuações do `Stop` persistido por conversa

- Date: 2026-11-13
- Status: Accepted (emendou o Requisito 4.4 e o design §3.2 de `specs/consolidation-layer/`, complementando o item 3 do Contexto da ADR-0012)

## Contexto

O hook `Stop` roda `verify --fast` e, se o gate falhar, devolve `{"decision": "continue", "reason": ...}` para que o agente corrija a falha antes de encerrar. Sem um limite, um gate que nunca passa prende a sessão em um ciclo infinito (LLM10, consumo ilimitado).

O texto aprovado previa dois mecanismos que não funcionam juntos com os payloads do Antigravity:

1. O Requisito 4.4 manda liberar o encerramento quando `continuationActive` for falso ou o `terminationReason` for `model_stop`. O Antigravity IDE nunca envia `continuationActive` e termina turnos normais com `model_stop`. Pela letra do requisito, o `verify --fast` nunca rodaria na IDE.
2. O design §3.2 manda zerar o contador quando `continuationActive` é falso. Na IDE, o `Stop` provocado pelo nosso próprio `continue` é indistinguível do fim de um turno novo. Zerar ali reinicia o ciclo a cada `Stop` e o limite de 2 continuações nunca é atingido.

## Decisão

Persistir o contador por `conversationId` no diretório temporário do sistema e usá-lo como o único limite do ciclo:

- Um `terminationReason` terminal (`USER_CANCELED`, `ERROR`, `error`, `MAX_INVOCATIONS`, `MAX_FORCED_INVOCATIONS`, `MAX_TOKEN_BUDGET_EXCEEDED`, `max_steps_exceeded`, `TERMINAL_STEP_TYPE`, `TERMINAL_CUSTOM_HOOK`, `INJECTED_RESPONSE`) encerra na hora com `{"decision": "stop"}`, sem rodar o verify, e zera o contador.
- `model_stop` e `NO_TOOL_CALL` são fins normais do modelo: o `verify --fast` roda.
- Gate verde zera o contador e devolve `{"decision": "stop"}`.
- Gate vermelho devolve `continue` até `MAX_CONTINUATIONS = 2`. Na terceira falha devolve `{"decision": "stop", "reason": ...}` com o relatório e a instrução de reportar a falha ao humano. O contador continua acima do teto até o gate passar, então `Stop`s seguintes encerram em vez de reabrir o ciclo.
- `continuationActive` é lido pelo normalizador, mas não altera o contador.

Emenda proposta ao Requisito 4.4: "QUANDO o evento `Stop` for recebido com `terminationReason` terminal, o dispatcher DEVE liberar o encerramento sem rodar `verify --fast`; QUANDO o `verify --fast` falhar, o dispatcher DEVE solicitar no máximo 2 continuações por conversa e, em seguida, DEVE encerrar informando a falha no campo `reason`."

## Consequências

- Mais fácil: o mesmo comportamento vale para CLI, IDE e 2.0, e o teto de 2 continuações vale mesmo sem `continuationActive`.
- Mais difícil: um contador acima do teto sobrevive entre turnos da mesma conversa até o gate passar ou um motivo terminal encerrar a cadeia; nesse intervalo, o `Stop` não pede novas correções automáticas.
- Proibido: zerar o contador por `continuationActive` falso ou tratar `model_stop` como motivo terminal sem uma nova ADR.
- Testes: `tests/harness/test_hook_lifecycle.py` (motivos terminais, teto de 2, ciclo que não reinicia depois da desistência, `reason` na desistência, isolamento por conversa).
