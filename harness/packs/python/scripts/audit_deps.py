"""Gate: audit every locked dependency (uv.lock) for known vulnerabilities with pip-audit.

Steps: `uv export --frozen` writes the exact locked versions to a temporary requirements file,
then `uv run --frozen pip-audit -r <file> --no-deps --disable-pip` checks them against the
public vulnerability data. The project declares pip-audit as an exactly pinned dev dependency
(`uv add --dev pip-audit==<version>`).

This gate needs the network. Offline it FAILS with a clear message; it is never skipped.
Stdlib only: runs as `python harness/packs/python/scripts/audit_deps.py` from the repository
root (or any folder below it).

Exit code: 0 when no known vulnerability is found, 1 otherwise (including offline, missing
tools and `uv export` errors), 2 on usage errors.
"""

from __future__ import annotations

import argparse

# Bandit B404: runs uv with fixed argument lists (no shell).
import subprocess  # nosec B404
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

OK_BANNER = "DEPENDENCY AUDIT OK"
FAIL_BANNER = "DEPENDENCY AUDIT FAILED"
ROOT_MARKERS = ("harness.toml", ".git")
EXPORT_TIMEOUT = 120
AUDIT_TIMEOUT = 280
NETWORK_MARKERS = (
    "ConnectionError",
    "Max retries exceeded",
    "NameResolutionError",
    "getaddrinfo failed",
    "Temporary failure in name resolution",
    "timed out",
)
MISSING_TOOL_MARKERS = (
    "Failed to spawn",
    "No such file or directory",
    "program not found",
)
OFFLINE_HINT = (
    "pip-audit could not reach the vulnerability service: re-run when online "
    "(this gate is never skipped)."
)
MISSING_TOOL_HINT = (
    "pip-audit (or uv) is not available in the project environment: add it with an exact pin "
    "(`uv add --dev pip-audit==<version>`) and run `uv sync`."
)
EXPORT_HINT = "`uv export --frozen` failed: check that uv.lock exists and is current (`uv lock`)."


@dataclass(frozen=True, slots=True)
class Completed:
    returncode: int
    output: str


Runner = Callable[[Sequence[str]], Completed]


def find_root(start: Path | None = None) -> Path:
    """Closest folder at or above `start` (default: cwd) holding harness.toml or .git."""
    origin = (Path.cwd() if start is None else start).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return origin


def subprocess_runner(root: Path) -> Runner:
    """Real runner: argv lists only, cwd = repository root, bounded by a timeout."""

    def run(command: Sequence[str]) -> Completed:
        timeout = AUDIT_TIMEOUT if "pip-audit" in command else EXPORT_TIMEOUT
        try:
            # Bandit B603: argv is built from constants and a temporary file path.
            done = subprocess.run(  # nosec B603
                list(command),
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError:
            return Completed(127, f"{command[0]}: program not found")
        except subprocess.TimeoutExpired:
            return Completed(124, f"{command[0]}: timed out after {timeout}s")
        return Completed(done.returncode, done.stdout + done.stderr)

    return run


def export_command(target: Path) -> list[str]:
    return [
        "uv",
        "export",
        "--frozen",
        "--all-groups",
        "--no-hashes",
        "--no-emit-project",
        "--output-file",
        str(target),
    ]


def audit_command(requirements: Path) -> list[str]:
    return [
        "uv",
        "run",
        "--frozen",
        "pip-audit",
        "--requirement",
        str(requirements),
        "--no-deps",  # the export already lists every transitive package, pinned
        "--disable-pip",
        "--progress-spinner",
        "off",
    ]


def is_network_error(output: str) -> bool:
    return any(marker in output for marker in NETWORK_MARKERS)


def is_missing_tool(output: str) -> bool:
    return any(marker in output for marker in MISSING_TOOL_MARKERS)


def audit(runner: Runner, workdir: Path) -> tuple[bool, str]:
    """Run export + audit through `runner`; return (ok, report)."""
    requirements = workdir / "requirements-locked.txt"
    exported = runner(export_command(requirements))
    if exported.returncode != 0:
        output = exported.output.strip()
        hint = MISSING_TOOL_HINT if is_missing_tool(output) else EXPORT_HINT
        return False, f"{FAIL_BANNER}: {hint}\n{output[-2000:]}"
    result = runner(audit_command(requirements))
    output = result.output.strip()
    if result.returncode == 0:
        summary = output.splitlines()[-1] if output else ""
        return True, f"{OK_BANNER}: {summary}".rstrip()
    if is_network_error(output):
        return False, f"{FAIL_BANNER}: {OFFLINE_HINT}\n{output[-2000:]}"
    if is_missing_tool(output):
        return False, f"{FAIL_BANNER}: {MISSING_TOOL_HINT}\n{output[-2000:]}"
    return False, (
        f"{FAIL_BANNER}: known vulnerabilities in locked dependencies; upgrade each package "
        f"to a fixed version with an exact pin\n{output}"
    )


def main(
    argv: Sequence[str] | None = None,
    root: Path | None = None,
    *,
    runner: Runner | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Audit the dependencies locked in uv.lock.")
    parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    repo = find_root() if root is None else root
    if not (repo / "uv.lock").is_file():
        print(f"{FAIL_BANNER}: uv.lock not found in {repo.as_posix()}; run `uv lock`.")
        return 1
    run = subprocess_runner(repo) if runner is None else runner
    with tempfile.TemporaryDirectory() as tmp:
        ok, report = audit(run, Path(tmp))
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
