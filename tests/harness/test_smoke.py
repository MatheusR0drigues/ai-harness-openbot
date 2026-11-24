"""Repository-level smoke checks for the Stage 3 consolidation (Requisitos 1, 2 and 7).

Unit suites cover each module; these tests pin the properties of the repository as a whole:
every runtime module imports, the structure gate passes on the real tree, the plugin ships no
MCP/hook/other-IDE files nor duplicated scripts, no distribution artifact survived, and runtime
dependencies stay empty.
"""

import ast
import importlib
import json
import re
import tomllib
from pathlib import Path
from typing import cast

import check_structure
import config
import pytest

ROOT = config.REPO_ROOT
RUNTIME = ROOT / "scripts" / "harness"
PLUGIN = ROOT / "plugin"
RUNTIME_MODULES = sorted(path.stem for path in RUNTIME.glob("*.py"))
SHARED_SCRIPTS = ("check_secrets.py", "validate_spec.py")
PLUGIN_HELPER_SCRIPTS = ("pr_via_rest_api.py",)
REMOVED_MODULES = (
    "sync_adapters.py",
    "distribute.py",
    "distribution.py",
    "check_lock.py",
    "blocks.py",
)
TESTS = ROOT / "tests" / "harness"
SKIP_ATTRS = frozenset({"skip", "skipif", "xfail", "importorskip"})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", RUNTIME_MODULES)
def test_every_runtime_module_imports(name: str) -> None:
    assert importlib.import_module(name).__name__ == name


def test_the_repository_passes_its_own_structure_gate() -> None:
    assert check_structure.check_all(ROOT) == []


@pytest.mark.parametrize("name", SHARED_SCRIPTS)
def test_plugin_scripts_are_byte_identical_to_the_runtime(name: str) -> None:
    assert (PLUGIN / "scripts" / name).read_bytes() == (RUNTIME / name).read_bytes()


def test_plugin_ships_only_the_shared_scripts() -> None:
    shipped = sorted(p.name for p in (PLUGIN / "scripts").iterdir() if p.is_file())
    in_skills = sorted(p.relative_to(PLUGIN).as_posix() for p in PLUGIN.glob("skills/**/*.py"))

    assert shipped == sorted((*SHARED_SCRIPTS, *PLUGIN_HELPER_SCRIPTS))
    assert in_skills == []


def test_plugin_has_no_mcp_hooks_or_other_ide_files() -> None:
    files = [p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*") if p.is_file()]

    assert not [f for f in files if "mcp" in Path(f).name.lower()]
    assert "hooks.json" not in {Path(f).name for f in files}
    assert not [f for f in files if any(part in f for part in (".claude", ".kiro", ".codex"))]


def test_plugin_manifest_declares_the_ai_harness_plugin() -> None:
    manifest = cast(dict[str, object], json.loads(read(PLUGIN / "plugin.json")))

    assert manifest["name"] == "ai-harness"
    assert set(manifest) == {"name", "displayName", "version", "description", "suggestedPrompts"}


def test_no_distribution_artifact_survived_the_consolidation() -> None:
    assert not (ROOT / ".github" / "workflows" / "propagate.yml").exists()
    assert not (ROOT / ".harness").exists()
    assert not (RUNTIME / "bin").exists()
    assert [name for name in REMOVED_MODULES if (RUNTIME / name).exists()] == []


def test_no_runtime_code_imports_sync_adapters() -> None:
    sources = [*RUNTIME.glob("*.py"), *ROOT.glob("harness/packs/*/scripts/*.py")]
    sources += [*(PLUGIN / "scripts").glob("*.py")]

    offenders = [p.name for p in sources if re.search(r"\bsync_adapters\b", read(p))]

    assert offenders == []


def test_runtime_dependencies_stay_empty_and_dev_tools_are_pinned() -> None:
    data = tomllib.loads(read(ROOT / "pyproject.toml"))
    project = cast(dict[str, object], data["project"])
    groups = cast(dict[str, list[str]], data["dependency-groups"])
    pyright = cast(dict[str, dict[str, object]], data["tool"])["pyright"]

    assert project["dependencies"] == []
    assert project["requires-python"] == ">=3.11"
    assert set(groups) == {"dev"}
    assert sorted(dep.split("==")[0] for dep in groups["dev"]) == ["pyright", "pytest", "ruff"]
    assert all(re.fullmatch(r"[a-z]+==\d+(?:\.\d+)+", dep) for dep in groups["dev"])
    assert pyright["typeCheckingMode"] == "strict"


def _skip_markers(path: Path) -> list[str]:
    """Every way the suite could skip or expect a failure, by line, aliases included."""
    tree = ast.parse(read(path), filename=str(path))
    pytest_names = {"pytest"}
    mark_names: set[str] = set()
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pytest_names |= {a.asname or a.name for a in node.names if a.name == "pytest"}
        elif isinstance(node, ast.ImportFrom) and node.module in ("pytest", "_pytest.mark"):
            for alias in node.names:
                if alias.name in SKIP_ATTRS:
                    found.append(f"{path.name}:{node.lineno}: from pytest import {alias.name}")
                elif alias.name == "mark":
                    mark_names.add(alias.asname or "mark")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in SKIP_ATTRS:
            continue
        owner = node.value
        on_pytest = isinstance(owner, ast.Name) and owner.id in pytest_names
        on_mark = (isinstance(owner, ast.Name) and owner.id in mark_names) or (
            isinstance(owner, ast.Attribute)
            and owner.attr == "mark"
            and isinstance(owner.value, ast.Name)
            and owner.value.id in pytest_names
        )
        if on_pytest or on_mark:
            found.append(f"{path.name}:{node.lineno}: {node.attr}")
    return found


def test_the_suite_never_skips_or_expects_failures() -> None:
    """Requisito 7.3: no `skip`/`xfail` anywhere in the harness suite."""
    offenders = [hit for path in sorted(TESTS.glob("*.py")) for hit in _skip_markers(path)]

    assert offenders == []


@pytest.mark.parametrize(
    ("source", "count"),
    [
        ("import pytest\n@pytest.mark.SKIP\ndef test_a(): pass\n", 1),
        ("import pytest\n@pytest.mark.XFAIL\ndef test_b(): pytest.SKIP('x')\n", 2),
        ("import pytest as pt\n@pt.mark.SKIPIF(True, reason='x')\ndef test_c(): pass\n", 1),
        ("from pytest import mark\n@mark.SKIP\ndef test_d(): pass\n", 1),
        ("from pytest import mark as m\n@m.XFAIL\ndef test_e(): pass\n", 1),
        ("from pytest import SKIP\ndef test_f(): SKIP('x')\n", 1),
        ("import pytest\nyaml = pytest.IMPORTORSKIP('yaml')\n", 1),
        ("import pytest\n@pytest.mark.parametrize('x', [1])\ndef test_g(x): pass\n", 0),
    ],
)
def test_skip_detector_finds_every_marker_shape(tmp_path: Path, source: str, count: int) -> None:
    """Upper-case placeholders keep this file free of real markers; they are lowered here."""
    sample = tmp_path / "test_sample.py"
    for name in ("IMPORTORSKIP", "SKIPIF", "SKIP", "XFAIL"):
        source = source.replace(name, name.lower())
    sample.write_text(source, encoding="utf-8")

    assert len(_skip_markers(sample)) == count
