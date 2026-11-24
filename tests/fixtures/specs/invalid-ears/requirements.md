# Requisitos: Palavra-chave EARS

### Requisito 1: Critérios sem palavra-chave

**História:** Como revisor, quero critérios com palavra-chave EARS, para verificar cada um por teste.

#### Critérios de Aceite

1. QUANDO o arquivo for salvo, o sistema grava um backup em `backup/`.
2. QUANDO o arquivo for salvo, o sistema deve registrar a data no log.
3. O sistema registra o evento com a palavra `SHALL` apenas dentro de código.
4. QUANDO houver mais de um processo, os processos DEVEM usar o mesmo arquivo de trava.

## Fora de Escopo

- Restauração automática de backups.
