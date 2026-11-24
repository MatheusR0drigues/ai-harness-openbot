# Bugfix: <título curto do defeito>

## Sintoma

- Comportamento observado: <o que acontece>
- Comportamento esperado: <o que deveria acontecer>
- Impacto: <quem é afetado e com que frequência>

## Reprodução

1. <passo>
2. <passo>

- Entrada, parâmetros e ambiente: <valores sintéticos, sem PII nem segredos>
- Comando que reproduz: `<comando>`

## Causa Raiz

<Mecanismo técnico exato, com referência `arquivo:linha`. Distinga o sintoma da causa.>

## Teste de Regressão

- Teste: `<caminho do arquivo de teste>::<nome_do_teste>`
- Saída antes da correção (deve falhar pelo motivo relatado): <trecho real>
- Saída depois da correção: <trecho real>

## Correção

<Mudança mínima aplicada e por que ela resolve a causa raiz.>

- Comportamento que não pode mudar: <lista>
- Hipóteses descartadas (ciclo anti-loop): <hipótese> - <evidência>

## Prevenção

- Entrada `AP-NNN` no Registro de erros indicado no `AGENTS.md` (padrão `.agents/rules/anti-patterns.md`): <sim ou não, e motivo>
- Sensor, regra ou teste adicional: <o que impede o retorno do defeito>
