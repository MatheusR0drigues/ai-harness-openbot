# Requisitos: Critérios Multilinha (ADR-0006)

### Requisito 1: Quebra de linha em critérios

**História:** Como autor de specs, quero quebrar critérios longos em várias linhas, para manter o
Markdown legível no revisor de código.

#### Critérios de Aceite

1. QUANDO um critério ocupar mais de uma linha física,
   o sistema DEVE tratar as linhas indentadas seguintes
   como parte do mesmo critério.
2. WHEN a criterion is wrapped with a tab-indented line,
	THE SYSTEM SHALL join the continuation with the numbered line.
3. O sistema DEVE manter o número da linha inicial do critério nas mensagens de erro.

## Fora de Escopo

- Critérios escritos como parágrafos sem numeração.
