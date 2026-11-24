# ADR-0020: Indentação TMDL por Tab no Gate `pbip-sanity`

- Date: 2026-11-16
- Status: Accepted

## Context

O gate `pbip-sanity` do pack `bi-pbip` (ADR-0015) acusava qualquer tab na indentação de arquivos `.tmdl` e mandava indentar com espaços. Medição num projeto PBIP real: os 600 arquivos `.tmdl` começam a indentação com tab, nenhuma linha começa com espaço e há cerca de 330 mil linhas com tab seguido de espaço (alinhamento dentro de expressões M e SQL). O Power BI Desktop e o export do Fabric gravam TMDL assim. A regra antiga reprovava todo projeto gerado pelas ferramentas oficiais e induzia o agente a reindentar arquivos, o que produz diffs enormes e conflita com o próximo save do Desktop.

A orientação de consulta nativa (`Value.NativeQuery` "parametrizado") também era vaga: não proibia concatenar parâmetro no texto SQL, que é a forma de injeção relevante em Power Query.

## Decision

1. `check_tmdl_text` passa a acusar a linha não vazia que começa com espaço. Tab no início da linha é válido; espaço depois dos tabs é alinhamento de expressão e é válido. O marcador `pbip-sanity: allow` continua isentando a linha.
2. A regra `harness/packs/bi-pbip/rules/bi-pbip.md`, a skill `plugin/skills/powerbi-pbip-tmdl/SKILL.md` e o `hint` do gate em `pack.toml` passam a dizer "indentação por tab".
3. Consulta nativa (`Value.NativeQuery` ou a opção `[Query = ...]` do conector) nunca concatena parâmetro no texto; filtro que depende de parâmetro vai num passo M depois da consulta.
4. Os testes em `tests/harness/test_domain_packs.py` invertem os casos: espaço inicial é achado, tab é aceito. O teste de contenção da raiz passa a usar um `outside.tmdl` indentado com espaços, para continuar provando que um arquivo com violação fora da raiz é ignorado.

## Consequences

- O gate deixa de reprovar projetos salvos pelo Desktop ou exportados do Fabric.
- Arquivo `.tmdl` editado à mão com espaços no início da linha passa a falhar no gate.
- O gate não valida a profundidade da indentação, só o caractere inicial.
