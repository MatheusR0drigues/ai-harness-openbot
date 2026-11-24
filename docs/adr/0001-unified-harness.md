# ADR-0001: One harness for Codex, Claude Code, Kiro and Antigravity

- Date: 2026-10-01
- Status: Accepted (multi-IDE sync superseded by ADR-0012; Antigravity-first)

## Context

The template must drive four agents with different file locations, hook schemas and payloads,
stay free of any stack or domain, run on Windows, macOS and Linux, and be copied into new
projects without a sync mechanism. Symlinks are unreliable on Windows checkouts.

## Decision

Keep one canonical source and thin adapters:

- `AGENTS.md` is the single instruction file; rules and skills live in `.agents/` (the format
  Codex and Antigravity read natively) and are copied to `.claude/` and `.kiro/` by
  `scripts/harness/sync_adapters.py`, with a hash manifest that refuses hand edits.
- Gates are data in `harness.toml`, run by one runner (`verify.py`); stacks come from optional
  profiles in `harness/profiles/`.
- Every agent's hook config calls one dispatcher with an explicit `--agent`; guards are shared
  and the pre-tool path fails closed. Runtime code is Python 3.11+ stdlib only, behind a
  cross-platform launcher with a quoted path.
- Planner, Generator and Evaluator are portable skills, not native subagent files.

## Consequences

- Easier: one place to change guidance or a guard; the same protection in all four agents;
  projects specialize by editing data.
- Harder: generated copies must be refreshed (post hook and the `adapters` gate do it); payload
  formats must be re-measured when an agent changes (`tools/dump_hook_payload.py`).
- Forbidden: editing generated adapters, symlinking guidance, shell-string gate commands, and
  weakening a gate, hook or guard without a new ADR.
