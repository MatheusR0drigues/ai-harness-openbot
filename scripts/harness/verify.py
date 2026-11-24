"""Unified computational sensor: runs the configured gates and stops at the first failure.

Gates come from harness/core.toml + harness.toml + the enabled packs (`config.load`). Output is
written for an LLM consumer: which gate failed, the relevant lines, and a fix hint.
Exit code: 0 when every selected gate passes, 1 otherwise.

A gate with `requires_glob` runs only when at least one repository file matches the pattern;
otherwise it is reported as `SKIPPED: <gate> (...)` and never counts as a failure. The filter
lives in `run_gates` so both entry points honor it: `main` (CLI) and `hook.fast_verify` (Stop
hook), which calls `run_gates(select_gates(cfg.gates, fast=True), subprocess_runner)`.

Usage:
  python scripts/harness/verify.py                 # every gate
  python scripts/harness/verify.py --fast          # only gates with `fast = true` (between tasks)
  python scripts/harness/verify.py --group core    # only one group (core | harness | stack)
"""

from __future__ import annotations

import argparse
import fnmatch
import os

# Bandit B404: the harness runs the gate tools declared in its config (argv lists, no shell).
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import check_secrets
import config
from config import ConfigError, Gate

REPO_ROOT = config.REPO_ROOT
MAX_LINES = 40
SUCCESS_BANNER = "ALL GATES PASSED"
NO_STACK_WARNING = (
    "WARNING: no stack gates configured (see harness.toml and the harness-setup skill)"
)
TIMEOUT_EXIT = 124
NOT_FOUND_EXIT = 127
RERUN = "Re-run `python scripts/harness/verify.py` (add `--fast` between tasks)."
STALE_SHIM = "failed to canonicalize script path"
STALE_SHIM_HINT = (
    "The virtual-environment shim is stale. Run `python scripts/harness/doctor.py`, then "
    "`uv sync --reinstall`."
)


@dataclass(frozen=True, slots=True)
class RunResult:
    returncode: int
    output: str


Runner = Callable[[Sequence[str], int], RunResult]


def resolve_command(command: Sequence[str]) -> list[str]:
    """A leading `python` means "the interpreter running the harness", so gates use its venv."""
    resolved = list(command)
    if resolved and resolved[0] == "python":
        resolved[0] = sys.executable
    return resolved


def subprocess_runner(command: Sequence[str], timeout: int) -> RunResult:
    try:
        # Bandit B603: argv list from harness/core.toml, harness.toml or a pack, never a shell.
        completed = subprocess.run(  # nosec B603
            list(command),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return RunResult(TIMEOUT_EXIT, f"command timed out after {timeout}s")
    except FileNotFoundError:
        return RunResult(
            NOT_FOUND_EXIT,
            f"executable `{command[0]}` not found; install it or fix the gate command",
        )
    return RunResult(completed.returncode, completed.stdout + completed.stderr)


def select_gates(gates: Sequence[Gate], fast: bool, group: str = "") -> tuple[Gate, ...]:
    return tuple(g for g in gates if (g.fast or not fast) and (not group or g.group == group))


def glob_variants(pattern: str) -> frozenset[str]:
    """fnmatch patterns equivalent to `pattern` where `**/` may also match zero directories."""
    found = {pattern}
    pending = [pattern]
    while pending:
        current = pending.pop()
        candidates: list[str] = []
        if current.startswith("**/"):
            candidates.append(current[3:])
        if "/**/" in current:
            candidates.append(current.replace("/**/", "/", 1))
        for candidate in candidates:
            if candidate not in found:
                found.add(candidate)
                pending.append(candidate)
    return frozenset(found)


def has_matching_file(root: Path, pattern: str) -> bool:
    """True when a file under `root` (excluded dirs pruned) matches `pattern` (POSIX relative)."""
    variants = glob_variants(pattern)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in check_secrets.EXCLUDED_DIRS]
        base = Path(dirpath)
        for name in filenames:
            rel = (base / name).relative_to(root).as_posix()
            if any(fnmatch.fnmatchcase(rel, variant) for variant in variants):
                return True
    return False


