---
trigger: glob
globs: "**/*.py, **/*.sql"
description: "Boas práticas de engenharia de dados para PySpark, Delta Lake, pipelines Medallion e contratos ODCS."
---

# Engenharia de Dados (PySpark, Delta Lake e Medallion)

Regras específicas do projeto para código PySpark, consultas SQL e pipelines analíticos.

## Performance e Memória no Driver

- Nunca chame `.toPandas()` nem `.collect()` sobre DataFrames Spark sem `.limit(...)` explícito antes da coleta no driver.
- Substitua UDFs Python linha-a-linha (`@udf`, `udf()`, `spark.udf.register()`) por funções nativas de `pyspark.sql.functions`, expressões Spark SQL ou `@pandas_udf` vetorizada com Apache Arrow.
- Prefira Liquid Clustering (`CLUSTER BY`) e Deletion Vectors ao criar tabelas Delta com carga ou `MERGE` frequente; mantenha `spark.sql.adaptive.enabled = true`.
- Evite `.cache()` e `.persist()` manuais redundantes quando o motor já oferece cache gerenciado de disco; ao usar `.persist()` em iteração, faça `.unpersist()`.

## Qualidade, Nulos e Segurança em Pipelines

- Respeite a invariante de conservação de registros entre estágios com qualidade aplicada: `count(entrada) == count(limpos) + count(quarentena)`.
- Em SQL, trate lógica ternária de `NULL`: evite `NOT IN (SELECT ...)` e `col != 'X'` sem guarda; prefira `IS DISTINCT FROM`, `eqNullSafe` e `NOT EXISTS`.
- Tabelas e filas de quarentena/DLQ herdam obrigatoriamente as mesmas ACLs, criptografia e política de retenção/LGPD da tabela de origem.
- Em fronteiras externas de ingestão, declare esquema explícito (`StructType`, Pandera ou Pydantic v2) alinhado ao contrato ODCS em vez de depender de `inferSchema=True` ou `SELECT *`.

## Testes de Transformação

- Teste regras de transformação em memória com DataFrames sintéticos determinísticos e `assertDataFrameEqual(..., checkRowOrder=False)` usando `StructType` explícito.
