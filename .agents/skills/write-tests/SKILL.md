---
name: write-tests
description: "Escreve ou atualiza testes automatizados com asserção de comportamento, dados sintéticos, determinismo sem rede, relógio real ou sleep, e independência entre casos. Use quando código novo, critério de aceite sem teste ou bug corrigido precisa de cobertura, ou quando um teste quebrou por mudança legítima."
---

# Escrita de Testes

Siga a regra `testing.md` do plugin e as convenções de testes do projeto (`.agents/rules/tech.md` e `.agents/rules/structure.md` indicam suítes, ferramentas e pastas).

## Quando Usar

Código novo sem cobertura, critério de aceite sem teste, bug corrigido que precisa de regressão (com a skill `fix-bug`) ou teste que quebrou por mudança legítima.

## Passos

1. **Escolher o nível (Troféu de Testes).** Priorize análise estática + testes de integração determinísticos na fronteira real dos módulos (banco em memória, `tmp_path` ou Spark local com `assertDataFrameEqual` e `StructType` explícito) sobre mocks frágeis da própria lógica; reserve testes E2E completos apenas para fluxos críticos.
2. **Nomear pelo comportamento.** `test_<comportamento>_<condição>`: o nome diz a regra, não o nome da função.
3. **Dados sintéticos e mínimos.** Nunca dado real de produção ou PII em fixture versionada; segredos fictícios montados em tempo de execução.
4. **Tabelas de casos.** Use `pytest.mark.parametrize` (ou o equivalente da stack) em vez de copiar testes.
5. **Casos de borda.** Vazio, nulo, duplicado, tipo errado, limite numérico e entrada inválida (que deve falhar de forma explícita, não devolver vazio).
6. **Isolamento.** Arquivos só em `tmp_path`; rede, relógio e processos substituídos por fakes ou `monkeypatch`; nenhum `sleep` real; nenhum teste depende de outro.
7. **Asserção estável.** Sem contagem absoluta que cresce com a carga, horário corrente ou ordem não garantida.
8. **Ver falhar.** Em teste novo para comportamento existente, quebre o código temporariamente, confirme que o teste acusa e desfaça a quebra. Teste que nunca falhou não prova nada.
9. **Exceções explícitas.** `skip`, `xfail`, `# noqa` ou `# type: ignore` só com justificativa escrita (motivo concreto e referência a issue ou ADR).
10. **Rodar.** `python scripts/harness/verify.py --fast` durante o trabalho e `python scripts/harness/verify.py` no fim (sem kit local, os comandos de teste do projeto).

## Contrato de Saída

- Teste na suíte certa, com nome que descreve o comportamento.
- Docstring ou comentário curto dizendo qual falha real o teste previne.
- Saída real da execução dos testes e do `verify`.

## Checklist

- [ ] Nível mais baixo que prova o requisito
- [ ] Dados sintéticos, sem PII nem segredo real
- [ ] Bordas cobertas
- [ ] Sem rede, relógio real ou `sleep`; arquivos em `tmp_path`
- [ ] Visto falhar ao menos uma vez
- [ ] Nenhum `skip` ou `noqa` sem justificativa escrita
