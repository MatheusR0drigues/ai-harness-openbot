"""Tests for the single spec gate (scripts/harness/validate_spec.py).

Spec folders live in tests/fixtures/specs/<case>/; the empty folder of ADR-0003 is created in
tmp_path because git cannot store an empty directory.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import validate_spec

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "harness" / "validate_spec.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "specs"
HINT_LINES = ["--- fix hint ---", *validate_spec.HINT.splitlines()]
NO_EARS = "lacks an uppercase EARS keyword `DEVE`, `DEVEM` or `SHALL` outside backticks"
VAGUE_FIX = "replace with a measurable limit (e.g. `em até 2 s`, `at most 3 retries`)"


def read(case: str, name: str) -> str:
    return (FIXTURES / case / name).read_text(encoding="utf-8")


def problems(case: str) -> list[str]:
    return validate_spec.validate_spec_dir(FIXTURES / case, case)


def make_requirements(criterion: str) -> str:
    """Minimal valid requirements.md whose only criterion (1.1) starts on line 9."""
    return (
        "# Requisitos\n\n### Requisito 1: Item\n\n"
        "**História:** Como mantenedor, quero um item, para testar o validador.\n\n"
        f"#### Critérios de Aceite\n\n1. {criterion}\n\n## Fora de Escopo\n\n- Nada.\n"
    )


def make_repo(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    (root / "specs").mkdir()
    return root


def copy_case(case: str, destination: Path) -> Path:
    shutil.copytree(FIXTURES / case, destination)
    return destination


# Valid specs
@pytest.mark.parametrize("case", ["valid-ptbr", "valid-en", "nested-tasks", "multiline-ears"])
def test_valid_fixture_has_no_problems(case: str) -> None:
    assert problems(case) == []


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("valid-ptbr", {"1", "1.1", "1.2", "2", "2.1", "2.2", "2.3"}),
        ("valid-en", {"1", "1.1", "1.2", "2", "2.1", "2.2"}),
    ],
)
def test_requirement_ids_are_returned_with_the_problems(case: str, expected: set[str]) -> None:
    found, ids = validate_spec.validate_requirements_text(read(case, "requirements.md"))

    assert found == []
    assert ids == expected


def test_assumption_heading_is_not_a_requirement() -> None:
    requirements = validate_spec.parse_requirements(read("nested-tasks", "requirements.md"))

    assert [r.number for r in requirements] == ["1", "2"]


def test_nested_tasks_parse_and_the_fenced_graph_is_ignored() -> None:
    tasks = validate_spec.parse_tasks(read("nested-tasks", "tasks.md"))

    assert [t.task_id for t in tasks] == ["1", "1.1", "1.2", "1.3", "2"]
    assert [t.optional for t in tasks] == [False, False, False, True, False]
    assert [r.target for r in tasks[3].requirements] == ["2.1", "2.2"]
    assert [r.target for r in tasks[4].depends_on] == ["1"]


def test_task_states_optional_marker_and_dependencies_are_parsed() -> None:
    tasks = validate_spec.parse_tasks(read("valid-ptbr", "tasks.md"))
    by_id = {task.task_id: task for task in tasks}

    assert list(by_id) == ["1", "1.1", "1.2", "1.3", "2", "2.1", "2.2", "2.3", "3"]
    assert {t.task_id for t in tasks if t.done} == {"1", "1.1"}
    assert {t.task_id for t in tasks if t.optional} == {"1.3", "2.2"}
    assert [(r.target, r.line) for r in by_id["2.2"].depends_on] == [("1.3", 21), ("2.1", 21)]


def test_task_line_variants_are_parsed() -> None:
    text = (
        "- [x] 1 Done without a dot\n"
        "- [~] 2. In progress\n"
        "- [ ]* 3. Optional\n"
        "- [X] 3.1. Upper-case box\n"
    )

    tasks = validate_spec.parse_tasks(text)

    assert [(t.task_id, t.done, t.optional, t.title) for t in tasks] == [
        ("1", True, False, "Done without a dot"),
        ("2", False, False, "In progress"),
        ("3", False, True, "Optional"),
        ("3.1", True, False, "Upper-case box"),
    ]


def test_lines_inside_code_fences_are_not_tasks() -> None:
    text = (
        "- [ ] 1. Real task\n\n"
        "```markdown\n- [ ] 9.1 Example inside a fence\n  - _Depends on: 7_\n```\n"
    )

    assert [t.task_id for t in validate_spec.parse_tasks(text)] == ["1"]
    assert validate_spec.validate_tasks_text(text) == []


def test_references_after_a_heading_belong_to_no_task() -> None:
    text = "- [ ] 1. Task\n\n## Notes\n\n- _Requirements: 9.9_\n"

    assert validate_spec.validate_tasks_text(text, {"1", "1.1"}) == []


# Spec folder and phase rules
def test_empty_spec_folder_is_not_started_and_valid(tmp_path: Path) -> None:
    """ADR-0003: the folder exists before requirements.md is written."""
    spec = tmp_path / "new-feature"
    spec.mkdir()

    assert validate_spec.validate_spec_dir(spec) == []


def test_folder_with_any_file_but_no_requirements_fails(tmp_path: Path) -> None:
    """ADR-0003: only a folder without entries is "not started"; any file makes it a spec."""
    spec = tmp_path / "new-feature"
    spec.mkdir()
    (spec / ".gitkeep").write_text("", encoding="utf-8")

    problems_found = validate_spec.validate_spec_dir(spec)

    assert len(problems_found) == 1
    assert "requirements.md is missing" in problems_found[0]


def test_tasks_without_requirements_is_an_error() -> None:
    assert problems("tasks-without-requirements") == [
        "tasks-without-requirements: requirements.md is missing (bugfix specs use bugfix.md); "
        "write the Specify phase before design.md, tasks.md or progress.md"
    ]


@pytest.mark.parametrize(
    ("name", "content"),
    [("design.md", "# Design\n\n## Segurança\n"), ("progress.md", "# Progresso\n")],
)
def test_other_phase_file_without_requirements_is_an_error(
    tmp_path: Path, name: str, content: str
) -> None:
    spec = tmp_path / "half"
    spec.mkdir()
    (spec / name).write_text(content, encoding="utf-8")

    assert validate_spec.validate_spec_dir(spec) == [
        f"{spec.as_posix()}: requirements.md is missing (bugfix specs use bugfix.md); "
        "write the Specify phase before design.md, tasks.md or progress.md"
    ]


def test_bugfix_spec_needs_no_requirements_and_skips_reference_checks(tmp_path: Path) -> None:
    spec = tmp_path / "bug"
    spec.mkdir()
    (spec / "bugfix.md").write_text("# Bugfix\n", encoding="utf-8")
    (spec / "tasks.md").write_text("- [ ] 1. Fix\n  - _Requisitos: 9.9_\n", encoding="utf-8")

    assert validate_spec.validate_spec_dir(spec) == []


def test_specify_phase_alone_is_valid(tmp_path: Path) -> None:
    spec = tmp_path / "specify-only"
    spec.mkdir()
    shutil.copy2(FIXTURES / "valid-ptbr" / "requirements.md", spec / "requirements.md")

    assert validate_spec.validate_spec_dir(spec) == []


def test_missing_spec_folder_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "nope"

    assert validate_spec.validate_spec_dir(missing, "specs/nope") == [
        "specs/nope: spec folder does not exist"
    ]


def test_byte_order_mark_does_not_hide_the_first_heading(tmp_path: Path) -> None:
    spec = tmp_path / "bom"
    spec.mkdir()
    text = make_requirements("O sistema DEVE gravar o arquivo.").replace("# Requisitos\n\n", "")
    (spec / "requirements.md").write_text(text, encoding="utf-8-sig")

    assert validate_spec.validate_spec_dir(spec) == []


def test_document_that_is_not_utf8_is_reported(tmp_path: Path) -> None:
    spec = tmp_path / "latin1"
    spec.mkdir()
    (spec / "requirements.md").write_bytes(b"### Requisito 1: caf\xe9\n")

    assert validate_spec.validate_spec_dir(spec, "specs/latin1") == [
        "specs/latin1/requirements.md: not valid UTF-8 text; save it as UTF-8"
    ]


# Requirements.md
def test_missing_out_of_scope_section_is_reported() -> None:
    assert problems("missing-out-of-scope") == [
        "missing-out-of-scope/requirements.md: missing section `## Fora de Escopo` "
        "(or `## Out of Scope`) stating what the feature will not do"
    ]


@pytest.mark.parametrize(
    "heading", ["## Fora de Escopo", "## Out of Scope", "## 7. Fora de Escopo", "### out of scope"]
)
def test_out_of_scope_heading_variants_are_accepted(heading: str) -> None:
    text = read("missing-out-of-scope", "requirements.md").replace("## Scope", heading)

    assert validate_spec.validate_requirements_text(text)[0] == []


def test_out_of_scope_heading_inside_a_code_fence_does_not_count() -> None:
    fenced = "```markdown\n## Out of Scope\n```"
    text = read("missing-out-of-scope", "requirements.md").replace("## Scope", fenced)

    assert validate_spec.validate_requirements_text(text)[0] == [
        "requirements.md: missing section `## Fora de Escopo` (or `## Out of Scope`) stating "
        "what the feature will not do"
    ]


def test_criteria_without_uppercase_keyword_outside_code_are_reported() -> None:
    """Criterion 1.4 uses the plural `DEVEM` and passes."""
    assert problems("invalid-ears") == [
        f"invalid-ears/requirements.md:9: criterion 1.1: {NO_EARS}: QUANDO o arquivo for salvo, "
        "o sistema grava um backup em `backup/`.",
        f"invalid-ears/requirements.md:10: criterion 1.2: {NO_EARS}: QUANDO o arquivo for salvo, "
        "o sistema deve registrar a data no log.",
        f"invalid-ears/requirements.md:11: criterion 1.3: {NO_EARS}: O sistema registra o evento "
        "com a palavra `SHALL` apenas dentro de código.",
    ]


def test_vague_terms_in_criteria_are_reported() -> None:
    assert problems("invalid-vague") == [
        f"invalid-vague/requirements.md:9: criterion 1.1: vague term(s) 'rápida', 'intuitiva'; "
        f"{VAGUE_FIX}",
        f"invalid-vague/requirements.md:10: criterion 1.2: vague term(s) 'fast', 'user-friendly'; "
        f"{VAGUE_FIX}",
    ]


@pytest.mark.parametrize(
    "term",
    [
        "rápido",
        "Rapido",
        "adequado",
        "fácil",
        "amigável",
        "intuitivo",
        "eficiente",
        "robusto",
        "se possível",
        "FAST",
        "user-friendly",
        "appropriate",
        "easy",
        "robust",
        "efficient",
        "as needed",
    ],
)
def test_each_vague_term_is_flagged(term: str) -> None:
    assert validate_spec.vague_terms(f"THE SYSTEM SHALL answer {term} to the caller.") == [
        term.lower()
    ]


@pytest.mark.parametrize(
    "criterion",
    [
        "O sistema DEVE executar `verify --fast` entre tarefas.",
        "THE SYSTEM SHALL list breakfast menus.",
        "THE SYSTEM SHALL report the fastest route.",
        "O sistema DEVE medir a rapidez em milissegundos.",
        "O sistema DEVE usar aspas simples no comando.",
    ],
)
def test_vague_terms_respect_word_boundaries_and_code_spans(criterion: str) -> None:
    assert validate_spec.validate_requirements_text(make_requirements(criterion))[0] == []


def test_multiline_criterion_is_joined_and_keeps_its_first_line() -> None:
    """ADR-0006: indented continuation lines belong to the numbered criterion above."""
    requirements = validate_spec.parse_requirements(read("multiline-ears", "requirements.md"))
    criteria = requirements[0].criteria

    assert [(c.number, c.line) for c in criteria] == [("1", 10), ("2", 13), ("3", 15)]
    assert criteria[0].text == (
        "QUANDO um critério ocupar mais de uma linha física, o sistema DEVE tratar as linhas "
        "indentadas seguintes como parte do mesmo critério."
    )
    assert criteria[1].text == (
        "WHEN a criterion is wrapped with a tab-indented line, "
        "THE SYSTEM SHALL join the continuation with the numbered line."
    )


@pytest.mark.parametrize(
    "continuation",
    [
        "THE SYSTEM SHALL record every login attempt.",
        "   - THE SYSTEM SHALL record every login attempt.",
        "   | Condition | THE SYSTEM SHALL record every login attempt. |",
        "   <div>THE SYSTEM SHALL record every login attempt.</div>",
        "   > THE SYSTEM SHALL record every login attempt.",
        "   ```\n   THE SYSTEM SHALL record every login attempt.\n   ```",
        "\n   THE SYSTEM SHALL record every login attempt.",
    ],
    ids=["unindented", "nested-list", "table", "html", "quote", "fence", "after-blank-line"],
)
def test_structural_or_detached_lines_do_not_supply_the_keyword(continuation: str) -> None:
    text = make_requirements(f"WHEN an administrator reviews authentication events\n{continuation}")

    assert validate_spec.validate_requirements_text(text)[0] == [
        f"requirements.md:9: criterion 1.1: {NO_EARS}: "
        "WHEN an administrator reviews authentication events"
    ]


def test_document_without_requirement_sections_is_reported() -> None:
    found, ids = validate_spec.validate_requirements_text(
        "# Requisitos\n\nApenas prosa.\n\n## Fora de Escopo\n\n- Nada.\n"
    )

    assert found == [
        "requirements.md: no requirement sections found; expected "
        "`### Requisito <n>: <title>` or `### Requirement <n>: <title>`"
    ]
    assert ids == set()


def test_requirement_structure_problems_are_reported() -> None:
    text = (
        "### Requisito\n\n"
        "Texto sem história nem critérios.\n\n"
        "### Requisito 2: Duplicado A\n\n"
        "**História:** Como autor, quero A, para B.\n\n"
        "#### Critérios de Aceite\n\n"
        "1. O sistema DEVE fazer A.\n"
        "1. O sistema DEVE fazer B.\n\n"
        "### Requirement 2: Duplicate B\n\n"
        "**User Story:** As an author, I want B, so that C.\n\n"
        "#### Acceptance Criteria\n\n"
        "1. THE SYSTEM SHALL do B.\n\n"
        "## Out of Scope\n\n- Nothing.\n"
    )

    found, ids = validate_spec.validate_requirements_text(text, "specs/x/requirements.md")

    assert found == [
        "specs/x/requirements.md:1: requirement heading needs a number, "
        "e.g. `### Requisito 1: <title>`",
        "specs/x/requirements.md:1: requirement ?: missing story line `**História:**` "
        "(or `**User Story:**`)",
        "specs/x/requirements.md:1: requirement ?: no numbered acceptance criteria under "
        "`#### Critérios de Aceite` (or `#### Acceptance Criteria`)",
        "specs/x/requirements.md:12: criterion 2.1: duplicate criterion number; "
        "number them 1, 2, 3, ...",
        "specs/x/requirements.md:14: duplicate requirement number 2 (first used on line 5)",
    ]
    assert ids == {"2", "2.1"}


# Design.md
def test_missing_security_section_is_reported() -> None:
    """Prose, a `### Notas de Segurança` sub-heading and a fenced heading do not count."""
    assert problems("missing-security") == [
        "missing-security/design.md: missing section `## Segurança` (or `## Threat Model`) "
        "listing each threat, its control and the gate or test that verifies it"
    ]


@pytest.mark.parametrize(
    "heading",
    [
        "## Segurança",
        "## Seguranca",
        "## Threat Model",
        "## Segurança (Modelo de Ameaças OWASP LLM/ASI/MCP e Controles)",
        "## 5. Threat Model",
        "### threat model",
    ],
)
def test_security_heading_variants_are_accepted(heading: str) -> None:
    assert validate_spec.validate_design_text(f"# Design\n\n{heading}\n\n| A | C |\n") == []


# Tasks.md
def test_mandatory_task_cannot_depend_on_an_optional_task() -> None:
    """Optional -> optional (1.3 -> 1.2) and optional -> mandatory (2.1 -> 1.1) are allowed."""
    assert problems("optional-dependency") == [
        "optional-dependency/tasks.md:19: task 3: mandatory task depends on optional task 1.2; "
        "drop the dependency, make 1.2 mandatory or mark 3 optional with `*`",
        "optional-dependency/tasks.md:19: task 3: mandatory task depends on optional task 2.1 "
        "(optional through the `*` of task 2); drop the dependency, make 2.1 mandatory or "
        "mark 3 optional with `*`",
    ]


def test_self_unknown_and_forward_dependencies_and_missing_parent_are_reported() -> None:
    assert problems("bad-dependencies") == [
        "bad-dependencies/tasks.md:7: task 2: depends on itself",
        "bad-dependencies/tasks.md:7: task 2: depends on unknown task 9",
        "bad-dependencies/tasks.md:10: task 3: forward dependency on task 4 declared later "
        "(line 11); reorder or split the tasks",
        "bad-dependencies/tasks.md:13: task 5.1: parent task 5 is missing",
    ]


def test_dependency_cycle_is_reported_with_its_path() -> None:
    assert problems("cycle") == [
        "cycle/tasks.md:5: task 1: forward dependency on task 3 declared later (line 9); "
        "reorder or split the tasks",
        "cycle/tasks.md:3: dependency cycle: 1 -> 3 -> 2 -> 1",
    ]


def test_find_cycle_returns_the_cycle_path_of_the_fixture_graph() -> None:
    tasks = validate_spec.parse_tasks(read("cycle", "tasks.md"))
    graph = validate_spec.dependency_graph(tasks)

    assert graph == {"1": ["3"], "2": ["1"], "3": ["2"]}
    assert validate_spec.find_cycle(graph) == ["1", "3", "2", "1"]


@pytest.mark.parametrize(
    ("graph", "expected"),
    [
        ({"a": ["a"]}, ["a", "a"]),
        ({"x": ["a"], "a": ["b"], "b": ["a"]}, ["a", "b", "a"]),
        ({"a": ["b"], "b": ["c"]}, None),
        ({"1": [], "2": ["1"], "3": ["1", "2"]}, None),
        ({}, None),
    ],
    ids=["self-loop", "cycle-below-start", "target-only-node", "dag", "empty"],
)
def test_find_cycle(graph: dict[str, list[str]], expected: list[str] | None) -> None:
    assert validate_spec.find_cycle(graph) == expected


def test_find_cycle_is_iterative_on_long_chains() -> None:
    graph = {str(n): [str(n + 1)] for n in range(5000)}
    graph["5000"] = ["0"]

    assert validate_spec.find_cycle(graph) == [str(n) for n in range(5001)] + ["0"]


def test_subtask_depending_on_its_own_parent_is_a_cycle() -> None:
    text = "- [ ] 1. Parent\n  - [ ] 1.1 Child\n    - _Depends on: 1_\n"

    assert validate_spec.validate_tasks_text(text) == [
        "tasks.md:1: dependency cycle: 1 -> 1.1 -> 1 "
        "(a parent task implicitly depends on its sub-tasks)"
    ]


def test_unknown_requirement_reference_is_reported() -> None:
    assert problems("unknown-requirement") == [
        "unknown-requirement/tasks.md:4: task 1: references unknown requirement 1.9",
        "unknown-requirement/tasks.md:4: task 1: references unknown requirement 7.3",
    ]


def test_requirement_references_are_not_checked_without_known_ids() -> None:
    assert validate_spec.validate_tasks_text(read("unknown-requirement", "tasks.md")) == []


def test_duplicate_task_id_is_reported() -> None:
    assert validate_spec.validate_tasks_text("- [ ] 1. First\n- [ ] 1. Again\n") == [
        "tasks.md:2: task 1: duplicate task id (first declared on line 1)"
    ]


def test_plan_without_tasks_is_reported() -> None:
    assert validate_spec.validate_tasks_text("# Plano\n\nSó prosa.\n") == [
        "tasks.md: no tasks found; expected `- [ ] <n>. <title>` lines"
    ]


# Discovery and CLI
def test_find_repo_root_walks_up_to_the_git_folder(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert validate_spec.find_repo_root(nested) == tmp_path.resolve()


def test_find_repo_root_accepts_a_worktree_git_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: ../main/.git/worktrees/x\n", encoding="utf-8")
    nested = tmp_path / "src"
    nested.mkdir()

    assert validate_spec.find_repo_root(nested) == tmp_path.resolve()


def test_all_discovers_the_root_through_git_and_validates_each_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    copy_case("valid-ptbr", root / "specs" / "exportacao")
    copy_case("valid-en", root / "specs" / "audit-export")
    (root / "specs" / "new-feature").mkdir()
    copy_case("cycle", root / "specs" / "_template")
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    code = validate_spec.main(["--all"])

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "SPEC VALID: specs/audit-export",
        "SPEC VALID: specs/exportacao",
        "SPEC VALID: specs/new-feature",
    ]


def test_all_reports_invalid_specs_with_the_hint_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    copy_case("valid-en", root / "specs" / "a")
    copy_case("cycle", root / "specs" / "b")

    code = validate_spec.main(["--all"], root=root)

    assert code == 1
    assert capsys.readouterr().out.splitlines() == [
        "SPEC VALID: specs/a",
        "SPEC INVALID: specs/b (2 problem(s))",
        "  specs/b/tasks.md:5: task 1: forward dependency on task 3 declared later (line 9); "
        "reorder or split the tasks",
        "  specs/b/tasks.md:3: dependency cycle: 1 -> 3 -> 2 -> 1",
        *HINT_LINES,
    ]


def test_all_without_a_specs_folder_passes_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".git").mkdir()

    assert validate_spec.main(["--all"], root=tmp_path) == 0
    assert capsys.readouterr().out == (
        f"SPECS VALID: no specs/ folder under {tmp_path.as_posix()}; nothing to check\n"
    )


def test_all_with_only_templates_passes_with_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    copy_case("cycle", root / "specs" / "_template")

    assert validate_spec.main(["--all"], root=root) == 0
    assert capsys.readouterr().out == "SPECS VALID: no spec folders in specs; nothing to check\n"


def test_relative_spec_path_is_resolved_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    copy_case("valid-ptbr", root / "specs" / "demo")
    monkeypatch.chdir(root)

    assert validate_spec.main(["specs/demo"]) == 0
    assert capsys.readouterr().out == "SPEC VALID: specs/demo\n"


def test_relative_spec_path_falls_back_to_the_repository_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    copy_case("valid-ptbr", root / "specs" / "demo")
    (root / "docs").mkdir()
    monkeypatch.chdir(root / "docs")

    assert validate_spec.main(["specs/demo"]) == 0
    assert capsys.readouterr().out == "SPEC VALID: specs/demo\n"


def test_file_argument_validates_its_spec_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo")
    spec = copy_case("valid-en", root / "specs" / "demo")

    assert validate_spec.main([str(spec / "tasks.md")], root=root) == 0
    assert capsys.readouterr().out == "SPEC VALID: specs/demo\n"


def test_invalid_single_spec_prints_problems_and_hint(capsys: pytest.CaptureFixture[str]) -> None:
    code = validate_spec.main([str(FIXTURES / "missing-security")], root=FIXTURES)

    assert code == 1
    assert capsys.readouterr().out.splitlines() == [
        "SPEC INVALID: missing-security (1 problem(s))",
        "  missing-security/design.md: missing section `## Segurança` (or `## Threat Model`) "
        "listing each threat, its control and the gate or test that verifies it",
        *HINT_LINES,
    ]


def test_missing_spec_path_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    assert validate_spec.main(["specs/nope"], root=tmp_path) == 1
    assert capsys.readouterr().out.splitlines() == [
        "SPEC INVALID: specs/nope does not exist",
        f"  looked in the working directory and under {tmp_path.as_posix()}",
    ]


@pytest.mark.parametrize("argv", [[], ["--all", "specs/x"], ["--verbose"], ["specs/a", "specs/b"]])
def test_usage_errors_exit_with_1(
    argv: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert validate_spec.main(argv, root=tmp_path) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"SPEC USAGE ERROR: expected `--all` or one spec folder, got {argv}",
        validate_spec.USAGE,
    ]


def test_help_exits_with_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert validate_spec.main(["--help"]) == 0
    assert capsys.readouterr().out == f"{validate_spec.USAGE}\n"


def test_script_runs_standalone_like_the_plugin_copy(tmp_path: Path) -> None:
    """The plugin ships this file alone: `-I` keeps harness modules off sys.path."""
    plugin_scripts = tmp_path / "plugin" / "scripts"
    plugin_scripts.mkdir(parents=True)
    script = Path(shutil.copy2(SCRIPT, plugin_scripts / "validate_spec.py"))
    root = make_repo(tmp_path / "repo")
    copy_case("valid-ptbr", root / "specs" / "demo")
    copy_case("cycle", root / "specs" / "loop")

    result = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(script), "--all"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "SPEC VALID: specs/demo",
        "SPEC INVALID: specs/loop (2 problem(s))",
        "  specs/loop/tasks.md:5: task 1: forward dependency on task 3 declared later (line 9); "
        "reorder or split the tasks",
        "  specs/loop/tasks.md:3: dependency cycle: 1 -> 3 -> 2 -> 1",
        *HINT_LINES,
    ]


def test_runtime_imports_only_the_standard_library() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert sorted(imported - sys.stdlib_module_names) == []


def test_repository_specs_are_valid(capsys: pytest.CaptureFixture[str]) -> None:
    assert validate_spec.main(["--all"], root=REPO_ROOT) == 0
    assert "SPECS VALID" in capsys.readouterr().out
