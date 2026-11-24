---
trigger: glob
globs: "**/*.js, **/*.jsx, **/*.ts, **/*.tsx, **/*.mjs, **/*.cjs"
description: "Padrões Node.js e TypeScript do pack node: dependências fixadas, tipagem estrita e segurança."
---

# Diretrizes Node.js e TypeScript

Vale para arquivos JavaScript e TypeScript do projeto. Os gates do pack `node` executam os
scripts `lint`, `typecheck` e `test` do `package.json` e o `npm audit`.

## Dependências e scripts

- Use um único gerenciador de pacotes por projeto e versione o lockfile correspondente.
- Toda dependência nova tem versão exata (`npm install --save-exact`, ou `save-exact=true` no
  `.npmrc`), é conhecida e mantida, e é citada para o humano antes de entrar.
- Em CI e em ambientes descartáveis, instale com `npm ci` para respeitar o lockfile.
- Desconfie de pacotes com scripts `postinstall`; avalie com `npm install --ignore-scripts`
  quando a origem não for confiável.
- O `package.json` define os scripts `lint`, `typecheck` e `test`; os gates dependem deles.

## Tipagem estrita

- `tsconfig.json` com `"strict": true`, `"noUncheckedIndexedAccess": true` e
  `"noImplicitOverride": true`.
- Evite `any`. Para dados externos use `unknown` e valide o formato antes de usar.
- `@ts-ignore` é proibido; use `@ts-expect-error` com o motivo na mesma linha.
- Prefira tipos de união discriminada e `readonly` a flags booleanas e objetos mutáveis.

## Erros

- Não engula erros: todo `catch` trata, registra com contexto ou propaga.
- Toda `Promise` é aguardada ou tem tratamento explícito de rejeição; nada de promessas soltas.
- Lance instâncias de `Error` (ou subclasses), nunca strings.

## Segurança

- Proibido `eval`, `new Function` e `setTimeout`/`setInterval` com string.
- Processos externos com `execFile` ou `spawn` e lista de argumentos; nunca `exec` com string
  montada nem `shell: true`.
- Toda chamada de rede tem timeout (`AbortSignal.timeout(...)` no `fetch`). Proibido
  `rejectUnauthorized: false` ou `NODE_TLS_REJECT_UNAUTHORIZED=0`.
- Valide entradas na fronteira (HTTP, CLI, arquivos, variáveis de ambiente) com um esquema
  explícito; rejeite chaves como `__proto__` e `constructor` ao mesclar objetos.
- Saída para HTML é escapada pelo framework; `innerHTML` e `dangerouslySetInnerHTML` só com
  conteúdo sanitizado e motivo registrado.
- Caminhos vindos de entrada externa: resolva com `path.resolve` e confirme que continuam dentro
  da pasta permitida.
- Segredos vêm do ambiente ou de um cofre; nunca no código, no bundle do cliente, nos logs ou
  nos testes.

## Testes

- Testes são determinísticos: relógio falso (`useFakeTimers` ou injeção de relógio), sem rede
  real e sem dependência da ordem de execução.
- Correção de bug começa por um teste de regressão que falha antes da correção.
- Nunca use `.skip`/`.only` nem afrouxe asserções para fazer um gate passar.

## Gates do pack

| Gate | Comando |
| :-- | :-- |
| `node-lint` | `npm run lint` |
| `node-types` | `npm run typecheck` |
| `node-tests` | `npm test` |
| `node-audit` | `npm audit --audit-level=high` |
