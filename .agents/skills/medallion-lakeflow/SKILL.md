---
name: medallion-lakeflow
description: "Arquitetura Medallion (Bronze, Silver, Gold) e pipelines Lakeflow com Expectations, quarentena segura, conservação de registros, lógica ternária de NULL e CDC/SCD Tipo 2."
---

# Arquitetura Medallion e Pipelines Lakeflow

Padrão operacional para construir pipelines de ingestão e refino em camadas (**Bronze -> Silver -> Gold**) com rastreabilidade, reconciliação quantitativa e proteção de dados sensíveis.

## Papel das Camadas

1. **Bronze (Captura Fiel e Append-Only):**
   - Preserva o dado bruto na granularidade e formato originais, acrescido apenas de metadados técnicos (`_ingested_at`, `_source_file`, `_batch_id`).
   - Imutável para permitir reprocessamento idempotente sem voltar à fonte externa.

2. **Silver (Normalização, Qualidade e Deduplicação):**
   - Tipagem explícita, padronização de fuso horário (UTC), deduplicação determinística por chave natural + timestamp/versão e aplicação de regras de qualidade (*Expectations*).
   - Implementa CDC e **SCD Tipo 2** (`valid_from`, `valid_to`, `is_current`) quando histórico de atributos for requisito de negócio.

3. **Gold (Camada de Consumo e Negócio):**
   - Modelos dimensionais (*Star Schema*: Fatos e Dimensões), métricas agregadas e visões orientadas a contrato ODCS. Nenhuma regra de limpeza ad-hoc deve vazar diretamente para o painel sem passar pela Silver.

## Invariantes Obrigatórias de Qualidade

- **Conservação de Registros:** todo estágio com roteamento de qualidade deve manter a invariante verificável:
  `count(entrada) == count(limpos) + count(quarentena)`
  Registros rejeitados nunca são descartados silenciosamente sem telemetria explícita.
- **Lógica Ternária de `NULL` em SQL:** lembre que `col != 'X'` e `NOT IN (SELECT ...)` avaliam como `UNKNOWN` (falso em `WHERE`) na presença de `NULL`.
  - Use comparações seguras para nulos: `IS DISTINCT FROM` / `eqNullSafe` (PySpark), `COALESCE` explícito e `NOT EXISTS` em vez de `NOT IN`.
- **Quarentena e DLQ Seguras:**
  - Tabelas/tópicos de quarentena armazenam os registros brutos rejeitados; portanto **herdam obrigatoriamente as mesmas ACLs, criptografia e política de retenção/LGPD** da camada de origem para não criar vazamento lateral de PII.

## Idempotência e Reprocessamento

- Prefira particionamento ou janelas `MERGE INTO` / `replaceWhere` por lote ou data de partição em vez de `INSERT` cego sem chave.
- Separe configuração declarativa de pipeline (workflows/Lakeflow) da lógica pura de transformação para viabilizar testes unitários com DataFrames sintéticos em memória.
