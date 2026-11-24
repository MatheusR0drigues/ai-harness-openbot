# ADR-0009: Agents cannot edit the hook bootstrap root

- Date: 2026-10-02
- Status: Accepted

## Context

ADR-0008 allowed a full-file replacement of `scripts/harness/cli.py` after `compile()` passed.
That is insufficient: syntactically valid top-level code can still fail with `NameError`,
`re.error` or another initialization error before `main()` starts. Because `cli.py` performs the
recovery itself, such a failure removes both fail-closed response formatting and rollback. On
Kiro, a launcher exit 1 may be only a warning, so this can become fail-open.

A concurrent corrupt journal also cannot be proven unrelated to the valid recovery candidate.
Choosing the valid candidate would violate the unambiguous-recovery condition in ADR-0008.

## Decision

Block every agent write to `scripts/harness/cli.py`; the human must make intentional bootstrap
changes outside an agent session and run the full gate. During recovery, reject the operation if
any journal in the inspected state set is invalid or if the number of matching valid candidates
is not exactly one.

This ADR supersedes only ADR-0008's allowance for syntax-checked full-file writes to `cli.py`.
The transactional journal remains the recovery mechanism for the other protected modules.

## Consequences

- Safer: an agent cannot destroy the only code path capable of enforcing fail-closed recovery.
- Harder: changes to `cli.py` require a human-mediated edit.
- Safer: recovery prefers availability loss over guessing when concurrent state is corrupt.
- Unchanged: protected modules other than `cli.py` retain automatic transactional rollback.