def skip_reason(gate: Gate, root: Path, cache: dict[str, bool] | None = None) -> str | None:
    """Why a conditional gate does not run in `root`, or None when it must run."""
    if not gate.requires_glob:
        return None
    memo: dict[str, bool] = {} if cache is None else cache
    if gate.requires_glob not in memo:
        memo[gate.requires_glob] = has_matching_file(root, gate.requires_glob)
    if memo[gate.requires_glob]:
        return None
    return f"requires_glob {gate.requires_glob} matched no file"


def format_failure(gate: Gate, result: RunResult, max_lines: int = MAX_LINES) -> str:
    lines = [line for line in result.output.splitlines() if line.strip()]
    report = [
        f"GATE FAILED: {gate.name} (exit code {result.returncode})",
        f"Command: {' '.join(gate.command)}",
        "--- output ---",
        *lines[:max_lines],
    ]
    if len(lines) > max_lines:
        report.append(f"... ({len(lines) - max_lines} more lines truncated)")
    if STALE_SHIM in result.output.lower():
        report += ["--- environment diagnosis ---", STALE_SHIM_HINT]
    report += ["--- fix hint ---", gate.hint, RERUN]
    return "\n".join(report)


def run_gates(
    gates: Sequence[Gate],
    runner: Runner,
    max_lines: int = MAX_LINES,
    root: Path = REPO_ROOT,
) -> tuple[bool, str]:
    """Run gates in order; conditional gates without matching files are skipped, not failed."""
    passed: list[str] = []
    skipped: list[str] = []
    cache: dict[str, bool] = {}
    for gate in gates:
        reason = skip_reason(gate, root, cache)
        if reason is not None:
            skipped.append(f"SKIPPED: {gate.name} ({reason})")
            continue
        result = runner(resolve_command(gate.command), gate.timeout)
        if result.returncode != 0:
            header = f"Passed: {', '.join(passed)}" if passed else "Passed: (none)"
            report = [header, *skipped, format_failure(gate, result, max_lines)]
            return False, "\n".join(report)
        passed.append(gate.name)
    banner = f"{SUCCESS_BANNER} ({', '.join(passed) or 'none'})"
    return True, "\n".join([banner, *skipped])


def _escape_unencodable_output() -> None:
    """Gate output may hold characters a legacy Windows code page cannot encode: escape them.

    Only the error handler changes; the console encoding stays. Called from `main` so that
    `cli.py verify` (ADR-0009) gets the same behavior as running this file directly.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def main(
    argv: Sequence[str] | None = None,
    runner: Runner = subprocess_runner,
    config_path: Path | None = None,
    root: Path | None = None,
) -> int:
    _escape_unencodable_output()
    parser = argparse.ArgumentParser(description="Run the harness gates.")
    parser.add_argument("--fast", action="store_true", help="only gates marked fast = true")
    parser.add_argument(
        "--group", choices=config.GROUPS, default="", help="only gates of this group (CI: core)"
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        cfg = config.load(config_path)
    except ConfigError as exc:
        print(f"HARNESS CONFIG INVALID: {exc}")
        print(
            "--- fix hint ---\nFix harness.toml or harness/core.toml; the schema is documented "
            "in scripts/harness/config.py."
        )
        return 1
    selected = select_gates(cfg.gates, args.fast, args.group)
    if args.group and not selected:
        print(f"HARNESS CONFIG INVALID: no gates in group `{args.group}`")
        return 1
    ok, report = run_gates(selected, runner, root=REPO_ROOT if root is None else root)
    print(report)
    # The `harness` group is the stack of a harness source repository (its own tests and lint).
    if not any(g.group in ("stack", "harness") for g in cfg.gates):
        print(NO_STACK_WARNING)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
