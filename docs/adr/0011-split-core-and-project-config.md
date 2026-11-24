# ADR-0011: Split the harness configuration into core and project files

- Date: 2026-10-03
- Status: Accepted

## Context

`harness.toml` mixes harness-owned data (core gates, `[controls]`) with project data (name,
secret patterns, scan paths, stack gates). With the harness pushed to child repositories
(ADR-0010), an update can neither overwrite the file nor merge TOML with the stdlib (which reads
TOML but cannot write it), so new core gates would never reach a child.

## Decision

- `harness/core.toml` is harness-owned and holds only `[controls]` and the `core` gates.
- `harness.toml` holds only project data and project gates (`harness` and `stack` groups).
- `config.load` reads the core file first, then the project file. A project gate may not reuse
  a core gate name, and the controls baseline is the union of both files: a project can add a
  control, never remove one. A missing `harness/core.toml` is a configuration error.
- `verify.py --group <name>` runs one group, so CI can run only the core sensors.

## Consequences

- Easier: a new core gate reaches every child with the next update.
- Safer: deleting `harness/core.toml` fails every gate instead of silently dropping controls.
- Harder: a project cannot tune a core gate (for example its timeout); that needs a harness change.
