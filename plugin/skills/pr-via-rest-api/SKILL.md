---
name: pr-via-rest-api
description: "Cria Pull Requests no GitHub via API REST HTTPS usando git credential fill em memória quando o GitHub MCP retorna 404 em repositórios privados ou quando o CLI gh não está disponível."
---

# Pull Request via GitHub REST API (`pr-via-rest-api`)

Padroniza a criação de Pull Requests via HTTPS REST API usando o helper `stdlib-only` em `../../scripts/pr_via_rest_api.py`, sem depender do CLI `gh` nem do servidor GitHub MCP.

## Quando Usar

- Quando o GitHub MCP retornar `404` / falta de permissão em repositórios privados.
- Quando o binário `gh` não estiver instalado no container ou ambiente de execução.
- Sempre que for necessário abrir um PR (normal ou `--draft`) a partir de uma branch já enviada (`git push`) para o remoto.

## Pré-condições

1. A branch de origem (`--head`) já deve existir no remoto `origin`.
2. O helper `git credential fill` deve estar configurado para o host alvo (ex.: `github.com`).
3. O usuário solicitou explicitamente a criação do PR (nunca faça push ou abra PR sem pedido explícito).

## Como Executar

```bash
python ../../scripts/pr_via_rest_api.py \
  --base main \
  --title "feat: resumo objetivo da mudanca" \
  --body "Contexto e verificacoes executadas."
```

Opções suportadas:
- `--base <branch>`: branch de destino (padrão `main`).
- `--head <branch>`: branch de origem (detectada automaticamente do `HEAD` atual quando omitida).
- `--title <texto>`: título do PR (obrigatório).
- `--body <texto>` ou `--body-file <caminho>`: descrição objetiva (opcional, mutuamente exclusiva; não exige template, labels ou reviewers).
- `--draft`: cria o PR em modo rascunho.
- `--repo <owner/repo>`: slug explícito (detectado do remoto `origin` quando omitido).
- `--repo-root <dir>`: raiz do repositório git alvo.

## Garantias de Segurança (`LLM02` / `ASI02`)

- **Zero vazamento de token:** o helper lê `password=` de `git credential fill` apenas em memória pelo Python; o token nunca passa por `argv`, variável de shell ou log, e qualquer resposta de erro tem o token substituído por `[REDACTED]`.
- **TLS verificado e timeout explícito:** usa `urllib.request` apenas sobre `https://` com `ssl.create_default_context()` (`verify=True`) e timeout explícito (padrão `30s`).
