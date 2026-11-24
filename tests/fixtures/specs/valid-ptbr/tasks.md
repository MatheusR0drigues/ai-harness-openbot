# Plano de Implementação: Exportação de Relatórios

- [x] 1. Exportação em CSV
  - _Requisitos: 1_

  - [x] 1.1 Escrever testes de exportação (devem falhar)
    - _Requisitos: 1.1, 1.2_
  - [ ] 1.2 Implementar a exportação
    - _Requisitos: 1.1, 1.2_
    - _Depende de: 1.1_
  - [ ]* 1.3 Medir o tempo de exportação com 10000 linhas
    - _Requisitos: 1.1_
    - _Depende de: 1.2_

- [ ] 2. Validação de entrada
  - [ ] 2.1 Validar o argumento `--mes`
    - _Requisitos: 2.1_
    - _Depende de: 1_
  - [ ]* 2.2 Teste de propriedade do separador
    - _Requisitos: 2.3_
    - _Depende de: 1.3, 2.1_
  - [-] 2.3 Implementar a trava de arquivo
    - _Requisitos: 2.2_
    - _Depende de: 1.2_

- [ ] 3. Checkpoint final
  - Executar `verify` e anexar a saída ao `progress.md`.
  - _Depende de: 2_
