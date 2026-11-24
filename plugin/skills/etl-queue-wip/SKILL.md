---
name: etl-queue-wip
description: "Dimensionamento e controle de filas ETL/streaming usando Lei de Little (L = lambda * W), aproximação de Kingman, limites de WIP (80-85%), backpressure, particionamento por chave e envelhecimento contra starvation."
---

# Filas ETL, Streaming e Controle de WIP

Guia matemático e operacional para projetar pipelines com filas, workers concorrentes e limites de paralelismo (*Work In Progress*) estáveis sob variação de carga.

## Fundamentos de Capacidade

1. **Lei de Little ($L = \lambda \cdot W$):**
   - $L$ = itens em voo (WIP), $\lambda$ = taxa de chegada, $W$ = tempo médio de residência no pipeline.
   - Reduzir o tempo de ponta a ponta ($W$) sob a mesma vazão exige limite explícito de WIP ($L$) para não acumular estoque ocioso em fila.

2. **Aproximação de Kingman e Teto de Utilização (80%–85%):**
   - Em sistemas reais com variância na chegada ou no tempo de processamento, a latência de espera cresce de forma hiperbólica conforme a utilização $\rho$ se aproxima de `100%`.
   - Dimensione o consumo sustentado para operar em **~80% a 85% de utilização**, preservando margem de absorção de picos sem degradação em cascata.

## Controles Obrigatórios em Pipelines e Workers

- **Limites explícitos de WIP e *Backpressure*:**
  - Defina capacidade máxima de fila interna (`maxsize`), máximo de partições/arquivos simultâneos (`maxFilesPerTrigger` / `maxOffsetsPerTrigger`) e semáforos de concorrência em chamadas externas.
  - Quando o consumidor saturar, propague *backpressure* ao produtor em vez de alocar memória ilimitada.

- **Particionamento por Chave e Ordem:**
  - Agrupe mensagens que exijam ordenação causal pela mesma chave de partição (ex.: `tenant_id` ou `entity_id`), preservando concorrência entre chaves independentes.

- **Prevenção de *Starvation* (Envelhecimento):**
  - Em filas com prioridade, aplique envelhecimento (*aging*) aumentando progressivamente a prioridade efetiva de itens antigos ou reserve banda mínima para cargas de baixa prioridade.

- **Encerramento Gracioso (*Graceful Shutdown*) e DLQ:**
  - Ao receber `SIGTERM`, pare de aceitar novos lotes, finalize o item em andamento dentro do timeout de desligamento e confirme o checkpoint apenas após persistência efetiva.
  - Itens com erro permanente após retentativas limitadas com *backoff* vão para *Dead Letter Queue* (DLQ) com metadado do erro e controle de acesso equivalente ao dado original.
