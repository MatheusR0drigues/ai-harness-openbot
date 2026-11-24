"""Opt-in stack packs (harness/packs/<name>/) load, merge and ship clean PT-BR rules."""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

import check_structure
import config
import pytest
from config import Pack

PACKS = ("python", "node", "web-ui", "research-guard", "data-engineering", "bi-pbip")
PACKS_DIR = config.REPO_ROOT / "harness" / "packs"
MAX_RULE_BYTES = 24_000
TRIGGERS = frozenset({"always_on", "glob", "model_decision", "manual"})
FRONTMATTER_KEYS = frozenset({"trigger", "globs", "description"})
YAML_INDICATORS = tuple("-?:,[]{}#&*!|>'\"%@`")
EXPECTED_GATES = {
    "python": (
        "py-format",
        "py-lint",
        "py-types",
        "py-tests",
        "py-audit",
        "py-determinism",
        "py-comments",
    ),
    "node": ("node-lint", "node-types", "node-tests", "node-audit"),
    "web-ui": (),
    "research-guard": (),
    "data-engineering": ("spark-antipatterns",),
    "bi-pbip": ("pbip-sanity",),
}
FAST_GATES = {
    "py-format",
    "py-lint",
    "py-determinism",
    "py-comments",
    "node-lint",
    "node-types",
    "spark-antipatterns",
    "pbip-sanity",
}
PT_PT_WORDS = re.compile(
    r"\b(?:ficheiros?|ecrãs?|utilizador(?:es|as?)?|telemóve(?:l|is)|registos?|equipas?"
    r"|partilh\w*|aceder|acedid\w*|guardar|rato|sítios?\s+web)\b",
    re.IGNORECASE,
)


def frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the flat `key: value` frontmatter Antigravity reads; return (fields, problems)."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, ["file must start with a `---` frontmatter line"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, ["frontmatter has no closing `---`"]
    fields: dict[str, str] = {}
    problems: list[str] = []
    for line in lines[1:end]:
        if not line.strip():
            continue
        match = re.fullmatch(r"([A-Za-z_][\w-]*):(?: (.*))?", line)
        if match is None:
            problems.append(f"not a flat `key: value` line: {line!r}")
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        if key not in FRONTMATTER_KEYS:
            problems.append(f"unknown key `{key}`")
        if key in fields:
            problems.append(f"duplicate key `{key}`")
        if value[:1] in ('"', "'"):
            quote = value[0]
            inner = value[1:-1]
            escaped = inner.replace('\\"', "") if quote == '"' else inner.replace("''", "")
            if len(value) < 2 or value[-1] != quote or quote in escaped:
                problems.append(f"`{key}` has unbalanced quotes")
            value = inner
        elif ": " in value or " #" in value or value.startswith(YAML_INDICATORS):
            problems.append(f"`{key}` must be quoted: {value!r}")
        if not value:
            problems.append(f"`{key}` is empty")
        fields[key] = value
    trigger = fields.get("trigger", "")
    if trigger not in TRIGGERS:
        problems.append(f"trigger must be one of {sorted(TRIGGERS)}, got `{trigger}`")
    if trigger == "glob" and not fields.get("globs"):
        problems.append("trigger `glob` needs `globs`")
    if trigger == "model_decision" and not fields.get("description"):
        problems.append("trigger `model_decision` needs `description`")
    if not "\n".join(lines[end + 1 :]).strip():
        problems.append("rule body is empty")
    return fields, problems


def load(name: str) -> Pack:
    return config.load_pack(config.REPO_ROOT, name)


def pack_files() -> list[Path]:
    return sorted(
        path for path in PACKS_DIR.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    )


def rule_paths() -> list[Path]:
    return [load(name).root / rule for name in PACKS for rule in load(name).rules]


def test_every_supported_pack_ships() -> None:
    shipped = {path.name for path in PACKS_DIR.iterdir() if path.is_dir()}

    assert shipped == set(PACKS) == config.SUPPORTED_PACKS


@pytest.mark.parametrize("name", PACKS)
def test_pack_loads_with_stack_gates_only(name: str) -> None:
    pack = load(name)

    assert pack.name == name
    assert pack.description.strip()
    assert pack.rules, "every pack ships at least one rule"
    assert tuple(gate.name for gate in pack.gates) == EXPECTED_GATES[name]
    assert all(gate.group == "stack" for gate in pack.gates)
    assert {gate.name for gate in pack.gates if gate.fast} == FAST_GATES & {
        gate.name for gate in pack.gates
    }
    assert all(gate.hint.strip() for gate in pack.gates)


@pytest.mark.parametrize("name", PACKS)
def test_pack_rules_folder_matches_declared_rules(name: str) -> None:
    pack = load(name)
    shipped = {f"rules/{path.name}" for path in (pack.root / "rules").glob("*.md")}

    assert shipped == set(pack.rules)


@pytest.mark.parametrize("name", ["python", "node", "data-engineering", "bi-pbip"])
def test_python_gate_scripts_exist(name: str) -> None:
    for gate in load(name).gates:
        if gate.command[0] == "python":
            assert (config.REPO_ROOT / gate.command[1]).is_file(), gate.name


def test_python_pack_gates_require_matching_files() -> None:
    gates = {gate.name: gate for gate in load("python").gates}

    assert gates["py-audit"].requires_glob == "uv.lock"
    assert all(gate.requires_glob for gate in gates.values())
    assert all(gate.requires_glob == "package.json" for gate in load("node").gates)


