# ADR-0008: Recover hook-critical modules from a pre-write journal

- Date: 2026-10-02
- Status: Accepted

## Context

A syntax or import-time error in `guards.py` or one of its dependencies prevents `hook.py` from
importing. The bootstrap then fails closed and blocks every guarded tool, including the write that
would repair the module. Three incidents required human intervention. A syntax-only `compile()`
check would not detect the observed top-level `NameError` and `re.error` failures.

Allowing arbitrary replacement code while the normal guards are unavailable would duplicate the
security policy in a weaker recovery path. Reconstructing and importing every agent's prospective
patch would be complex and could execute proposed code before it is accepted.

## Decision

After all normal guards allow a write to a hook-critical Python module, atomically journal its
exact current bytes for 30 seconds. Syntax-check full-file writes before allowing them. If the
next hook cannot import and its traceback names the journaled module, restore only those exact
bytes, verify that the hook imports again, consume the journal and block the current call with a
recovery report. Without one recent, valid, unambiguous journal, remain fail-closed.

Keep the journal and recovery primitives in `cli.py`, the minimal bootstrap that runs before
`hook.py`. Require full-file writes for `cli.py` itself because it is the recovery root.

## Consequences

- Easier: observed syntax, name and regex initialization failures recover without a human.
- Harder: `cli.py` owns a small, Python-3.6-parseable journal implementation and is more critical.
- Safer: recovery never accepts new code, never runs a shell and cannot target paths outside an
  explicit module allowlist.
- Residual risk: the temporary journal is a tripwire, not a sandbox against a process with local
  filesystem access; a same-file human edit inside the short transaction window is ambiguous.
- Forbidden: widening recovery to arbitrary paths or replacement content without a superseding ADR.
