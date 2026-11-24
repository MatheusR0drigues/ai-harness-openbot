# ADR-0028: Fase 2 OpenBot — Modo Externo, Diff Secret Scan, PR via REST API e Portabilidade

- Date: 2026-11-24
- Status: Accepted

## Context

Após a adoção inicial do pacote `ai-harness-openbot` (`ADR-0027`) no container Linux do OpenBot, sessões reais levantaram cinco lacunas operacionais:

1. Repositórios com política que proíbe commitar arquivos do harness não podem hospedar `harness.toml`, `harness/` ou `scripts/harness/`, exigindo execução externa a partir de `/data/OpenBot/Shared/ai-harness-openbot` sem gravar arquivos no alvo, além de auditoria de segredos restrita ao diff (`--diff`) para não exigir baseline estático nem mascarar legado.
2. No container OpenBot, o servidor GitHub MCP retorna `404` em repositórios privados e o CLI `gh` não está instalado, bloqueando a abertura automatizada de Pull Requests.
3. A skill `repo-map` citava modelos fora da família Claude (`flash` / `flash_lite`) e o subagente `powerbi-architect` não explicitava o fallback estático quando `powerbi-modeling-mcp` (Windows) está indisponível em Linux.
4. O pack `bi-pbip` precisava validar estrutura/`$schema` PBIR e regras estáticas DAX/BPA (`DIVIDE()`, `VAR`/`RETURN`, `IFERROR`) sobre `.tmdl`.
5. Faltava uma skill padronizada (`ata-para-cartoes`) para converter atas (Granola, `.md`, `.xlsx`) em cartões do Trello sem inventar prazos.

## Decision

1. **Modo externo em `config.py`, `verify.py` e `doctor.py` + `--diff` em `check_secrets.py`:**
   - `config.load(path, harness_root=...)` faz fallback de `harness/core.toml` e `harness/packs/` para `harness_root` quando ausentes no repositório alvo.
   - `verify.py` e `doctor.py` aceitam `--repo-root <dir>` e `--config <caminho>`, executando gates no diretório alvo e dispensando `.agents/hooks.json` local em modo externo (preservando comportamento atual sem as flags).
   - `check_secrets.py` (espelhado byte-a-byte em `plugin/scripts/check_secrets.py`) passa a aceitar `--diff` e `--base <ref>` (padrão `origin/main` ou `HEAD`), auditando apenas linhas adicionadas/modificadas no diff git sem criar arquivo de baseline estático.
2. **Skill `pr-via-rest-api` + helper `stdlib-only` (`plugin/scripts/pr_via_rest_api.py`):**
   - Lê credenciais em memória via `git credential fill` (nunca em `argv`, variável de shell ou log), aplica sanitização `[REDACTED]` em erros, usa `urllib.request` apenas sobre `https://` com TLS verificado (`ssl.create_default_context()`) e timeout explícito.
3. **Portabilidade `repo-map` e `powerbi-architect`:**
   - `repo-map/SKILL.md` passa a orientar delegação ao `researcher` sem citar `flash`/`flash_lite`.
   - `powerbi-architect.md` documenta explicitamente o **Modo Estático** sobre arquivos `.pbip`/`.tmdl`/`.pbir` em ambientes Linux sem `mcp__powerbi-modeling`.
4. **Evolução do pack `bi-pbip`:**
   - `check_pbip_sanity.py` inclui validação de raiz objeto e `$schema` PBIR (obrigatório em `definition/` e `definition.pbir`) e lint estático DAX/BPA em `.tmdl` (`DIVIDE()`, `VAR`/`RETURN` em medidas complexas, `IFERROR()`), mantendo 100% `stdlib-only`.
5. **Skill `ata-para-cartoes`:**
   - Padroniza conversão de atas (texto colado, `.md`, `.xlsx`) para cartões Trello com regra estrita de preencher `due date` somente quando explícito na ata.

## Consequences

- Repositórios restritos podem ser auditados externamente via `--repo-root`, `--config` e `check_secrets.py --diff` sem poluir a árvore alvo.
- O fluxo OpenBot ganha abertura autônoma de PRs, pareceres Power BI consistentes em Linux, validação estática PBIR/DAX ampliada e conversão padronizada de atas.
- `harness/baseline.json` é atualizado para refletir os novos digests SHA-256 dos scripts em `scripts/harness/`.
