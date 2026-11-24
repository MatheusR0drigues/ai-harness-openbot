---
name: secure-rag-design
description: "Arquitetura RAG segura (LLM01, LLM02, LLM08): Authorization-First Retrieval com pré-filtragem ACL antes do top-K vetorial, rastreabilidade de proveniência, índices segregados e higienização contra injeção."
---

# Arquitetura RAG Segura (Authorization-First)

Diretrizes obrigatórias para sistemas de geração aumentada por recuperação (RAG), evitando vazamento entre inquilinos (*cross-tenant*), injeção indireta de prompt e indexação sem governança.

## Princípio Central: Authorization-First Retrieval (LLM08)

- **Autorize antes de buscar, nunca depois:** o filtro de controle de acesso (tenant, grupo, nível de confidencialidade, ACL do usuário autenticado) precisa entrar **como predicado obrigatório na consulta vetorial/híbrida antes do cálculo de `top-K`**.
- Pós-filtrar depois do `top-K` vaza contexto indiretamente (reduz recall do usuário autorizado e pode expor metadados/contagens ou vazar fragmentos se houver falha de fallback).

## Segregação, Proveniência e Cadeia de Suprimentos (LLM03)

1. **Índices Segregados por Sensibilidade:** separe fisicamente coleções ou namespaces quando os conjuntos de leitores autorizados ou requisitos regulatórios (ex.: RH, financeiro, público) forem distintos.
2. **Proveniência Obrigatória no Chunk:** cada documento e fragmento armazenado deve registrar `source_uri`, `owner`, `classification`, `updated_at` e `ingestion_pipeline_version` para auditoria e revogação seletiva (*right to be forgotten*).
3. **Sem Dados Pessoais sem Base:** higienize ou mascare PII na ingestão quando o caso de uso não exigir reidentificação explícita.

## Defesa contra Injeção Indireta e Exfiltração (LLM01 / LLM02)

- **Sanitização na Ingestão:** neutralize comentários ocultos HTML/Markdown, texto invisível, caracteres de controle bidirecional e tags que simulam delimitadores de sistema antes de gerar embeddings.
- **Isolamento no Prompt:** envolva os trechos recuperados em delimitadores explícitos marcando-os como dados brutos externos; o modelo é instruído a nunca seguir comandos encontrados dentro dos documentos.
- **Guardrails de Saída e DLP:** bloqueie links externos gerados dinamicamente com parâmetros codificados, imagens Markdown para domínios não aprovados (*EchoLeak*) e vazamento de trechos fora da citação permitida.
