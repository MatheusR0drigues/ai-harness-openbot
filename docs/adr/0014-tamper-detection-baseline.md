# ADR-0014: Baseline deterministico de deteccao de adulteracao do harness

- Date: 2026-11-13
- Status: Accepted

## Context

Guardas de `PreToolUse` (`privileged_config` e `harness_integrity`) reduzem o risco de alteracao via ferramentas do agente, mas um comando shell ofuscado ou uma edicao externa fora da sessao ainda pode modificar `.agents/hooks.json`, `harness/core.toml` ou `scripts/harness/*.py`.

Antes desta decisao nao havia um sensor criptografico deterministico comparando esses arquivos criticos contra uma assinatura conhecida no inicio e no encerramento da sessao nem no gate `controls`.

## Decision

Adotar `scripts/harness/check_tamper.py` com baseline SHA-256 normalizado em LF em `harness/baseline.json` cobrindo `.agents/hooks.json`, `harness/core.toml` e todos os modulos `scripts/harness/*.py`:

1. `scripts/harness/init.py` gera `harness/baseline.json` como arquivo gerenciado pelo kit durante a projecao em repositorios-alvo, a partir do conteudo exato projetado (incluindo hooks de packs ativos).
2. `harness/baseline.json` integra a superficie privilegiada protegida por `privileged_config` (inclusive em operacoes de parent folder/glob e redirecionamentos), exigindo acao explicita do humano (`python scripts/harness/check_tamper.py --update`) para atualizar hashes.
3. O sensor e verificado em tres pontos sem depender de rede ou timestamps: `SessionStart` (`hook.default_config_notice` via `injectSteps`), `Stop` (`hook.handle_stop` interrompendo com `decision: stop` e aviso explicito se houver divergencia) e no gate `controls` (`check_controls.main`).

## Consequences

- Adulteracoes silenciosas, remocoes ou adicoes inesperadas em `.agents/hooks.json`, `harness/core.toml` ou `scripts/harness/*.py` passam a ser detectadas na abertura da sessao, no fechamento e no gate obrigatorio `controls`.
- Como contrapartida operacional, qualquer edicao humana intencional nesses arquivos exige executar `uv run python scripts/harness/check_tamper.py --update` antes dos gates finais.
- Um atacante com acesso direto ao sistema de arquivos fora dos hooks continua podendo recalcular `harness/baseline.json`; o sensor detecta adulteracao acidental ou por bypass parcial do agente, nao substitui controles de SO ou assinatura remota (registrado em `docs/llm-threat-model.md`).
