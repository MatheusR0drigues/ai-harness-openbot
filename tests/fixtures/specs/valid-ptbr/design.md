# Design: Exportação de Relatórios

## Visão Geral

O comando `relatorio exportar` lê os chamados do banco local e grava um arquivo CSV.

## Segurança (Modelo de Ameaças)

| Ameaça | Vetor | Controle | Verificado por |
| :-- | :-- | :-- | :-- |
| Injeção de fórmula no CSV | Campo de texto iniciado por `=` | Prefixar `'` em células iniciadas por `=`, `+`, `-` ou `@` | `test_exportar.py` |
