"""Gate: comments and docstrings describe the present code, not its history.

Dates, notebook cell numbers, banners, version history and patch labels age silently and
pollute the context of whoever reads the file next, human or agent. The scan covers comments
and docstrings of `.py` files plus markdown cells and comments of `.ipynb` notebooks; string
literals in code are data and never match.

Rules:
  DATE     a calendar date (YYYY-MM-DD or DD/MM/YYYY), except API versions and format examples
  CELL     a notebook cell number ("cell N", "celula N")
  BANNER   a run of five or more `-`, `=`, `#`, `*`, `~` or `_` in a comment
  VERSION  version history ("since vN", "desde a vN", "vN to vM")
  LABEL    an uppercase patch label opening a comment (FIX, NEW, CHANGED, NOVO, CORRECAO, ...)

Scope comes from `[comments]` in harness.toml (read with tomllib): `include` globs (empty =
whole repository) and `exempt_paths` prefixes. Explicit PATH arguments skip `include` but still
honour `exempt_paths`. A line carrying `comments: allow` accepts one proven false positive.

Usage: python harness/packs/python/scripts/verificar_comentarios.py [PATH ...]
Exit code: 0 when clean, 1 when violations exist, 2 on configuration or read errors.
Stdlib only.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import io
import json
import os
import re
import sys
import tokenize
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT_MARKERS = ("harness.toml", ".git")
CONFIG_FILE = "harness.toml"
COMMENTS_KEYS = frozenset({"include", "exempt_paths"})
EXTENSIONS = (".py", ".ipynb")
ALLOW_MARKER = "comments: allow"
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".ipynb_checkpoints",
    }
)

DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b(?!-preview)|\b\d\d/\d\d/20\d\d\b")
API_VERSION = re.compile(r"api[-_]version", re.IGNORECASE)
EXAMPLE_BEFORE = re.compile(
    r"(?:\bex\.?:|\bexemplo:?|\bexample:?|\be\.g\.,?|\bformato:?|\bformat:?)\s*[`'\"(]*$",
    re.IGNORECASE,
)

RULES: dict[str, re.Pattern[str]] = {
    "DATE": DATE,
    "CELL": re.compile(r"\bc[ée]lulas?\s+\d+\b|\bcells?\s+\d+\b", re.IGNORECASE),
    "BANNER": re.compile(r"([-=#*~_])\1{4,}"),
    "VERSION": re.compile(
        r"\bv\d+\s+(?:a|to)\s+v\d+\b"
        r"|\b(?:até|ate|desde|antes\s+d[oa]|since|until|before)\s+(?:o\s+|a\s+|the\s+)?v\d+\b",
        re.IGNORECASE,
    ),
    # Uppercase on purpose: "# New items start open" is a sentence, not a label.
    "LABEL": re.compile(
        r"^(?:CORREÇÃO|CORRECAO|NOVO|NOVA|FIX|FIXED|ALTERADO|MODIFICADO|CHANGED|MODIFIED|NEW)\b"
        r"|\((?:FIX|Modificad[oa]|Modified|Changed)\)"
    ),
}

# Banners and labels only exist in comments: in a docstring a dashed line underlines a section.
COMMENT_ONLY = frozenset({"BANNER", "LABEL"})

REPAIR: dict[str, str] = {
    "DATE": (
        "remove the date. History or evidence (decision, incident, measurement) belongs in an "
        "ADR under docs/adr/, in the spec or in the commit message; the comment keeps only the "
        "current reason and may cite that record."
    ),
    "CELL": (
        "cite the function, constant or section title, not the position: inserting a cell "
        "shifts the number and the comment starts to lie."
    ),
    "BANNER": "replace the frame with a one-line title (# Title).",
    "VERSION": (
        "describe the current behavior. Earlier versions live in the git history and the ADRs."
    ),
    "LABEL": (
        "a patch label (FIX, NEW, CHANGED) tells the story of the change; describe what the "
        "code does and why."
    ),
}

FOOTER = "Full rule: .agents/rules/python.md, section 'Comentários e docstrings'."


class CommentsConfigError(ValueError):
    """harness.toml `[comments]` cannot be read or does not match the schema."""


@dataclass(frozen=True, slots=True)
class Settings:
    include: tuple[str, ...] = ()
    exempt_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Unit:
    """One line of a comment, docstring or markdown cell."""

    line: int
    text: str
    kind: str  # comment | docstring | markdown
    cell: int | None = None


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    unit: Unit
    rule: str

    def location(self) -> str:
        if self.unit.cell is None:
            return f"{self.path}:{self.unit.line}"
        return f"{self.path}:cell {self.unit.cell}:line {self.unit.line}"


def find_root(start: Path | None = None) -> Path:
    """Closest folder at or above `start` (default: cwd) holding harness.toml or .git."""
    origin = (Path.cwd() if start is None else start).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return origin


def _string_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CommentsConfigError(f"{where} must be a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) and item for item in items):
        raise CommentsConfigError(f"{where} must be a list of non-empty strings")
    return tuple(cast(list[str], items))


def load_settings(root: Path) -> Settings:
    """`[comments]` of root/harness.toml; a missing file or table means the whole repository."""
    path = root / CONFIG_FILE
    if not path.is_file():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CommentsConfigError(f"{CONFIG_FILE} is not valid TOML: {exc}") from exc
    table = data.get("comments", {})
    if not isinstance(table, dict):
        raise CommentsConfigError("[comments] must be a table")
    comments = cast(dict[str, object], table)
    for key in comments:
        if key not in COMMENTS_KEYS:
            raise CommentsConfigError(
                f"[comments]: unknown key `{key}` (supported: exempt_paths, include)"
            )
    return Settings(
        include=_string_list(comments.get("include", []), "comments.include"),
        exempt_paths=_string_list(comments.get("exempt_paths", []), "comments.exempt_paths"),
    )


def _docstrings(source: str) -> Iterator[Unit]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return
    nodes: list[ast.AST] = [tree]
    nodes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    )
    for node in nodes:
        body = cast(list[ast.stmt], getattr(node, "body", []))
        first = body[0] if body else None
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        for offset, line in enumerate(first.value.value.splitlines()):
            if line.strip():
                yield Unit(first.value.lineno + offset, line.strip(), "docstring")


def python_units(source: str, cell: int | None = None) -> list[Unit]:
    """Comments (tokenize) and docstrings (ast) of Python source, in line order."""
    units: list[Unit] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        for number, line in enumerate(source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                units.append(Unit(number, line.strip(), "comment", cell))
        return units
    units.extend(
        Unit(token.start[0], token.string.strip(), "comment", cell)
        for token in tokens
        if token.type == tokenize.COMMENT and not token.string.startswith("#!")
    )
    units.extend(Unit(unit.line, unit.text, unit.kind, cell) for unit in _docstrings(source))
    return sorted(units, key=lambda unit: unit.line)


def notebook_units(text: str, path: str) -> list[Unit]:
    try:
        loaded: object = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"unreadable notebook: {path}") from exc
    raw_cells = cast(dict[str, object], loaded).get("cells") if isinstance(loaded, dict) else None
    if not isinstance(raw_cells, list):
        raise ValueError(f"notebook without a `cells` list: {path}")
    units: list[Unit] = []
    for index, raw in enumerate(cast(list[object], raw_cells)):
        cell = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(str(part) for part in cast(list[object], source))
        if not isinstance(source, str):
            continue
        cell_type = cell.get("cell_type")
        if cell_type == "markdown":
            units.extend(
                Unit(number, line.strip(), "markdown", index)
                for number, line in enumerate(source.splitlines(), start=1)
                if line.strip()
            )
        elif cell_type == "code":
            code = "\n".join(
                "" if line.lstrip().startswith(("%", "!")) else line for line in source.splitlines()
            )
            units.extend(python_units(code + "\n", index))
    return units


def units_for(text: str, path: str) -> list[Unit]:
    if not text:
        return []
    if path.endswith(".ipynb"):
        return notebook_units(text, path)
    return python_units(text)


def _legit_date(text: str, match: re.Match[str]) -> bool:
    return bool(API_VERSION.search(text) or EXAMPLE_BEFORE.search(text[: match.start()]))


def violations_in(units: Sequence[Unit], path: str) -> list[Violation]:
    found: list[Violation] = []
    for unit in units:
        if ALLOW_MARKER in unit.text:
            continue
        for rule, pattern in RULES.items():
            if rule in COMMENT_ONLY and unit.kind != "comment":
                continue
            target = unit.text.lstrip("#-= ") if rule == "LABEL" else unit.text
            matches = list(pattern.finditer(target))
            if rule == "DATE":
                matches = [m for m in matches if not _legit_date(target, m)]
            if matches:
                found.append(Violation(path, unit, rule))
    return found


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def is_exempt(rel: str, exempt: Sequence[str]) -> bool:
    if any(part in EXCLUDED_DIRS for part in rel.split("/")[:-1]):
        return True
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in exempt)


def is_included(rel: str, include: Sequence[str]) -> bool:
    if not include:
        return True
    return any(fnmatch.fnmatch(rel, glob) or rel.startswith(glob) for glob in include)


def _walk(folder: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            if name.endswith(EXTENSIONS):
                yield Path(dirpath) / name


def candidate_files(
    paths: Sequence[str], root: Path, settings: Settings
) -> tuple[list[tuple[Path, str]], list[str]]:
    """(files to scan with their repo-relative path, missing explicit paths)."""
    selected: list[tuple[Path, str]] = []
    missing: list[str] = []
    if not paths:
        for path in _walk(root):
            rel = _relative(path, root)
            if is_included(rel, settings.include) and not is_exempt(rel, settings.exempt_paths):
                selected.append((path, rel))
        return selected, missing
    for raw in paths:
        candidate = Path(raw)
        candidate = candidate if candidate.is_absolute() else root / candidate
        if candidate.is_dir():
            files = list(_walk(candidate))
        elif candidate.is_file():
            files = [candidate] if candidate.name.endswith(EXTENSIONS) else []
        else:
            missing.append(raw)
            continue
        for path in files:
            rel = _relative(path, root)
            if not is_exempt(rel, settings.exempt_paths):
                selected.append((path, rel))
    return selected, missing


def report(found: Sequence[Violation]) -> None:
    print(f"COMMENT CHECK FAILED: {len(found)} violation(s)")
    rules_seen: list[str] = []
    for violation in found:
        print(f"  {violation.location()}: [{violation.rule}] {violation.unit.text}")
        if violation.rule not in rules_seen:
            rules_seen.append(violation.rule)
    print("--- fix hint ---")
    for rule in rules_seen:
        print(f"- {rule}: {REPAIR[rule]}")
    print(f"Proven false positive only: append `{ALLOW_MARKER}` to that line.")
    print(FOOTER)


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject comments and docstrings that narrate the history of the code."
    )
    parser.add_argument("paths", nargs="*", help="files or folders (default: [comments] scope)")
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    repo = find_root() if root is None else root
    try:
        settings = load_settings(repo)
    except CommentsConfigError as exc:
        print(f"HARNESS CONFIG INVALID: {exc}")
        return 2
    files, missing = candidate_files(list(args.paths), repo, settings)
    if missing:
        print(f"ERROR: path does not exist: {', '.join(missing)}")
        return 2
    found: list[Violation] = []
    for path, rel in files:
        try:
            text = path.read_text(encoding="utf-8-sig")
            found.extend(violations_in(units_for(text, rel), rel))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            print(f"ERROR: {rel}: {exc}")
            return 2
    if not found:
        print(f"COMMENT CHECK PASSED: {len(files)} file(s) checked")
        return 0
    report(found)
    return 1


if __name__ == "__main__":
    sys.exit(main())
