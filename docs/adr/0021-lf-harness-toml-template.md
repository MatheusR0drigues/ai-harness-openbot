# ADR-0021: Template `harness.toml` em LF no `init`

- Date: 2026-11-18
- Status: Accepted

## Context

`render_harness_toml` em `scripts/harness/init.py` localiza os placeholders do template com `(?m)^name = "projeto-sem-nome"$` e `(?m)^enabled = \[\]$`. No `re` do Python, `$` em modo multilinha casa só antes de `\n`, nunca antes de `\r\n`. Num clone do `ai-harness` no Windows com `core.autocrlf=true`, a regra `* text=auto` do `.gitattributes` grava `harness/templates/harness.toml` com CRLF no disco. Nesse caso nenhum placeholder casa e o `init` aborta com ``harness.toml template lost its `name`/`enabled` placeholders``, mesmo com o template intacto. O defeito apareceu ao instalar o kit em outro repositório.

## Decision

1. `render_harness_toml` converte `\r\n` em `\n` depois de decodificar o template e antes de aplicar as regex. O `harness.toml` projetado sai sempre em LF.
2. O `.gitattributes` passa a declarar `harness/templates/*.toml text eol=lf`, para que o checkout grave os templates TOML em LF em qualquer sistema.
3. `tests/harness/test_init.py::test_render_harness_toml_accepts_a_crlf_template` monta o template com CRLF em `tmp_path` e exige que a renderização preencha nome e packs sem deixar `\r`.

## Consequences

- O `init` funciona em clones Windows com `core.autocrlf=true`, mesmo que o `.gitattributes` não tenha sido aplicado ao checkout atual.
- Os demais templates (`.md`, `.json`, `.txt`) continuam copiados byte a byte (ou reserializados como JSON, no caso de `hooks.antigravity.json` com hooks de pack) e podem sair em CRLF. Eles não passam por regex e o `check_tamper` normaliza para LF antes do hash.
- Como `scripts/harness/init.py` mudou, o digest em `harness/baseline.json` precisa ser regenerado pelo humano com `python scripts/harness/check_tamper.py --update` (ADR-0014).