def test_research_guard_registers_antigravity_pre_tool_hook() -> None:
    pack = load("research-guard")

    assert pack.hooks == ()
    assert pack.rules == ("rules/research-policy.md",)


@pytest.mark.parametrize("path", rule_paths(), ids=lambda path: path.name)
def test_rule_has_valid_frontmatter_and_size(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    _, problems = frontmatter(text)

    assert not problems, problems
    assert len(path.read_bytes()) < MAX_RULE_BYTES
    assert "\ufeff" not in text


@pytest.mark.parametrize("path", rule_paths(), ids=lambda path: path.name)
def test_rule_uses_brazilian_portuguese(path: Path) -> None:
    found = PT_PT_WORDS.findall(path.read_text(encoding="utf-8"))

    assert not found, f"PT-PT forms found (use PT-BR): {found}"


def test_web_ui_rule_states_wcag_contrast_ratios() -> None:
    fields, _ = frontmatter((PACKS_DIR / "web-ui" / "rules" / "ui_ux_design.md").read_text("utf-8"))
    text = (PACKS_DIR / "web-ui" / "rules" / "ui_ux_design.md").read_text(encoding="utf-8")

    assert fields["trigger"] == "glob"
    assert fields["globs"] == "**/*.html, **/*.css, **/*.tsx, **/*.jsx, **/*.vue"
    assert "WCAG 2.2" in text
    assert "4.5:1" in text
    assert "3:1" in text


def test_python_rule_targets_python_files() -> None:
    fields, _ = frontmatter((PACKS_DIR / "python" / "rules" / "python.md").read_text("utf-8"))

    assert (fields["trigger"], fields["globs"]) == ("glob", "**/*.py")


@pytest.mark.parametrize(
    "path", pack_files(), ids=lambda path: path.relative_to(PACKS_DIR).as_posix()
)
def test_pack_file_has_no_project_leaks(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    leaks = [term for line in text.splitlines() for term in check_structure.find_line_leaks(line)]
    assert not leaks, f"{path.name} mentions project-specific or other-IDE terms: {leaks}"


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("trigger: glob\n", "start with"),
        ("---\ntrigger: glob\n", "no closing"),
        ("---\ntrigger: glob\n---\nbody\n", "needs `globs`"),
        ("---\ntrigger: model_decision\n---\nbody\n", "needs `description`"),
        ("---\ntrigger: sometimes\n---\nbody\n", "trigger must be one of"),
        ("---\ntrigger: always_on\ndescription: Regras: tudo\n---\nbody\n", "must be quoted"),
        ("---\ntrigger: glob\nglobs: *.py\n---\nbody\n", "must be quoted"),
        ('---\ntrigger: always_on\ndescription: "aberta\n---\nbody\n', "unbalanced"),
        ("---\ntrigger: always_on\n  nested: x\n---\nbody\n", "flat"),
        ("---\ntrigger: always_on\nalias: x\n---\nbody\n", "unknown key"),
        ("---\ntrigger: always_on\n---\n\n", "body is empty"),
    ],
)
def test_frontmatter_validator_rejects_invalid_rules(text: str, problem: str) -> None:
    _, problems = frontmatter(text)

    assert any(problem in item for item in problems), problems


def test_frontmatter_validator_accepts_quoted_values() -> None:
    text = '---\ntrigger: glob\nglobs: "**/*.py"\ndescription: "Regras: Python"\n---\nCorpo\n'

    fields, problems = frontmatter(text)

    assert problems == []
    assert fields == {"trigger": "glob", "globs": "**/*.py", "description": "Regras: Python"}


def test_enabled_packs_merge_their_gates_after_core(tmp_path: Path) -> None:
    for name in PACKS:
        shutil.copytree(
            PACKS_DIR / name,
            tmp_path / "harness" / "packs" / name,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    core = tmp_path / "harness" / "core.toml"
    core.write_text(
        '[[gates]]\nname = "secrets"\ncommand = ["python", "scripts/harness/check_secrets.py"]\n'
        'hint = "Remova o segredo."\ngroup = "core"\nfast = true\n',
        encoding="utf-8",
    )
    target = tmp_path / "harness.toml"
    target.write_text(
        '[project]\nname = "demo"\n\n[packs]\nenabled = ["python", "node", "web-ui", '
        '"research-guard", "data-engineering", "bi-pbip"]\n\n[[gates]]\nname = "custom"\n'
        'command = ["make", "check"]\nhint = "Corrija."\ngroup = "stack"\n',
        encoding="utf-8",
    )

    cfg = config.load(target)

    names = [gate.name for gate in cfg.gates]
    assert cfg.packs == PACKS
    assert names == [
        "secrets",
        *EXPECTED_GATES["python"],
        *EXPECTED_GATES["node"],
        *EXPECTED_GATES["data-engineering"],
        *EXPECTED_GATES["bi-pbip"],
        "custom",
    ]


def test_pack_gate_names_do_not_collide_with_repository_gates() -> None:
    def read(path: Path) -> dict[str, object]:
        return tomllib.loads(path.read_text(encoding="utf-8-sig"))

    core = config.parse(read(config.REPO_ROOT / "harness" / "core.toml"))
    project = config.parse(read(config.CONFIG_PATH))
    merged = config.merge(core, project)

    combined = config.merge_packs(merged, tuple(load(name) for name in PACKS))

    names = [gate.name for gate in combined.gates]
    assert len(names) == len(set(names))
