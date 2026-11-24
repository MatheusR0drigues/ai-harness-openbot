---
name: schema-drift-gatekeeper
description: "Detecção proativa de Schema Drift entre produtor e consumidor: validação estrita em fronteiras (Pydantic v2, Pandera, StructType), análise AST de SQL e rastreamento de linhagem até PBIP/BI."
---

# Schema Drift Gatekeeper

Protocolo preventivo para impedir que alterações silenciosas de schema no produtor quebrem pipelines Silver/Gold, APIs ou modelos semânticos BI/TMDL em produção.

## Pontos de Controle Obrigatórios

1. **Fronteira de Ingestão (Contrato Estrito):**
   - Nunca confie em `inferSchema=True` ou dicionários sem validação em ingestões críticas de produção.
   - Declare o esquema explicitamente com `StructType` (PySpark), **Pandera** (DataFrames analíticos) ou **Pydantic v2** (payloads JSON/APIs), distinguindo claramente campos obrigatórios de opcionais.

2. **Modos Explícitos de Evolução:**
   - Rejeite ou roteie para quarentena colunas inesperadas com tipo incompatível, em vez de deixar `mergeSchema` alterar tipos silenciosamente (`int` -> `string` ou perda de precisão decimal).
   - Toda evolução aditiva permitida deve atualizar o contrato ODCS e os testes de contrato no mesmo conjunto de alterações.

3. **Linhagem Consumidora (SQL, Modelos Semânticos e PBIP):**
   - Ao renomear, remover ou mudar tipo de coluna na camada Gold ou em API de dados:
     - Rastreie dependências em queries SQL (analisando referências de tabela/coluna e evitando `SELECT *` em camadas expostas).
     - Verifique arquivos `.tmdl`, expressões Power Query M e referências de visuais `.pbir` (`visual.json`) para detectar campos quebrados antes do merge.

## Regras para Código e Testes

- Proíba `SELECT *` em tabelas Gold, views públicas e queries de origem consumidas por BI.
- Adicione testes de compatibilidade retroativa usando *fixtures* sintéticas da versão anterior e da versão nova do payload/tabela.
- Quando ocorrer *drift* inesperado em runtime, falhe rápido na camada de validação ou desvie o lote para tabela de quarentena com alerta contendo apenas nomes de coluna e tipos divergentes (sem vazar valores com PII nos logs).
