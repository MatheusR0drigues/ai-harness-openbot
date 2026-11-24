# ADR-0007: Diagnose the harness environment with allowlisted probes

- Date: 2026-10-02
- Status: Accepted

## Context

Stale virtual-environment shims made `uv run pyright` and `uv run pytest` fail with
`Failed to canonicalize script path`. The failure looked like a gate problem and caused repeated
workarounds before `uv sync --reinstall` repaired the environment.

Gate commands are project data and may name arbitrary programs. A diagnostic must not execute
every configured gate merely to obtain a version.

## Decision

Add an explicit stdlib-only `doctor` command. Resolve every gate's top-level executable without
running it, and execute bounded `--version` probes only for the fixed harness tools `ruff`,
`pyright` and `pytest` through `uv run --no-sync`. Recognize the stale-shim error and recommend
`uv sync --reinstall`. Keep the doctor outside gates and hooks.

## Consequences

- Easier: environment failures have one deterministic diagnosis and repair hint.
- Harder: unknown stack tools are checked only for PATH resolution, not functionality.
- Safer: no shell is used, every probe has a timeout, and arbitrary gate commands never run.
- Unchanged: the doctor reports repairs but never changes the environment automatically.
