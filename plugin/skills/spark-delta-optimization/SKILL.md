---
name: spark-delta-optimization
description: "Otimização prática de PySpark e Delta Lake: diagnóstico via Spark UI, AQE, Liquid Clustering (CLUSTER BY), Deletion Vectors, Photon/Disk Cache, vetorização Arrow e eliminação de .toPandas()/.collect() sem limite."
---

# Otimização de PySpark e Delta Lake

Diretrizes práticas para diagnosticar e corrigir gargalos de custo, memória e latência em jobs PySpark e tabelas Delta Lake antes de escalar cluster ou memória de driver.

## Diagnóstico Primeiro (Ordem de Análise)

1. Inspecione o **Spark UI / Query Profile** para localizar o gargalo dominante:
   - *Skew* (uma tarefa demora muito mais que a mediana do stage).
   - *Spill* em disco (`Spill (Memory)` / `Spill (Disk)`).
   - *Small Files* (milhares de arquivos pequenos lidos ou gravados).
   - *Shuffle* excessivo (troca de dados entre nós antes de filtros).
2. Verifique o plano físico (`df.explain("formatted")`) para confirmar *predicate pushdown* e poda de partições/arquivos.

## Vetorização e Memória do Driver

- **Proibido `.toPandas()` e `.collect()` sem `.limit(...)`:** nunca puxe volumes abertos para a memória do driver (risco de `OutOfMemoryError`). Amostragens usam `.limit(N)` explícito; agregações e exportações permanecem distribuídas.
- **Substitua UDF Python linha-a-linha (`@udf` / `udf()` / `spark.udf.register`)** por:
  1. Funções nativas `pyspark.sql.functions` ou expressões Spark SQL (executadas na JVM/Photon).
  2. `@pandas_udf` com **Apache Arrow** vetorizado quando lógica Python personalizada for inevitável.
- **Reduza `.cache()` e `.persist()` manuais** quando o motor contar com Photon e Disk Cache gerenciado; cache manual mal dimensionado pressiona a JVM e gera despejo em disco. Quando usar `.persist()` em fluxo iterativo, garanta `.unpersist()` ao final.

## Layout Físico Delta Lake e Shuffle

- **Liquid Clustering (`CLUSTER BY`):** prefira `CLUSTER BY (col_filtro, col_join)` em tabelas novas no lugar de `PARTITIONED BY` rígido ou `ZORDER` legado, acompanhado de `OPTIMIZE` periódico.
- **Deletion Vectors & Predictive I/O:** mantenha Deletion Vectors habilitados em tabelas com `MERGE`/`UPDATE`/`DELETE` frequentes para evitar reescrita completa de arquivos Parquet (*Copy-on-Write*).
- **Adaptive Query Execution (AQE):** deixe `spark.sql.adaptive.enabled = true` para coalescência automática de partições pós-shuffle e mitigação dinâmica de *skew joins*.
- **Salting controlado:** quando houver chave altamente assimétrica não resolvida por AQE ou `broadcast()` de tabela pequena, aplique prefixo aleatório (*salt*) em duas fases de agregação ou join.

## Checklist de Revisão Rápida

- [ ] Nenhuma chamada `.toPandas()` ou `.collect()` sem `.limit(N)` prévio (ou motivo documentado em teste).
- [ ] Zero `@udf` Python pura para transformações simples de string, data ou matemática.
- [ ] Filtros e projeções de colunas aplicados o mais cedo possível antes de `join` e `groupBy`.
- [ ] Tabelas Delta com `MERGE` frequente usam `Liquid Clustering` e Deletion Vectors, além de `VACUUM` com janela segura configurada.
