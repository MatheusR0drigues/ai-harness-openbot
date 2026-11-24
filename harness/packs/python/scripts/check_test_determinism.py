"""Gate: unit tests must not read the real clock, sleep for real, or probe real processes.

The scan uses the AST, so string literals and comments never match. Rules:
  clock    datetime.now/utcnow/today, date.today, time.time, time.time_ns
  sleep    time.sleep
  process  importing psutil

Usage:
  python harness/packs/python/scripts/check_test_determinism.py [PATH ...]
      [--exclude GLOB] [--clock-hint TEXT] [--sleep-hint TEXT] [--process-hint TEXT]

Without PATH it scans `tests/` under the repository root (the closest folder above the cwd
holding harness.toml or .git). The hints are the replacement each project recommends (for
example, its own fake clock fixture). A line carrying `determinism: allow` (in a comment)
accepts one proven exception.

Exit code: 0 when clean, 1 when violations exist, 2 on usage errors. Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT_MARKERS = ("harness.toml", ".git")
DEFAULT_TARGET = "tests"
ALLOW_MARKER = "determinism: allow"
EXCLUDED_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__"})

CLOCK_CALLS = frozenset(
    {
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "time.time",
        "time.time_ns",
    }
)
SLEEP_CALLS = frozenset({"time.sleep"})
PROCESS_MODULES = frozenset({"psutil"})

DEFAULT_HINTS: dict[str, str] = {
    "clock": "inject a clock the test controls (a fixture returning a fixed instant)",
    "sleep": "unit tests never wait for real: inject the clock or scheduler and advance it",
    "process": "inject a fake process probe instead of querying the real system",
}


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    line: int
    rule: str
    detail: str

    def render(self, hints: dict[str, str]) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}: {hints[self.rule]}"


def find_root(start: Path | None = None) -> Path:
    """Closest folder at or above `start` (default: cwd) holding harness.toml or .git."""
    origin = (Path.cwd() if start is None else start).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return origin


def _dotted(node: ast.expr) -> str:
    """`a.b.c` for a chain of attributes over a name; empty for anything else."""
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    parts.append(current.id)
    return ".".join(reversed(parts))


class DeterminismVisitor(ast.NodeVisitor):
    """Collect forbidden clock, sleep and process calls, resolving import aliases."""

    def __init__(self, path: str, allowed_lines: frozenset[int]) -> None:
        self.path = path
        self.allowed_lines = allowed_lines
        self.aliases: dict[str, str] = {}
        self.violations: list[Violation] = []

    def _add(self, line: int, rule: str, detail: str) -> None:
        if line not in self.allowed_lines:
            self.violations.append(Violation(self.path, line, rule, detail))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] in PROCESS_MODULES:
                self._add(node.lineno, "process", f"import {alias.name}")
            local = alias.asname or alias.name.split(".")[0]
            self.aliases[local] = alias.name if alias.asname else local
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level == 0 and module.split(".")[0] in PROCESS_MODULES:
            self._add(node.lineno, "process", f"from {module} import ...")
        for alias in node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            self.aliases[alias.asname or alias.name] = full
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted:
            head, _, rest = dotted.partition(".")
            resolved = self.aliases.get(head, head) + (f".{rest}" if rest else "")
            if resolved in CLOCK_CALLS:
                self._add(node.lineno, "clock", f"{dotted}()")
            elif resolved in SLEEP_CALLS:
                self._add(node.lineno, "sleep", f"{dotted}()")
        self.generic_visit(node)


def _allowed_lines(source: str) -> frozenset[int]:
    return frozenset(
        number for number, line in enumerate(source.splitlines(), start=1) if ALLOW_MARKER in line
    )


def check_source(source: str, path: str) -> list[Violation]:
    """Violations in one Python source; a syntax error is reported as a violation."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [Violation(path, exc.lineno or 0, "syntax", "file cannot be parsed")]
    visitor = DeterminismVisitor(path, _allowed_lines(source))
    visitor.visit(tree)
    return visitor.violations


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def iter_python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    return sorted(
        path
        for path in target.rglob("*.py")
        if not any(part in EXCLUDED_DIRS for part in path.relative_to(target).parts[:-1])
    )


def check_paths(
    targets: Sequence[Path], root: Path, exclude: Sequence[str] = ()
) -> list[Violation]:
    violations: list[Violation] = []
    for target in targets:
        for path in iter_python_files(target):
            rel = _relative(path, root)
            if any(fnmatch.fnmatch(rel, pattern) for pattern in exclude):
                continue
            source = path.read_text(encoding="utf-8-sig", errors="replace")
            violations.extend(check_source(source, rel))
    return violations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that tests use no real clock, real sleep or real process probe."
    )
    parser.add_argument("paths", nargs="*", help=f"folders or files (default: {DEFAULT_TARGET})")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="repository-relative glob to skip (repeatable)",
    )
    parser.add_argument("--clock-hint", default=DEFAULT_HINTS["clock"])
    parser.add_argument("--sleep-hint", default=DEFAULT_HINTS["sleep"])
    parser.add_argument("--process-hint", default=DEFAULT_HINTS["process"])
    return parser


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    repo = find_root() if root is None else root
    raw_paths: list[str] = list(args.paths)
    exclude: list[str] = list(args.exclude)
    hints = {
        "clock": str(args.clock_hint),
        "sleep": str(args.sleep_hint),
        "process": str(args.process_hint),
        "syntax": "fix the syntax error",
    }
    targets: list[Path] = []
    for raw in raw_paths:
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else repo / candidate
        if not candidate.exists():
            print(f"ERROR: path does not exist: {raw}")
            return 2
        targets.append(candidate)
    if not raw_paths:
        default = repo / DEFAULT_TARGET
        if not default.is_dir():
            print(f"TEST DETERMINISM PASSED: no {DEFAULT_TARGET}/ folder, nothing to check.")
            return 0
        targets.append(default)
    violations = check_paths(targets, repo, exclude)
    if not violations:
        print("TEST DETERMINISM PASSED")
        return 0
    print(f"TEST DETERMINISM FAILED: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  {violation.render(hints)}")
    print(f"Proven exception only: append `# {ALLOW_MARKER}` to that line.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
