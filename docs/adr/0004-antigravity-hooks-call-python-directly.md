# ADR-0004: Antigravity hooks call the CLI through python, without quotes

- Date: 2026-10-01
- Status: Accepted

## Context

The other agents run hook commands through cmd.exe on Windows, which rejects an unquoted
forward-slash program path, so their configs quote the launcher (AP-001). Measured live,
Antigravity escapes the quotes before cmd.exe sees them: every PreToolUse call failed with
`'\"scripts/harness/bin/harness\"' is not recognized as an internal or external command`.
Antigravity treated the failing hook as a block, so all nine test steps were blocked, including
plain reads.

## Decision

Antigravity hook commands are `python ../scripts/harness/cli.py hook <event> --agent antigravity`,
with no double quotes. cmd.exe accepts forward slashes in arguments, and `cli.py` still checks
the Python version. `check_structure.check_hooks` rejects any double quote in an Antigravity
command.

## Consequences

- Easier: Antigravity hooks run on Windows.
- Harder: the command needs `python` on PATH pointing to Python 3.11+. On macOS/Linux where only
  `python3` exists, change the executable in `.agents/hooks.json` (documented in
  `docs/agent-setup.md`). The launcher's `python3`/`py -3` fallback does not apply here.

## Addendum (same day)

Antigravity runs hook commands with the working directory set to `.agents/` (the folder of`nhooks.json`), not the project root (measured live: `python: can't open file '...\.agents\scripts\harness\cli.py'`).`nPaths in `.agents/hooks.json` are therefore written as `../scripts/...`; `check_hooks` enforces it.
