# Progresso: <nome da feature>

- **Feature:** `<feature>` em `specs/<feature>/`
- **Fase atual:** Specify | Design | Tasks | Implement | Review
- **Última atualização:** <AAAA-MM-DD>

Memória paginada entre sessões: mantenha o **Core State** acima de 40 linhas enxuto no topo para retomadas baratas; detalhes históricos ficam arquivados em `design.md` e `docs/adr/`.

## Core State (Estado Ativo)

- **Concluído:** <IDs de tarefas, por exemplo 1.1, 1.2>
- **Em andamento:** <ID da tarefa>
- **Bloqueios e anti-loop:** <nenhum ou lista com hipóteses descartadas e modelo usado>
- **Próximo passo:** <próxima ação concreta, por exemplo executar a tarefa 2.1>

## Gates

- [ ] Gate 1 (Specify): validador imprime `SPEC VALID` + aprovação explícita do usuário
- [ ] Gate 2 (Design): validador imprime `SPEC VALID` com `## Segurança` presente + aprovação explícita do usuário
- [ ] Gate 3 (Tasks): validador imprime `SPEC VALID` (dependências só para trás, sem ciclos) + aprovação explícita do usuário
- [ ] Gate 4 (Implement): `verify` completo verde + `git diff --stat` relido + `VEREDITO: PASS` do revisor independente

## Recall (Decisões Recentes)

- <AAAA-MM-DD> - <decisão ativa> - <motivo curto>

## Archival (Referências Frias)

- Decisões arquiteturais consolidadas e alternativas descartadas vivem em `design.md` e `docs/adr/`. Mova entregas antigas para resumo condensado se este arquivo ultrapassar 80 linhas.
