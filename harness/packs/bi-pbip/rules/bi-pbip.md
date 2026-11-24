---
trigger: glob
globs: "**/*.tmdl, **/*.pbip, **/*.pbir, **/report.json"
description: "Boas práticas para projetos Power BI PBIP/PBIR/TMDL, DAX limpo, Star Schema e proteção contra vazamento de PII."
---

# BI e Power BI como Código (PBIP / PBIR / TMDL)

Regras específicas do projeto para edição textual de modelos semânticos TMDL e relatórios PBIP/PBIR.

## Higiene Textual e Modelagem

- Indentação TMDL por **tab**, como o Desktop e o Fabric gravam: a linha indentada começa com tab, nunca com espaço; espaço depois dos tabs é alinhamento de expressão.
- Estruture modelos analíticos em **Star Schema** com fatos centrais e dimensões conformes (`1:*`, direção única de filtro por padrão).
- Em medidas DAX, organize cálculos compostos com `VAR` / `RETURN`, proteja divisões com `DIVIDE()` e documente métricas principais em `description`.
- Em Power Query M, parametrize parâmetros de ambiente e nunca embuta credenciais ou tokens. Consulta nativa (`Value.NativeQuery` ou a opção `[Query = ...]` do conector) nunca concatena parâmetro no texto; filtro que depende de parâmetro vai num passo M depois da consulta.

## Proteção de Dados Pessoais (LGPD) em Filtros JSON

- Arquivos `report.json`, `page.json`, `visual.json` e `bookmarks.json` armazenam filtros salvos e marcadores em texto claro.
- **Proibido versionar PII literal** (e-mails reais, CPFs, telefones ou nomes de clientes) dentro de blocos `"filter"` ou `"filters"` de configuração de relatório ou visual.
- Limpe filtros pessoais de depuração antes do commit e valide com `pbip-sanity`.

## Acessibilidade Visual

- Respeite paletas distinguíveis (ex.: Okabe-Ito), contraste mínimo de **4.5:1** para texto e **3:1** para séries/bordas, além de hierarquia clara com rótulos diretos.
