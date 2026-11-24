---
name: powerbi-pbip-tmdl
description: "Boas práticas para projetos Power BI PBIP/PBIR/TMDL: indentação por tab, Star Schema, DAX com VAR/RETURN e DIVIDE(), Power Query seguro e limpeza de PII em filtros JSON."
---

# Power BI como Código (PBIP, PBIR e TMDL)

Guia para editar, revisar e versionar projetos Power BI em formato textual (`.pbip`, `.pbir` e arquivos `.tmdl` do modelo semântico) com segurança, legibilidade e manutenibilidade.

## Estrutura e Sintaxe TMDL

- **Indentação estrita por tab:** o Power BI Desktop e o export do Fabric gravam TMDL com tab. Preserve a indentação do arquivo: a linha indentada começa com tab, nunca com espaço. Espaço depois dos tabs é alinhamento dentro de expressão M ou DAX e é válido.
- **Formato textual moderno:** prefira `.pbip` com `.pbir` e TMDL no lugar de arquivos binários `.pbix` ou `model.bim` monolítico para permitir revisões linha a linha e automação em CI.
- **Idioma dos identificadores e documentação:** preserve nomes de medidas/colunas existentes quando já houver consumidores conectados e documente medidas públicas na propriedade `description` do TMDL.

## Modelagem e DAX

- **Star Schema rigoroso:** modele fatos no centro ligados a dimensões conformes com cardinalidade `1:*` e filtro em direção única; evite filtros bidirecionais e relações muitos-para-muitos sem tabela ponte justificada.
- **Medidas DAX limpas:**
  - Estruture cálculos compostos com blocos `VAR` / `RETURN` para clareza e avaliação única.
  - Use `DIVIDE(numerador, denominador, 0)` em vez do operador `/` sem proteção contra divisão por zero.
  - Evite colunas calculadas para métricas que dependem do contexto de filtro; prefira medidas.
  - Nunca insira constantes mágicas de cliente ou segredos dentro de expressões DAX ou Power Query M.
  - Consulta nativa (`Value.NativeQuery` ou a opção `[Query = ...]` do conector) nunca concatena parâmetro no texto; filtro que depende de parâmetro vai num passo M depois da consulta.

## Segurança e LGPD em Relatórios (`page.json`, `visual.json`, `bookmarks.json`, `report.json`)

- **Risco crítico de vazamento passivo:** filtros salvos no painel de filtros ou marcadores (*bookmarks*) ficam gravados em texto puro dentro dos arquivos JSON do relatório e do workspace.
- **Proibido versionar PII literal:** nunca deixe endereços de e-mail, CPFs, telefones ou nomes de clientes reais gravados como valores literais em blocos `"filter"` / `"filters"` de `report.json`, `page.json`, `visual.json` ou `bookmarks.json`.
- Limpe seleções pessoais de filtro no Power BI Desktop antes de salvar e execute o sensor `pbip-sanity` (pack `bi-pbip`) quando habilitado.

## Grounding com Power BI Modeling MCP Local (`MCP09`) e Controle de Versão

- **Fronteira do `powerbi-modeling-mcp` local:** o executável oficial `powerbi-modeling-mcp.exe` (extensão `analysis-services.powerbi-modeling-mcp` via `stdio`) opera apenas sobre a **camada de modelo semântico** (`.SemanticModel` / TMDL / DAX / M ou Power BI Desktop local). Ele **não lê nem edita** a camada visual `.Report` / PBIR (`report.json`, `page.json`, `visual.json`, `bookmarks.json`), que permanece editada diretamente como JSON sob validação contra o `$schema` declarado.
- **Pinagem e modo seguro (`MCP09`):** aponte sempre para o caminho exato da versão instalada de `powerbi-modeling-mcp.exe` usando `${USERPROFILE}` para portabilidade no time (ex.: baseline `1.0.1` em `${USERPROFILE}\.vscode\extensions\analysis-services.powerbi-modeling-mcp-1.0.1-win32-x64\server\powerbi-modeling-mcp.exe`), sem `@latest` ou `npx -y`. Use `["--start", "--read-only"]` como padrão seguro quando o MCP servir apenas para inspeção semântica e testes de queries DAX (mantendo escritas em disco sob os hooks do harness) ou `["--start"]` quando desejar refatorações semânticas assistidas pelo servidor.
- **Controle de versão PBIR / TMDL:** preserve o `compatibilityLevel` em `database.tmdl` e a URL exata `$schema` em cada arquivo JSON do PBIR (`report.json`, `page.json`, `visual.json`). Nunca realize upgrade silencioso de schema em edições manuais; atualizações estruturais de versão acontecem ao salvar no Power BI Desktop atualizado, seguidas de revisão de `git diff` e dos sensores locais.
