---
trigger: glob
globs: "tests/**, **/test_*.*, **/*_test.*, **/*.test.*, **/*.spec.*"
description: "Convenções de testes automatizados ao criar ou editar arquivos de teste: determinismo sem rede, relógio real ou sleep, tmp_path, parametrize, fixtures anonimizadas, proibição de noqa e skip sem justificativa escrita e teste de regressão obrigatório em correções de bug."
---

# Convenções de Testes

## Estrutura e Troféu de Testes (*Testing Trophy*)

- Priorize análise estática (tipos + lint) e testes de integração determinísticos na fronteira real dos módulos (usando banco em memória, `tmp_path` ou Spark local) em vez de multiplicar testes unitários acoplados a mocks frágeis da própria lógica.
- Em transformações PySpark ou de dados, declare `StructType` explícito nas fixtures e valide com `assertDataFrameEqual(..., checkRowOrder=False)` sem depender de cluster remoto.
- Nomeie testes como `test_<comportamento>_<condição>` (ou o equivalente da stack).
- Um comportamento por teste, com Arrange / Act / Assert visível e sem condicionais ou laços decidindo o que afirmar.
- Para tabelas de entrada, use `pytest.mark.parametrize` (ou `test.each` / `it.each` em JavaScript) em vez de testes copiados.
- Nenhum teste depende da ordem de execução ou do estado deixado por outro.

## Determinismo

- Testes unitários nunca usam rede real, relógio real ou `sleep` real.
- Injete dependências (cliente HTTP, relógio, executor de processos) e passe fakes, ou use `monkeypatch`.
- Fixe semente de aleatoriedade e fuso horário quando o comportamento depender deles.
- Testes com rede real ficam marcados (por exemplo `@pytest.mark.live`), fora da execução padrão e do `verify`.

## Arquivos e Fixtures

- Escreva arquivos apenas em diretórios temporários (`tmp_path` no pytest); nunca no repositório a partir de um teste.
- Fixtures são sintéticas e anonimizadas: sem nomes reais, e-mails, URLs de perfis, cookies ou tokens.
- Segredos fictícios são montados em tempo de execução (concatenação) para o scanner de segredos não acusar o arquivo de teste.

## Disciplina com Falhas

- Teste falhando é sinal. Corrija o código; mude o teste só se ele estiver errado, e explique por quê.
- Nunca afrouxe asserção, apague teste ou reduza cobertura só para ficar verde.
- `# noqa`, `# type: ignore`, `skip`, `skipif` e `xfail` exigem justificativa escrita na mesma linha ou na linha anterior, com motivo concreto e referência a issue ou ADR. Sem justificativa escrita, é violação.
- Asserção estável: sem contagem absoluta que cresce com a carga, horário corrente ou ordem não garantida.

## Regressão

- Correção de bug exige teste de regressão que falha antes da correção, pelo motivo relatado, e passa depois.
- Veja todo teste novo falhar ao menos uma vez: teste que nunca falhou não prova nada.

## Testes do Harness

- `tests/harness/` protege o próprio harness; alterá-lo exige aprovação explícita do humano.
