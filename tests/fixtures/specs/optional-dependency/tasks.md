# Plano: dependência de tarefa opcional

- [ ] 1. Núcleo
  - [ ] 1.1 Implementar o núcleo
    - _Requisitos: 1.1_
  - [ ]* 1.2 Teste de propriedade opcional
    - _Requisitos: 1.1_
    - _Depende de: 1.1_
  - [ ]* 1.3 Relatório opcional que depende de outra tarefa opcional
    - _Requisitos: 1.2_
    - _Depende de: 1.2_

- [ ]* 2. Extras opcionais
  - [ ] 2.1 Extra que herda a marcação opcional do pai
    - _Depende de: 1.1_

- [ ] 3. Checkpoint obrigatório
  - _Requisitos: 1.2_
  - _Depende de: 1.2, 2.1_
