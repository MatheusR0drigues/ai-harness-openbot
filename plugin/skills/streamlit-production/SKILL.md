---
name: streamlit-production
description: "Streamlit pronto para produção: arquitetura em 4 camadas, cache correto (@st.cache_data vs @st.cache_resource com TTL), @st.fragment, isolamento de session_state, paginação e testes com AppTest."
---

# Engenharia de Aplicações Streamlit em Produção

Guia para transformar protótipos Streamlit em aplicações rápidas, seguras e testáveis, evitando armadilhas comuns de reexecução completa de script e compartilhamento acidental de estado.

## Arquitetura em 4 Camadas

1. **Acesso a Dados / Consultas:** clientes parametrizados, pools e leitura paginada em módulos puros sem importar `streamlit`.
2. **Domínio e Transformação:** regras de negócio, validações e cálculos determinísticos isolados e testáveis com `pytest`.
3. **Adaptadores de Cache (`@st.cache_data` / `@st.cache_resource`):**
   - `@st.cache_data(ttl=...)`: para dados serializáveis (DataFrames, resultados de consulta, dicionários) sempre com `ttl` e argumentos hasháveis ligados ao usuário/tenant quando sensível.
   - `@st.cache_resource`: exclusivamente para recursos globais não serializáveis (engine de banco, cliente HTTP com pool, modelos carregados uma única vez). Nunca coloque estado mutável por usuário aqui.
4. **Camada de UI:** componentes visuais enxutos usando `@st.fragment` para re-renderização parcial de seções interativas e `st.form` para agrupar filtros antes de disparar consultas caras.

## Segurança, Estado e Escalabilidade

- **Isolamento de Sessão:** todo dado específico do usuário autenticado vive em `st.session_state` (escopado por sessão) ou é buscado via proxy/BFF com autenticação OIDC na borda; jamais passe `tenant_id` em cache global sem incluí-lo explicitamente na chave da função em cache.
- **Paginação no Servidor:** nunca carregue tabelas inteiras com dezenas de milhares de linhas no navegador; faça `LIMIT`/`OFFSET` ou paginação por cursor na camada de dados.
- **Sem Segredos em Código ou Logs:** carregue credenciais de ambiente/secret manager (nunca valores embutidos) e sanitize erros antes de exibir `st.error`.
- **CSV Formula Injection:** antes de oferecer exportação CSV via `st.download_button`, neutralize células que comecem com `=`, `+`, `-`, `@`, `\t` ou `\r`.

## Testes Sem Navegador

- Teste as camadas 1 e 2 diretamente com `pytest` unitário determinístico.
- Teste o fluxo de UI usando **`streamlit.testing.v1.AppTest`** com clientes de dados falsos injetados (`monkeypatch`), verificando estado e mensagens renderizadas sem precisar abrir navegador real.
