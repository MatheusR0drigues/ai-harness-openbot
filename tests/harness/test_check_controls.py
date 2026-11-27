"""Tests for the anti-weakening sensor (scripts/harness/check_controls.py)."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

import check_controls
import config
import guards
import pytest
from config_fixtures import write_core

PROJECT_GATE = """
[[gates]]
name = "pytest"
command = ["uv", "run", "pytest"]
hint = "h"
group = "harness"
"""
CORE_GATE = """
[[gates]]
name = "secrets"
command = ["python", "scripts/harness/check_secrets.py"]
hint = "h"
group = "core"
fast = true
"""
BASELINE = '[controls]\nrequired_gates = ["secrets"]\nrequired_guards = ["secret_in_write"]\n'
GUARDS = ("secret_in_write", "sensitive_file")


def write_split(tmp_path: Path, core: str, project: str = PROJECT_GATE) -> Path:
    """`core` goes to harness/core.toml, `project` to harness.toml (ADR-0011)."""
    write_core(tmp_path, core)
    path = tmp_path / "harness.toml"
    path.write_text(project, encoding="utf-8")
    return path


def load(tmp_path: Path, core: str, project: str = PROJECT_GATE) -> config.HarnessConfig:
    return config.load(write_split(tmp_path, core, project))


def test_satisfied_baseline_reports_no_problem(tmp_path: Path) -> None:
    cfg = load(tmp_path, CORE_GATE + BASELINE)

    assert check_controls.check(cfg, GUARDS) == []


def test_missing_gate_is_reported_with_the_adr_obligation(tmp_path: Path) -> None:
    cfg = load(tmp_path, CORE_GATE + '[controls]\nrequired_gates = ["untrusted"]\n')

    problems = check_controls.check(cfg, GUARDS)

    assert len(problems) == 1
    assert "`untrusted`" in problems[0]
    assert "docs/adr/" in problems[0]


def test_gate_that_left_the_core_group_is_reported() -> None:
    text = CORE_GATE.replace('group = "core"', 'group = "stack"')
    cfg = config.parse(tomllib.loads(text + '[controls]\nrequired_gates = ["secrets"]\n'))
    cfg = replace(cfg, core_required_gates=("secrets",))

    problems = check_controls.check(cfg, GUARDS)

    assert len(problems) == 1
    assert "moved to group `stack`" in problems[0]


def test_core_file_cannot_hold_a_non_core_gate(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="must be in group `core`"):
        load(tmp_path, CORE_GATE.replace('group = "core"', 'group = "stack"'))


def test_project_may_require_its_own_stack_gate(tmp_path: Path) -> None:
    project = (
        '[controls]\nrequired_gates = ["lint"]\n'
        '[[gates]]\nname = "lint"\ncommand = ["x"]\nhint = "h"\ngroup = "stack"\nfast = true\n'
    )

    assert check_controls.check(load(tmp_path, CORE_GATE + BASELINE, project), GUARDS) == []


def test_gate_that_lost_its_fast_flag_is_reported(tmp_path: Path) -> None:
    core = CORE_GATE.replace("fast = true", "fast = false")
    cfg = load(tmp_path, core + '[controls]\nrequired_gates = ["secrets"]\n')

    problems = check_controls.check(cfg, GUARDS)

    assert len(problems) == 1
    assert "lost `fast = true`" in problems[0]


def test_missing_guard_is_reported(tmp_path: Path) -> None:
    cfg = load(tmp_path, CORE_GATE + '[controls]\nrequired_guards = ["data_egress"]\n')

    problems = check_controls.check(cfg, GUARDS)

    assert len(problems) == 1
    assert "guard `data_egress`" in problems[0]


def test_empty_baseline_warns_instead_of_passing_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_path = write_split(tmp_path, CORE_GATE)

    code = check_controls.main([], root=tmp_path, config_path=cfg_path)

    assert code == 0
    assert "WARNING: no controls baseline" in capsys.readouterr().out


def test_exception_markers_are_counted_per_file(tmp_path: Path) -> None:
    secret, untrusted, risk = check_controls.MARKERS
    (tmp_path / "a.md").write_text(
        f"line one  <!-- {untrusted} -->\nline two  # {secret}\n", encoding="utf-8"
    )
    (tmp_path / "b.py").write_text(f"x = 1  # {risk}\n", encoding="utf-8")
    (tmp_path / "c.md").write_text("no marker here\n", encoding="utf-8")

    assert check_controls.count_markers(tmp_path) == {"a.md": 2, "b.py": 1}


def test_exempt_paths_and_excluded_dirs_are_not_counted(tmp_path: Path) -> None:
    marker = check_controls.MARKERS[0]
    for rel in ("docs/research/a.md", ".venv/lib/b.py", "src/c.py"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# {marker}\n", encoding="utf-8")

    assert check_controls.count_markers(tmp_path, ("docs/research/",)) == {"src/c.py": 1}


def test_main_reports_intact_controls_and_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_path = write_split(tmp_path, CORE_GATE + '[controls]\nrequired_gates = ["secrets"]\n')
    (tmp_path / "x.py").write_text(f"x = 1  # {check_controls.MARKERS[2]}\n", encoding="utf-8")

    code = check_controls.main([], root=tmp_path, config_path=cfg_path)

    out = capsys.readouterr().out
    assert code == 0
    assert "CONTROLS INTACT (1 gate(s), 0 guard(s))" in out
    assert "  exception markers: x.py (1)" in out


def test_main_lists_every_scanner_exemption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = (
        '[secrets]\nexempt_paths = ["vendor/"]\n'
        '[untrusted]\nexempt_paths = ["docs/imported/"]\n'
        '[code_risks]\nexempt_paths = ["legacy/"]\n' + PROJECT_GATE
    )
    cfg_path = write_split(
        tmp_path, CORE_GATE + '[controls]\nrequired_gates = ["secrets"]\n', project
    )

    code = check_controls.main([], root=tmp_path, config_path=cfg_path)

    out = capsys.readouterr().out
    assert code == 0
    assert "  exempt path [secrets]: vendor/" in out
    assert "  exempt path [untrusted]: docs/imported/" in out
    assert "  exempt path [code_risks]: legacy/" in out


def test_main_fails_when_a_control_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_path = write_split(tmp_path, CORE_GATE + '[controls]\nrequired_gates = ["untrusted"]\n')

    code = check_controls.main([], root=tmp_path, config_path=cfg_path)

    out = capsys.readouterr().out
    assert code == 1
    assert "CONTROLS WEAKENED: 1 problem(s)" in out
    assert "--- fix hint ---" in out


def test_invalid_config_is_reported_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg_path = write_split(tmp_path, "", "[[gates]\n")

    code = check_controls.main([], root=tmp_path, config_path=cfg_path)

    assert code == 1
    assert "HARNESS CONFIG INVALID" in capsys.readouterr().out


def test_repository_baseline_covers_every_guard() -> None:
    declared = set(config.load().controls.required_guards)

    assert declared == {guard.__name__ for guard in (*guards.ALL, *guards.CONFIRM)}


def test_repository_controls_are_intact() -> None:
    assert check_controls.main([]) == 0
