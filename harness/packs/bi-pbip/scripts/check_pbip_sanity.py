"""Valida indentacao TMDL e vazamento de PII em filtros JSON de projetos PBIP/PBIR."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import cast

HARNESS_DIR = Path(__file__).resolve().parents[4] / "scripts" / "harness"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

RUNTIME_MISSING = "harness runtime not found (scripts/harness/check_secrets.py)"
ALLOW_MARKER = "pbip-sanity: allow"
IGNORE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
        "raw",
        "docs",
        "tests",
    }
)
REPORT_JSON_NAMES = frozenset(
    {"page.json", "report.json", "visual.json", "bookmarks.json", "version.json", "pages.json"}
)
PBIR_SCHEMA_TOKENS: dict[str, str] = {
    "visual.json": "visualContainer",
    "page.json": "page",
    "report.json": "report",
    "version.json": "version",
    "pages.json": "pagesMetadata",
    "bookmarks.json": "bookmarksMetadata",
    "definition.pbir": "definitionProperties",
}
TMDL_MEASURE_PROP_PREFIXES = (
    "formatString:",
    "displayFolder:",
    "description:",
    "lineageTag:",
    "isHidden",
    "changedProperty",
    "annotation ",
    "detailRowsDefinition",
    "kpi",
)
DAX_COMPLEX_MIN_LINES = 6
_DAX_VAR_RE = re.compile(r"\bVAR\b", re.IGNORECASE)
_DAX_RETURN_RE = re.compile(r"\bRETURN\b", re.IGNORECASE)
_DAX_IFERROR_RE = re.compile(r"\bIFERROR\s*\(", re.IGNORECASE)
_DAX_STRING_OR_COMMENT_RE = re.compile(
    r"//[^\n]*|--[^\n]*|/\*.*?\*/|\"(?:\"\"|[^\"])*\"|'(?:''|[^'])*'",
    re.DOTALL,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CPF_FORMATTED_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_DIGITS_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
ID_KEYS = frozenset({"name", "queryRef", "nativeQueryRef"})


def _runtime_found() -> bool:
    """The candidate listing and the binary rule come from `scripts/harness/check_secrets.py`."""
    try:
        importlib.import_module("check_secrets")
    except ImportError:
        return False
    return True


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "harness.toml").is_file() or (candidate / ".git").exists():
            return candidate
    return current


def _is_ignored(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        rel_parts = path.parts
    return any(part in IGNORE_DIRS for part in rel_parts)


def _is_report_json(path: Path) -> bool:
    return (
        path.name in REPORT_JSON_NAMES
        or path.name == "definition.pbir"
        or path.name.endswith(".bookmark.json")
    )


def iter_target_files(root: Path, paths: Iterable[Path] | None = None) -> list[Path]:
    import check_secrets

    root_resolved = root.resolve()
    candidates: list[Path] = []
    if paths:
        for item in paths:
            resolved = (item if item.is_absolute() else (root_resolved / item)).resolve()
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                continue
            if resolved.is_file():
                if resolved.suffix == ".tmdl" or _is_report_json(resolved):
                    candidates.append(resolved)
            elif resolved.is_dir():
                for child in sorted(resolved.rglob("*")):
                    if (
                        child.is_file()
                        and not _is_ignored(child, root_resolved)
                        and (child.suffix == ".tmdl" or _is_report_json(child))
                    ):
                        candidates.append(child)
        return candidates

    for child in sorted(check_secrets.expand_targets([], root_resolved)):
        if (
            child.is_file()
            and not _is_ignored(child, root_resolved)
            and (child.suffix == ".tmdl" or _is_report_json(child))
        ):
            candidates.append(child)
    return candidates


def _is_binary(path: Path) -> bool:
    import check_secrets

    with path.open("rb") as handle:
        head = handle.read(check_secrets.BINARY_SNIFF_BYTES)
    return check_secrets.is_binary(path, head)


def _strip_dax_literals_and_comments(text: str) -> str:
    """Replace DAX string literals, quoted identifiers, and comments with spaces."""

    def _blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return _DAX_STRING_OR_COMMENT_RE.sub(_blank, text)


def _leading_tabs(line: str) -> int:
    count = 0
    for ch in line:
        if ch == "\t":
            count += 1
        else:
            break
    return count


def _check_dax_measures(lines: list[str]) -> list[tuple[int, str]]:
    """Static DAX/BPA lint over `measure` blocks in a TMDL file."""
    violations: list[tuple[int, str]] = []
    idx = 0
    total = len(lines)
    while idx < total:
        raw = lines[idx]
        stripped = raw.lstrip("\t")
        if not raw.startswith(" ") and stripped.startswith("measure ") and "=" in stripped:
            decl_tabs = _leading_tabs(raw)
            decl_line_no = idx + 1
            measure_allowed = ALLOW_MARKER in raw
            _, _, after_eq = stripped.partition("=")
            expr_lines: list[tuple[int, str]] = []
            if after_eq.strip() and not after_eq.strip().startswith("```"):
                expr_lines.append((decl_line_no, after_eq))
            idx += 1
            while idx < total:
                cur = lines[idx]
                cur_stripped = cur.lstrip("\t ")
                if not cur_stripped:
                    idx += 1
                    continue
                cur_tabs = _leading_tabs(cur)
                if cur_tabs <= decl_tabs:
                    break
                if cur_tabs == decl_tabs + 1 and cur_stripped.startswith(
                    TMDL_MEASURE_PROP_PREFIXES
                ):
                    break
                if cur_stripped != "```":
                    expr_lines.append((idx + 1, cur))
                idx += 1

            if measure_allowed or not expr_lines:
                continue

            full_raw_expr = "\n".join(text for _, text in expr_lines)
            sanitized_lines = _strip_dax_literals_and_comments(full_raw_expr).splitlines()
            non_empty_code = 0
            for (line_no, raw_line), clean_line in zip(expr_lines, sanitized_lines, strict=True):
                if ALLOW_MARKER in raw_line:
                    continue
                if clean_line.strip():
                    non_empty_code += 1
                if "/" in clean_line:
                    violations.append(
                        (
                            line_no,
                            "DAX BPA: evite divisao `/` desprotegida; use DIVIDE(num, den, 0).",
                        )
                    )
                if _DAX_IFERROR_RE.search(clean_line):
                    violations.append(
                        (
                            line_no,
                            "DAX BPA: evite IFERROR(); prefira DIVIDE() ou tratamento explicito.",
                        )
                    )
            full_clean = "\n".join(sanitized_lines)
            if non_empty_code >= DAX_COMPLEX_MIN_LINES and not (
                _DAX_VAR_RE.search(full_clean) and _DAX_RETURN_RE.search(full_clean)
            ):
                violations.append(
                    (
                        decl_line_no,
                        "DAX BPA: medida complexa sem VAR/RETURN; "
                        "organize etapas com VAR e RETURN.",
                    )
                )
            continue
        idx += 1
    return violations


def check_tmdl_text(text: str) -> list[tuple[int, str]]:
    lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for line_no, line in enumerate(lines, start=1):
        if line.startswith(" ") and line.strip() and ALLOW_MARKER not in line:
            violations.append(
                (line_no, "Indentacao TMDL comecando com espaco; o Desktop grava com tab.")
            )
    violations.extend(_check_dax_measures(lines))
    return sorted(violations, key=lambda item: item[0])


def _dict_has_allow_marker(mapping: dict[object, object]) -> bool:
    return any(isinstance(val, str) and ALLOW_MARKER in val for val in mapping.values())


def _detect_pii_kind(text: str) -> str | None:
    if "@" in text and EMAIL_RE.search(text):
        return "e-mail"
    if CPF_FORMATTED_RE.search(text) or CPF_DIGITS_RE.search(text):
        return "CPF"
    return None


def _scan_json_node(
    node: object,
    *,
    in_filter: bool,
    allowed: bool,
    path_hint: str,
    findings: list[str],
    in_filter_block: bool = False,
) -> None:
    if isinstance(node, dict):
        mapping = cast("dict[object, object]", node)
        node_has_marker = in_filter and _dict_has_allow_marker(mapping)
        node_is_filter_config = path_hint == "filterConfig" or path_hint.endswith(".filterConfig")
        for key, value in mapping.items():
            key_str = str(key)
            if in_filter_block and key_str in ID_KEYS and isinstance(value, str):
                # Identifiers generated by Power BI Desktop are not literals (D7).
                continue
            key_is_filter = "filter" in key_str.lower()
            child_in_filter = in_filter or key_is_filter
            child_allowed = False if key_is_filter else (allowed or node_has_marker)
            child_in_filter_block = in_filter_block or (
                node_is_filter_config and key_str == "filters" and isinstance(value, list)
            )
            next_hint = f"{path_hint}.{key_str}" if path_hint else key_str
            _scan_json_node(
                cast("object", value),
                in_filter=child_in_filter,
                allowed=child_allowed,
                path_hint=next_hint,
                findings=findings,
                in_filter_block=child_in_filter_block,
            )
    elif isinstance(node, list):
        items = cast("list[object]", node)
        for idx, item in enumerate(items):
            _scan_json_node(
                item,
                in_filter=in_filter,
                allowed=allowed,
                path_hint=f"{path_hint}[{idx}]",
                findings=findings,
                in_filter_block=in_filter_block,
            )
    elif isinstance(node, str) and in_filter and not allowed and ALLOW_MARKER not in node:
        pii_kind = _detect_pii_kind(node)
        if pii_kind is not None:
            loc = path_hint or "filter"
            findings.append(
                f"Possivel literal de PII ({pii_kind}) em bloco de filtro JSON ({loc})."
            )


def _check_pbir_structure(data: object, rel_path: str) -> list[str]:
    if not isinstance(data, dict):
        return ["Estrutura PBIR invalida: a raiz do JSON deve ser um objeto."]
    mapping = cast("dict[object, object]", data)
    if _dict_has_allow_marker(mapping):
        return []
    findings: list[str] = []
    name = Path(rel_path).name if rel_path else ""
    requires_schema = name == "definition.pbir" or (
        bool(rel_path) and "definition/" in rel_path.replace("\\", "/")
    )
    schema_val = mapping.get("$schema")
    if schema_val is None:
        if requires_schema:
            findings.append("Estrutura PBIR: campo `$schema` ausente no artefato de definicao.")
    elif not isinstance(schema_val, str) or not schema_val.startswith("https://"):
        findings.append("Estrutura PBIR: `$schema` deve ser uma URL `https://` valida.")
    else:
        expected_token = PBIR_SCHEMA_TOKENS.get(name)
        if expected_token is not None and expected_token not in schema_val:
            findings.append(
                f"Estrutura PBIR: `$schema` inconsistente para `{name}` "
                f"(esperado `{expected_token}`)."
            )
    return findings


def check_report_json_text(text: str, *, rel_path: str = "") -> list[str]:
    try:
        data = cast("object", json.loads(text))
    except json.JSONDecodeError as exc:
        return [f"JSON invalido na linha {exc.lineno}: {exc.msg}"]

    findings: list[str] = _check_pbir_structure(data, rel_path)
    _scan_json_node(data, in_filter=False, allowed=False, path_hint="", findings=findings)
    return findings


def check_paths(root: Path, paths: Iterable[Path] | None = None) -> list[str]:
    messages: list[str] = []
    for path in iter_target_files(root, paths):
        if _is_binary(path):
            continue
        text = path.read_text(encoding="utf-8-sig")
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        if path.suffix == ".tmdl":
            for line_no, reason in check_tmdl_text(text):
                messages.append(f"{rel}:{line_no}: {reason}")
        elif _is_report_json(path):
            for reason in check_report_json_text(text, rel_path=rel):
                messages.append(f"{rel}: {reason}")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida indentacao TMDL e ausencia de PII em filtros JSON PBIP/PBIR."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="Arquivos ou pastas alvo.")
    parser.add_argument("--root", type=Path, default=None, help="Diretorio raiz do projeto.")
    args = parser.parse_args(argv)
    if not _runtime_found():
        print(RUNTIME_MISSING, file=sys.stderr)
        return 1

    root = find_root(args.root)
    violations = check_paths(root, args.paths or None)
    if violations:
        for item in violations:
            print(f"[pbip-sanity] {item}", file=sys.stderr)
        return 1
    print("PBIP SANITY CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
