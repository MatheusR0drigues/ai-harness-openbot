---
name: resilience-patterns
description: "Padrões de resiliência e cache distribuído: timeout explícito, Exponential Backoff com Full Jitter, Circuit Breaker, Bulkhead, Outbox Transacional, Saga e proteção contra Cache Stampede (XFetch/Singleflight)."
---

# Padrões de Resiliência e Cache Distribuído

Catálogo prático de defesa contra falhas parciais de rede, indisponibilidade de dependências e tempestades de requisições em APIs, workers e caches distribuídos (ex.: Redis).

## Proteção de Chamadas Externas

1. **Timeout Explícito em Toda Fronteira:** defina timeouts separados de conexão e leitura; nunca faça chamadas externas sem teto de espera.
2. **Retentativas Inteligentes (Backoff + Full Jitter):**
   - Reenvie **apenas** operações idempotentes diante de falhas transitórias (`429`, `502`, `503`, `504`, timeout de rede).
   - Use **Exponential Backoff com Full Jitter** e limite estrito de tentativas (`max_retries`) para evitar tempestades sincronizadas (*thundering herd*).
3. **Circuit Breaker:** interrompa chamadas (*fail fast*) quando a taxa de erro ultrapassar o limiar configurado, abrindo janela de recuperação gradual (*half-open*) para proteger o sistema chamado e liberar threads locais.
4. **Bulkhead (Isolamento de Recursos):** separe pools de threads, conexões e semáforos por integração crítica para que a lentidão de um provedor secundário não esgote o pool principal da aplicação.

## Consistência Assíncrona e Idempotência

- **Chaves de Idempotência:** operações de escrita via fila ou webhook exigem chave de idempotência validada atomicamente antes de aplicar efeito colateral.
- **Transactional Outbox + CDC:** persista a mudança de estado de negócio e o evento a publicar **na mesma transação local de banco**, deixando um relay/CDC publicar no broker para eliminar falhas de gravação dupla (*dual-write*).
- **Sagas e Compensação:** em fluxos multi-etapas sem transação distribuída, defina ações compensatórias idempotentes para cada passo concluído antes da falha.
- **Dead Letter Queue (DLQ):** mensagens que excederem tentativas vão para DLQ com auditoria e controle de acesso equivalente ao fluxo original.

## Cache Distribuído Sem Cache Stampede

- Evite expiração simultânea em massa adicionando **jitter no TTL** das chaves.
- Para chaves quentes de cálculo caro, aplique **Singleflight** (coalescência de requisições concorrentes no mesmo processo) ou recomputação probabilística antecipada (**XFetch**) antes da expiração real do cache.
