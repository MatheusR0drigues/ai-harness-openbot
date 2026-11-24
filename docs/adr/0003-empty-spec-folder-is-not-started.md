# ADR-0003: An empty spec folder counts as "not started"

- Date: 2026-10-01
- Status: Accepted

## Context

Kiro creates `.kiro/specs/<feature>/` before it writes `requirements.md`. While a spec session was
open in one chat, the Stop hook of another session ran `verify --fast` and the `specs` gate
failed twice with "requirements.md (or bugfix.md) is missing" for a folder that was simply empty.

## Decision

`validate_spec.py` treats an empty spec folder as a spec that has not started and reports no
problem. A folder with any file (e.g. `design.md` or `tasks.md`) but no `requirements.md` or
`bugfix.md` still fails.

## Consequences

- Easier: starting a spec in Kiro never turns the gate red in parallel sessions.
- Harder: an abandoned empty folder is not reported; it is harmless and can be deleted.
