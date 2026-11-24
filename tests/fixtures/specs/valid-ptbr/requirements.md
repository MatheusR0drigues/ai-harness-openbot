# Requisitos: Exportação de Relatórios

## Introdução

Exportar o relatório mensal de chamados em CSV pela linha de comando.

## Requisitos

### Requisito 1: Exportação em CSV

**História:** Como analista, quero exportar o relatório mensal em CSV, para abrir os dados em uma planilha.

#### Critérios de Aceite

1. QUANDO o analista executar `relatorio exportar --mes 2026-01`, o sistema DEVE gravar `relatorio-2026-01.csv` em até 5 segundos para até 10000 linhas.
2. SE o mês informado não tiver chamados, ENTÃO o sistema DEVE gravar apenas o cabeçalho e encerrar com código 0.

### Requisito 2: Validação de Entrada

**Historia:** Como analista, quero mensagens objetivas para entradas inválidas, para corrigir o comando sem consultar o código.

#### Criterios de Aceite

1. SE o argumento `--mes` não seguir o formato `AAAA-MM`, ENTÃO o sistema DEVE encerrar com código 2 e imprimir o formato esperado.
2. ENQUANTO uma exportação estiver em andamento, as demais execuções DEVEM aguardar a liberação do arquivo de trava por até 30 segundos.
3. ONDE a opção `--separador` for informada, o sistema DEVE usar o caractere informado como delimitador.

## Fora de Escopo

- Exportação em formatos diferentes de CSV.
- Agendamento automático da exportação.
