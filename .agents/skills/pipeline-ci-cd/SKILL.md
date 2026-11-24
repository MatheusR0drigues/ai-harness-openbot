---
name: pipeline-ci-cd
description: "CI/CD seguro para pipelines de dados e DataOps: GitHub Actions com OIDC sem chaves estáticas, actions fixadas por SHA, Asset Bundles, Write-Audit-Publish (WAP), rollback Delta e testes PySpark em memória."
---

# CI/CD e DataOps Seguro para Pipelines

Padrão de entrega contínua para projetos de engenharia de dados com foco em autenticidade sem segredos estáticos, promoção segura de dados e controle de custos.

## Identidade e Cadeia de Suprimentos no CI

1. **Autenticação via OIDC (`id-token: write`):**
   - Proibido armazenar chaves estáticas de longa duração (service principal secret, access keys de nuvem) em secrets de repositório quando o provedor suportar federação OIDC.
   - Solicite tokens efêmeros de curta duração vinculados estritamente ao repositório, ambiente e branch autorizados.

2. **Fixação Rígida de Dependências e Actions:**
   - Actions de terceiros no workflow devem ser fixadas pelo **hash SHA completo do commit** (nunca tags móveis como `@v4` ou `@main`).
   - Dependências Python/SQL de pipeline seguem versões exatas com lockfile verificado.

## Promoção Segura e Rollback de Dados

- **Empacotamento Declarativo:** use Asset Bundles ou infraestrutura como código para promover definições idênticas entre `dev`, `staging` e `prod`, parametrizando apenas catálogo, cluster e permissões por ambiente.
- **Padrão Write-Audit-Publish (WAP) / Blue-Green:**
  1. Escreva em ramo, partição isolada ou tabela temporária de validação.
  2. Execute checagens de contrato, invariante `count(entrada) == count(limpos) + count(quarentena)` e sanidade estatística antes de promover o ponteiro final ao consumidor.
- **Rollback em Delta Lake:** documente e teste o procedimento de reversão via `RESTORE TABLE <tabela> TO VERSION AS OF <n>` para recuperação imediata sem reconstruir histórico inteiro.

## Testes Rápidos e Controles FinOps

- Execute testes unitários de transformações em memória local com PySpark (`assertDataFrameEqual(..., checkRowOrder=False)`) sem precisar de cluster remoto em PRs.
- Configure limites de orçamento/alerta, *auto-termination* curto de clusters interativos e políticas de retenção/`VACUUM` para conter custos de computação e armazenamento ocioso.
