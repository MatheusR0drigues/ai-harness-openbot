# Plano de Implementação: <nome da feature>

## Visão Geral

<Como o trabalho foi fatiado e em que ordem.>

Regras do plano:

- As tarefas rodam de cima para baixo e as dependências só apontam para tarefas anteriores, sem dependência para frente e sem ciclos.
- Tarefas obrigatórias nunca dependem de tarefas opcionais (marcadas com `*` logo após o checkbox); uma tarefa opcional pode depender de obrigatórias.
- O teste vem antes da implementação. Cada tarefa termina com `verify --fast` verde e a última com o `verify` completo.
- As referências de requisitos citam IDs de critérios que existem em `requirements.md` (por exemplo `1.1`).

## Tarefas

- [ ] 1. <primeira fatia vertical>
  - [ ] 1.1 Escrever os testes de <comportamento> (devem falhar)
    - <testes a escrever e ver falhar>
    - _Requisitos: 1.1, 1.2_
  - [ ] 1.2 Implementar <comportamento>
    - <o que muda e por quê>
    - Demo: <comando ou resultado observável>
    - _Requisitos: 1.1, 1.2_
    - _Depende de: 1.1_
  - [ ]* 1.3 <tarefa opcional, por exemplo testes de propriedade adicionais>
    - _Requisitos: 1.2_
    - _Depende de: 1.2_
- [ ] 2. <segunda fatia vertical>
  - [ ] 2.1 Escrever os testes de <comportamento> (devem falhar)
    - _Requisitos: 2.1, 2.2, 2.3_
    - _Depende de: 1.2_
  - [ ] 2.2 Implementar <comportamento>
    - Demo: <comando ou resultado observável>
    - _Requisitos: 2.1, 2.2, 2.3_
    - _Depende de: 2.1_
- [ ] 3. Checkpoint final: `verify` completo e revisão independente (skill `review`)
  - [ ] 3.1 Rodar o `verify` completo, reler `git diff --stat` e obter `VEREDITO: PASS` do `code-reviewer`
    - _Requisitos: 1.1, 1.2, 2.1, 2.2, 2.3_
    - _Depende de: 2.2_

## Notas

- <restrições e itens explicitamente fora desta entrega>
