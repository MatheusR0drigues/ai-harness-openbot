---
name: pr-impact-analysis
description: "Análise estruturada de raio de impacto (blast radius), contratos quebrados, migrações e riscos operacionais antes de concluir entregas Tier 2, sem substituir auditoria independente."
---

# Análise de Impacto de PR / Mudança (Blast Radius)

Avalia o alcance real de uma alteração antes da revisão final ou abertura de PR, identificando dependências ocultas, quebras de contrato e riscos de implantação.

## Escopo e Papel

- Esta skill produz um **relatório técnico descritivo de impacto**.
- Ela **não substitui** a auditoria independente de `code-reviewer` nem a de `security-auditor`, e não emite veredito de aprovação (`PASS`/`FAIL`).

## Fluxo de Análise (5 Eixos)

1. **Inventário da Superfície Alterada:**
   - Obtenha a lista objetiva via `git diff --stat` e `git diff --name-status`.
   - Classifique os arquivos tocados em: contrato público/esquema, regra de negócio, infraestrutura/CI, configuração de segurança/harness e testes.

2. **Raio de Impacto (*Blast Radius*) e Consumidores:**
   - Para cada função pública, evento, rota, tabela ou coluna modificada, busque todos os pontos de chamada e consumidores no repositório (`rg -n`).
   - Identifique se há consumidores externos (APIs REST/gRPC, filas, painéis BI/PBIP, DAGs) fora da cobertura direta dos testes locais.

3. **Compatibilidade de Contratos e Migrações:**
   - Verifique remoção ou renomeação de campos, mudança de tipo, alteração de valor padrão ou nulabilidade.
   - Avalie ordem de implantação (*expand-contract*): código novo convive com dados antigos durante janela de deploy? Há necessidade de backfill ou script de rollback?

4. **Impacto em Desempenho, Custo e Confiabilidade:**
   - Novas consultas sem limite, joins amplos, loops com rede sem timeout ou remoção de cache.
   - Alterações de paralelismo, retenção ou volumetria que afetem custo de nuvem ou SLA.

5. **Lacunas de Verificação:**
   - Liste caminhos afetados que ainda não possuem teste automatizado ou cuja verificação dependa de ambiente específico.

## Formato da Entrega

- **Resumo de Escopo:** N arquivos alterados e nível sugerido (`Tier 1`, `Tier 2` ou `Tier 3`).
- **Tabela de Impacto:** `Superfície | Mudança | Consumidores Afetados | Risco | Mitigação`.
- **Plano de Rollback:** passos objetivos para reverter em caso de regressão (código e estado/dados).
- **Perguntas em Aberto:** pontos que exigem decisão humana antes de merge ou deploy.
