---
name: modular-monolith-bff
description: "Arquitetura Modular Monolith com BFF: fronteiras de domínio sem joins cruzados entre esquemas, contratos tipados internos, pool de conexões centralizado, paginação por cursor e TanStack Query."
---

# Monólito Modular e BFF

Padrão arquitetural pragmático para construir aplicações completas com alta coesão de domínio e baixo custo operacional antes que microsserviços distribuídos sejam realmente necessários.

## Fronteiras de Domínio (*Bounded Contexts*)

- Organize o backend por **módulos de domínio** (ex.: `billing/`, `catalog/`, `identity/`), não apenas por camadas técnicas horizontais (`controllers/`, `models/`).
- **Zero *joins* cruzados entre módulos:** um módulo não consulta diretamente as tabelas internas de outro domínio nem importa modelos ORM privados alheios.
- A comunicação entre módulos acontece somente por meio de **fachadas públicas tipadas** (serviços/DTOs em memória ou eventos de domínio via Outbox quando assíncrono).

## Camada BFF (Backend-for-Frontend) e Dados

- Centralize autenticação (OAuth 2.1 + cookie `__Host-`), agregação de chamadas para a UI e controle de acesso em um **BFF fino**, evitando expor múltiplos serviços internos ou tokens diretamente ao navegador.
- **Pool de conexões e transações:** mantenha pool único e dimensionado para o banco no runtime do servidor; transações nunca atravessam chamadas de rede externas.
- **Paginação por Cursor (*Keyset Pagination*):** prefira paginação baseada em cursor (`after_id` / `(created_at, id)`) em listas crescentes em vez de `OFFSET` profundo, que degrada linearmente e gera saltos/duplicatas sob inserções concorrentes.

## Integração com Frontend

- No cliente web, gerencie estado remoto com cache declarativo (ex.: **TanStack Query**), chaves determinísticas de query, invalidação explícita após mutações e tratamento claro de erro sem vazar detalhes internos do servidor.
- Mantenha contratos compartilhados ou gerados a partir de esquema único (OpenAPI / Pydantic / TypeScript) para detectar quebras entre BFF e UI em tempo de verificação estática.
