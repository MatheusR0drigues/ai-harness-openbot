"""Security fitness over every runtime script: banned APIs, justified nosec, stdlib-only imports.

Runtime scripts are the files hooks and gates execute: scripts/harness/*.py,
harness/packs/*/scripts/*.py, plugin/scripts/*.py and tools/*.py. Each check is parametrized
per file so a failure names the offending script.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_GLOBS = (
    "scripts/harness/*.py",
    "harness/packs/*/scripts/*.py",
    "plugin/scripts/*.py",
    "workflows/*.py",
)
HARNESS_DIR = Path("scripts") / "harness"
BANNED_CALLS = frozenset({"eval", "exec", "compile"})
BANNED_MODULES = frozenset({"pickle", "cPickle", "_pickle", "marshal", "shelve"})
NOSEC = re.compile(r"#\s*nosec\b(?P<rest>.*)")
BANDIT_CODE = re.compile(r"\bB\d{3}\b")
JUSTIFICATION = re.compile(r"^#\s*Bandit\s+(?P<codes>B\d{3}(?:[\s,/]+B\d{3})*):\s*\S")


def runtime_scripts(root: Path) -> list[Path]:
    found = {path for pattern in RUNTIME_GLOBS for path in root.glob(pattern) if path.is_file()}
    return sorted(found)


def local_modules(path: Path, root: Path) -> frozenset[str]:
    """Same-folder stems; tools reuse scripts/harness; pack scripts only `check_secrets` (D10)."""
    stems = {sibling.stem for sibling in path.parent.glob("*.py")}
    parent = path.parent.resolve()
    if parent == (root / "workflows").resolve():
        stems |= {module.stem for module in (root / HARNESS_DIR).glob("*.py")}
    elif parent in {d.resolve() for d in root.glob("harness/packs/*/scripts")}:
        stems |= {m.stem for m in (root / HARNESS_DIR).glob("check_secrets.py")}
    return frozenset(stems)


def dangerous_calls(source: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
            violations.append(f"{node.lineno}: {func.id}()")
        if (
            isinstance(func, ast.Attribute)
            and func.attr in BANNED_CALLS
            and isinstance(func.value, ast.Name)
            and func.value.id == "builtins"
        ):
            violations.append(f"{node.lineno}: builtins.{func.attr}()")
        for keyword in node.keywords:
            value = keyword.value
            is_false = isinstance(value, ast.Constant) and value.value is False
            if keyword.arg == "shell" and not is_false:
                violations.append(f"{node.lineno}: shell=True")
            if keyword.arg == "verify" and is_false:
                violations.append(f"{node.lineno}: verify=False")
    return violations


def banned_imports(source: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            violations.extend(
                f"{node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in BANNED_MODULES
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] in BANNED_MODULES
        ):
            violations.append(f"{node.lineno}: from {node.module} import ...")
    return violations


def unjustified_nosec(source: str) -> list[int]:
    """Every `# nosec BXXX` needs `# Bandit BXXX: <reason>` on the line above."""
    lines = source.splitlines()
    violations: list[int] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        match = NOSEC.search(token.string)
        if match is None:
            continue
        row = token.start[0]
        codes: set[str] = set(BANDIT_CODE.findall(match.group("rest")))
        above = lines[row - 2].strip() if row > 1 else ""
        justified = JUSTIFICATION.match(above)
        documented: set[str] = set()
        if justified is not None:
            documented.update(BANDIT_CODE.findall(justified.group("codes")))
        if not codes or not codes <= documented:
            violations.append(row)
    return violations


def non_stdlib_imports(source: str, local: frozenset[str]) -> list[str]:
    allowed = set(sys.stdlib_module_names) | local
    violations: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            violations.extend(
                f"{node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] not in allowed
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] not in allowed
        ):
            violations.append(f"{node.lineno}: from {node.module} import ...")
    return violations


RUNTIME = runtime_scripts(REPO_ROOT)
IDS = [path.relative_to(REPO_ROOT).as_posix() for path in RUNTIME]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_runtime_scripts_are_discovered() -> None:
    assert "scripts/harness/config.py" in IDS
    assert {
        "harness/packs/python/scripts/audit_deps.py",
        "harness/packs/python/scripts/check_test_determinism.py",
        "harness/packs/python/scripts/verificar_comentarios.py",
        "harness/packs/research-guard/scripts/research_guard.py",
        "harness/packs/data-engineering/scripts/check_spark_antipatterns.py",
        "harness/packs/bi-pbip/scripts/check_pbip_sanity.py",
    } <= set(IDS)


@pytest.mark.parametrize("path", RUNTIME, ids=IDS)
def test_no_eval_exec_compile_shell_true_or_verify_false(path: Path) -> None:
    violations = dangerous_calls(read(path))

    assert not violations, (
        "eval/exec/compile, shell=True and verify=False are banned in runtime scripts; parse "
        f"data explicitly, pass argv lists to subprocess and keep TLS verification: {violations}"
    )


@pytest.mark.parametrize("path", RUNTIME, ids=IDS)
def test_no_pickle_marshal_or_shelve(path: Path) -> None:
    violations = banned_imports(read(path))

    assert not violations, f"unsafe deserialization modules are banned: {violations}"


@pytest.mark.parametrize("path", RUNTIME, ids=IDS)
def test_every_nosec_is_justified(path: Path) -> None:
    violations = unjustified_nosec(read(path))

    assert not violations, (
        "each `# nosec BXXX` needs a `# Bandit BXXX: <reason>` comment on the line above "
        f"(lines {violations})"
    )


@pytest.mark.parametrize("path", RUNTIME, ids=IDS)
def test_runtime_imports_only_stdlib_or_sibling_modules(path: Path) -> None:
    violations = non_stdlib_imports(read(path), local_modules(path, REPO_ROOT))

    assert not violations, (
        "runtime scripts are stdlib-only; import only the standard library or modules that "
        f"ship in the same folder: {violations}"
    )


def test_dangerous_call_detector_catches_each_pattern() -> None:
    source = (
        "import builtins\n"
        "eval(x)\n"
        "exec(x)\n"
        "compile(src, 'f', 'exec')\n"
        "builtins.eval(x)\n"
        "subprocess.run(c, shell=True)\n"
        "subprocess.run(c, shell=flag)\n"
        "subprocess.run(c, shell=False)\n"
        "client.get(url, verify=False)\n"
        "client.get(url, verify=True)\n"
        "re.compile(pattern)\n"
    )

    assert dangerous_calls(source) == [
        "2: eval()",
        "3: exec()",
        "4: compile()",
        "5: builtins.eval()",
        "6: shell=True",
        "7: shell=True",
        "9: verify=False",
    ]


def test_banned_import_detector() -> None:
    source = "import pickle\nimport json\nfrom marshal import loads\nimport shelve as s\n"

    assert banned_imports(source) == [
        "1: import pickle",
        "3: from marshal import ...",
        "4: import shelve",
    ]


def test_nosec_detector_requires_matching_reason_above() -> None:
    source = (
        "# Bandit B404: fixed argv lists only\n"
        "import subprocess  # nosec B404\n"
        "import pickle  # nosec B403\n"
        "import os  # nosec\n"
        "# Bandit B603, B607: argv built from constants\n"
        "run(['uv'])  # nosec B603 B607\n"
        "# Bandit B603: argv built from constants\n"
        "run(['uv'])  # nosec B603 B607\n"
        'hint = "add # nosec B603"\n'
    )

    assert unjustified_nosec(source) == [3, 4, 8]


def test_stdlib_detector_accepts_stdlib_and_local_modules() -> None:
    source = (
        "from __future__ import annotations\n"
        "import json\n"
        "import xml.etree.ElementTree\n"
        "from collections.abc import Sequence\n"
        "import config\n"
        "import requests\n"
        "from yaml import safe_load\n"
        "from . import sibling\n"
    )

    assert non_stdlib_imports(source, frozenset({"config"})) == [
        "6: import requests",
        "7: from yaml import ...",
    ]


def test_local_modules_for_tools_include_core_harness(tmp_path: Path) -> None:
    (tmp_path / "workflows").mkdir()
    (tmp_path / "scripts" / "harness").mkdir(parents=True)
    (tmp_path / "workflows" / "dump.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "harness" / "payload.py").write_text("", encoding="utf-8")
    pack = tmp_path / "harness" / "packs" / "demo" / "scripts"
    pack.mkdir(parents=True)
    (pack / "tool.py").write_text("", encoding="utf-8")

    assert local_modules(tmp_path / "workflows" / "dump.py", tmp_path) == {"dump", "payload"}
    assert local_modules(pack / "tool.py", tmp_path) == {"tool"}


def test_local_modules_for_packs_reuse_only_check_secrets(tmp_path: Path) -> None:
    harness = tmp_path / "scripts" / "harness"
    harness.mkdir(parents=True)
    (harness / "payload.py").write_text("", encoding="utf-8")
    (harness / "check_secrets.py").write_text("", encoding="utf-8")
    pack = tmp_path / "harness" / "packs" / "demo" / "scripts"
    pack.mkdir(parents=True)
    (pack / "tool.py").write_text("", encoding="utf-8")

    assert local_modules(pack / "tool.py", tmp_path) == {"tool", "check_secrets"}
