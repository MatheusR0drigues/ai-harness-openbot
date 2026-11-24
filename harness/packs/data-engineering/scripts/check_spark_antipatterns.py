"""Verifica antipadroes PySpark em arquivos Python por analise AST."""

from __future__ import annotations

import argparse
import ast
import importlib
import sys
from collections.abc import Iterable
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[4] / "scripts" / "harness"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))

RUNTIME_MISSING = "harness runtime not found (scripts/harness/check_secrets.py)"
ALLOW_MARKER = "spark-antipatterns: allow"
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
SPARK_ROOT_NAMES = frozenset({"spark"})
SPARK_CHAIN_METHODS = frozenset(
    {
        "table",
        "sql",
        "read",
        "readStream",
        "createDataFrame",
        "select",
        "selectExpr",
        "filter",
        "where",
        "groupBy",
        "groupby",
        "agg",
        "join",
        "withColumn",
        "withColumnRenamed",
        "dropDuplicates",
        "repartition",
        "coalesce",
        "orderBy",
        "sort",
        "distinct",
        "union",
        "unionByName",
        "toDF",
    }
)


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


def iter_python_files(root: Path, paths: Iterable[Path] | None = None) -> list[Path]:
    import check_secrets

    root_resolved = root.resolve()
    if paths:
        collected: list[Path] = []
        for item in paths:
            resolved = (item if item.is_absolute() else (root_resolved / item)).resolve()
            try:
                resolved.relative_to(root_resolved)
            except ValueError:
                continue
            if resolved.is_file() and resolved.suffix == ".py":
                collected.append(resolved)
            elif resolved.is_dir():
                for child in sorted(resolved.rglob("*.py")):
                    if not _is_ignored(child, root_resolved):
                        collected.append(child)
        return collected
    return [
        p
        for p in sorted(check_secrets.expand_targets([], root_resolved))
        if p.suffix == ".py" and not _is_ignored(p, root_resolved)
    ]


def _is_binary(path: Path) -> bool:
    import check_secrets

    with path.open("rb") as handle:
        head = handle.read(check_secrets.BINARY_SNIFF_BYTES)
    return check_secrets.is_binary(path, head)


def _extract_chain(expr: ast.expr) -> tuple[str | None, list[str]]:
    attrs: list[str] = []
    cur: ast.expr = expr
    while True:
        if isinstance(cur, ast.Call):
            cur = cur.func
            continue
        if isinstance(cur, ast.Attribute):
            attrs.append(cur.attr)
            cur = cur.value
            continue
        if isinstance(cur, ast.Subscript):
            cur = cur.value
            continue
        if isinstance(cur, ast.Name):
            attrs.reverse()
            return cur.id, attrs
        break
    attrs.reverse()
    return None, attrs


def _looks_like_spark_chain(root_name: str | None, attrs: list[str]) -> bool:
    if root_name is not None:
        lowered = root_name.lower()
        if (
            root_name in SPARK_ROOT_NAMES
            or lowered == "df"
            or lowered.endswith("_df")
            or lowered == "dataframe"
        ):
            return True
    return any(attr in SPARK_CHAIN_METHODS for attr in attrs)


def _is_udf_target(expr: ast.expr) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "udf"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "udf"
    return False


def _line_allowed(lines: list[str], start_line: int, end_line: int | None) -> bool:
    last = end_line if end_line is not None else start_line
    for idx in range(max(1, start_line) - 1, min(len(lines), last)):
        if ALLOW_MARKER in lines[idx]:
            return True
    return False


def check_source(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        line = exc.lineno or 1
        return [(line, f"SyntaxError ao analisar {filename}: {exc.msg}")]

    lines = source.splitlines()
    findings: list[tuple[int, str]] = []
    seen_udf_lines: set[int] = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if _is_udf_target(target) and not _line_allowed(lines, dec.lineno, dec.end_lineno):
                    seen_udf_lines.add(dec.lineno)
                    findings.append(
                        (
                            dec.lineno,
                            "Evite @udf linha-a-linha; use funcoes nativas Spark SQL"
                            " ou @pandas_udf com Arrow.",
                        )
                    )

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                method = node.func.attr
                root_name, attrs = _extract_chain(node.func.value)
                has_limit = "limit" in attrs

                if method == "toPandas" and not has_limit:
                    if not _line_allowed(lines, node.lineno, node.end_lineno):
                        findings.append(
                            (
                                node.lineno,
                                "Evite .toPandas() sem .limit(N) antes da coleta no driver.",
                            )
                        )
                elif (
                    method == "collect"
                    and not has_limit
                    and _looks_like_spark_chain(root_name, attrs)
                    and not _line_allowed(lines, node.lineno, node.end_lineno)
                ):
                    findings.append(
                        (
                            node.lineno,
                            "Evite .collect() em DataFrame Spark sem .limit(N)"
                            " antes da coleta no driver.",
                        )
                    )
                elif (
                    method == "register"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "udf"
                    and not _line_allowed(lines, node.lineno, node.end_lineno)
                ):
                    findings.append(
                        (
                            node.lineno,
                            "Evite spark.udf.register(); prefira expressoes nativas"
                            " SQL ou @pandas_udf.",
                        )
                    )

            if (
                node.lineno not in seen_udf_lines
                and _is_udf_target(node.func)
                and not _line_allowed(lines, node.lineno, node.end_lineno)
            ):
                findings.append(
                    (
                        node.lineno,
                        "Evite udf() Python pura; use funcoes nativas de"
                        " pyspark.sql.functions ou @pandas_udf.",
                    )
                )

    findings.sort(key=lambda item: (item[0], item[1]))
    return findings


def check_paths(root: Path, paths: Iterable[Path] | None = None) -> list[str]:
    messages: list[str] = []
    for path in iter_python_files(root, paths):
        if _is_binary(path):
            continue
        text = path.read_text(encoding="utf-8-sig")
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        for line_no, reason in check_source(text, filename=rel):
            messages.append(f"{rel}:{line_no}: {reason}")
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica antipadroes PySpark no repositorio.")
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
            print(f"[spark-antipatterns] {item}", file=sys.stderr)
        return 1
    print("SPARK ANTIPATTERNS CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
