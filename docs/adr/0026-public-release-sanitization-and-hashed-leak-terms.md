# ADR-0026: Higienização para Publicação e Hashes na Lista Anti-Vazamento

- Date: 2026-11-23
- Status: Accepted

## Context

Ao preparar o repositório espelho e o repositório canônico `ai-harness` para publicação aberta, identificou-se que a lista anti-vazamento em `scripts/harness/check_structure.py` e em `tests/harness/test_profiles.py` armazenava literais em texto claro de empregador, clientes e projetos privados anteriores. Além disso, ADRs e especificações antigas ainda mencionavam nomes internos de bases e repositórios privados, o workflow de sincronização gravava o SHA completo do repositório de origem nas mensagens de commit, faltava arquivo `LICENSE` e havia divergência de versão entre `pyproject.toml`, os manifestos de exportação e `plugin/plugin.json`.

Remover a proteção contra vazamento reduziria a defesa do harness contra regressões acidentais, enquanto manter os literais em texto claro no código-fonte exporia os próprios termos que deveriam permanecer privados.

## Decision

1. Substituir os literais privados de `LEAK_TERMS` em `scripts/harness/check_structure.py` por um conjunto de digests SHA-256 (`PRIVATE_TOKEN_HASHES`), verificados por token normalizado via `find_line_leaks`, mantendo `LEAK_TERMS` apenas para marcadores genéricos de ferramentas e placeholders.
2. Centralizar a verificação de `tests/harness/test_profiles.py` em `check_structure.find_line_leaks` e usar apenas canários sintéticos com `monkeypatch` em `tests/harness/test_check_structure.py`.
3. Higienizar `docs/adr/`, `README.md` e `specs/` substituindo nomes internos e caminhos locais absolutos por descrições genéricas.
4. Remover `SOURCE_SHA` da mensagem de commit de `.github/workflows/sync-claude.yml`, adotando mensagem genérica de sincronização.
5. Adicionar `LICENSE` (MIT) na raiz e no exportador `tools/export_claude.py`, e alinhar a versão do pacote e dos manifestos de exportação para `0.3.0`.
6. Exigir regeneração humana da baseline (`scripts/harness/check_tamper.py --update`) após revisão desta alteração, preservando a separação de privilégios sobre `harness/baseline.json`.

## Consequences

- O código-fonte público mantém a detecção determinística de regressões dos tokens privados sem revelar os termos originais em texto claro (assumindo exposição apenas em commits históricos caso o histórico completo fosse publicado; para repositórios derivados, recomenda-se iniciar com commit único).
- Os sensores de integridade (`check_controls.py` e `check_tamper.py`) acusam a alteração em `scripts/harness/check_structure.py` até que o mantenedor humano valide o diff e atualize `harness/baseline.json`.
- A exportação para o espelho passa a incluir `LICENSE`, versões consistentes e histórico livre de SHAs da matriz.
