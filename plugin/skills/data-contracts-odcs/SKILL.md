---
name: data-contracts-odcs
description: "Definição e validação de Contratos de Dados (ODCS v3 YAML) com esquemas tipados, SLAs de frescor/completude/unicidade, semântica de negócio, SemVer e fluxo datacontract lint/breaking."
---

# Contratos de Dados (ODCS — Open Data Contract Standard)

Padroniza a fronteira formal entre produtores de dados (pipelines/aplicações) e consumidores (Gold, ML, painéis BI/PBIP) por meio de contratos versionados como código.

## Estrutura Essencial de um Contrato ODCS (YAML)

Todo dataset exposto entre domínios deve manter um manifesto versionado contendo:

1. **Identidade e Propriedade:** `id`, `version` (SemVer `MAJOR.MINOR.PATCH`), domínio proprietário, canal de contato e nível de classificação de sensibilidade (LGPD/PII).
2. **Esquema Estrutural:** nome de colunas, tipos físicos exatos, nulabilidade (`required`/`nullable`), chaves primárias/únicas e restrições de formato ou domínio.
3. **Semântica de Negócio:** definição inequívoca de cada métrica ou coluna (unidade monetária/temporal, regra de cálculo e fuso horário padrão).
4. **SLAs e Qualidade:**
   - **Frescor (*Freshness*):** atraso máximo aceitável desde o evento ou última atualização bem-sucedida.
   - **Completude (*Completeness*):** percentual máximo tolerado de valores ausentes e invariante de não-vazio por partição esperada.
   - **Unicidade e Integridade:** ausência de duplicatas na chave de negócio e integridade referencial com dimensões críticas.

## Evolução Segura (SemVer)

- **`PATCH`:** ajuste documental de descrição sem alterar dados ou validação.
- **`MINOR`:** adição de coluna **opcional** (`nullable: true`) ou relaxamento compatível sem quebrar consumidores existentes.
- **`MAJOR`:** remoção/renomeação de coluna, estreitamento de tipo, mudança semântica de cálculo ou alteração de chave primária. Exige janela *expand-contract* com aviso prévio aos consumidores registrados.

## Fluxo Automatizado em CI

- Valide a sintaxe e aderência do manifesto localmente e em PR (`datacontract lint`).
- Compare a versão proposta contra a versão publicada em produção (`datacontract breaking`) para bloquear mudanças incompatíveis sem bump `MAJOR` e aprovação explícita dos consumidores impactados.
- Nunca inclua amostras reais com PII dentro dos exemplos do arquivo de contrato; use exclusivamente valores sintéticos.
