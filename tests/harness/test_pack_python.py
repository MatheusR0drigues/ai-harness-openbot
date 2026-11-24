"""Tests for the python pack scripts: audit_deps, check_test_determinism, verificar_comentarios."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import audit_deps
import check_test_determinism
import pytest
import verificar_comentarios
from audit_deps import FAIL_BANNER, OK_BANNER, Completed, audit


class FakeRunner:
    """Replays canned results in order and records every command (no network, no uv)."""

    def __init__(self, *responses: Completed) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> Completed:
        self.calls.append(list(command))
        return self.responses[len(self.calls) - 1]


OK = Completed(0, "")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# audit_deps


def test_audit_passes_when_no_vulnerability(tmp_path: Path) -> None:
    runner = FakeRunner(OK, Completed(0, "No known vulnerabilities found"))

    ok, report = audit(runner, tmp_path)

    assert ok
    assert report == f"{OK_BANNER}: No known vulnerabilities found"
    assert runner.calls[0][:3] == ["uv", "export", "--frozen"]
    assert runner.calls[1][:4] == ["uv", "run", "--frozen", "pip-audit"]
    assert "--no-deps" in runner.calls[1]
    assert str(tmp_path / "requirements-locked.txt") in runner.calls[1]


def test_audit_fails_on_vulnerability(tmp_path: Path) -> None:
    runner = FakeRunner(OK, Completed(1, "demo-pkg 1.0.0 GHSA-xxxx-yyyy-zzzz 1.0.1"))

    ok, report = audit(runner, tmp_path)

    assert not ok
    assert report.startswith(f"{FAIL_BANNER}: known vulnerabilities")
    assert "GHSA-xxxx-yyyy-zzzz" in report


def test_audit_offline_fails_with_hint_instead_of_skipping(tmp_path: Path) -> None:
    offline = Completed(1, "requests.exceptions.ConnectionError: Max retries exceeded")

    ok, report = audit(FakeRunner(OK, offline), tmp_path)

    assert not ok
    assert audit_deps.OFFLINE_HINT in report


def test_audit_reports_missing_pip_audit(tmp_path: Path) -> None:
    missing = Completed(2, "error: Failed to spawn: `pip-audit`")

    ok, report = audit(FakeRunner(OK, missing), tmp_path)

    assert not ok
    assert "uv add --dev pip-audit==" in report


def test_audit_fails_when_export_fails(tmp_path: Path) -> None:
    runner = FakeRunner(Completed(2, "lockfile out of date"), OK)

    ok, report = audit(runner, tmp_path)

    assert not ok
    assert "uv export --frozen" in report
    assert len(runner.calls) == 1


def test_audit_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "uv.lock", "version = 1\n")

    assert audit_deps.main([], tmp_path, runner=FakeRunner(OK, Completed(0, "clean"))) == 0
    assert audit_deps.main([], tmp_path, runner=FakeRunner(OK, Completed(1, "vuln"))) == 1
    out = capsys.readouterr().out
    assert OK_BANNER in out
    assert FAIL_BANNER in out


def test_audit_main_fails_without_lockfile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = FakeRunner()

    assert audit_deps.main([], tmp_path, runner=runner) == 1
    assert runner.calls == []
    assert "uv.lock" in capsys.readouterr().out


def test_subprocess_runner_reports_missing_program(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("uv")

    monkeypatch.setattr(subprocess, "run", missing)

    result = audit_deps.subprocess_runner(tmp_path)(["uv", "export"])

    assert result.returncode == 127
    assert audit_deps.is_missing_tool(result.output)


def test_subprocess_runner_reports_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(command: list[str], **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(subprocess, "run", slow)

    result = audit_deps.subprocess_runner(tmp_path)(["uv", "export"])

    assert result.returncode == 124
    assert audit_deps.is_network_error(result.output)


# check_test_determinism

NON_DETERMINISTIC = """\
import time
import time as t
import datetime as dt
from datetime import date, datetime
from time import sleep as nap

import psutil


def test_clock() -> None:
    datetime.now()
    dt.datetime.utcnow()
    date.today()
    time.time()
    t.time_ns()


def test_sleep() -> None:
    time.sleep(1)
    nap(0.1)
"""

DETERMINISTIC = '''\
"""time.sleep(1) and datetime.now() inside strings never count."""
import time


def test_ok(clock: object) -> None:
    # time.sleep(5) in a comment is not a call
    label = "datetime.now()"
    time.perf_counter()
    time.sleep(0)  # determinism: allow
    assert label
'''


def test_determinism_flags_clock_sleep_and_process_through_aliases() -> None:
    violations = check_test_determinism.check_source(NON_DETERMINISTIC, "tests/test_x.py")

    found = [(v.line, v.rule) for v in violations]
    assert found == [
        (7, "process"),
        (11, "clock"),
        (12, "clock"),
        (13, "clock"),
        (14, "clock"),
        (15, "clock"),
        (19, "sleep"),
        (20, "sleep"),
    ]


def test_determinism_ignores_strings_comments_and_allowed_lines() -> None:
    assert check_test_determinism.check_source(DETERMINISTIC, "tests/test_ok.py") == []


def test_determinism_reports_syntax_errors() -> None:
    violations = check_test_determinism.check_source("def broken(:\n", "tests/test_bad.py")

    assert [v.rule for v in violations] == ["syntax"]


def test_determinism_main_exit_codes_and_custom_hints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "tests" / "test_clean.py", DETERMINISTIC)

    assert check_test_determinism.main([], tmp_path) == 0

    write(tmp_path / "tests" / "unit" / "test_dirty.py", NON_DETERMINISTIC)
    capsys.readouterr()

    code = check_test_determinism.main(
        ["--clock-hint", "use the frozen_clock fixture", "--process-hint", "use ProbeStub"],
        tmp_path,
    )

    out = capsys.readouterr().out
    assert code == 1
    assert "test_dirty.py:11: [clock] datetime.now(): use the frozen_clock fixture" in out
    assert "tests/unit/test_dirty.py:7: [process] import psutil: use ProbeStub" in out
    assert "[sleep] time.sleep()" in out


def test_determinism_paths_and_exclude(tmp_path: Path) -> None:
    write(tmp_path / "tests" / "unit" / "test_clean.py", DETERMINISTIC)
    write(tmp_path / "tests" / "integration" / "test_waits.py", NON_DETERMINISTIC)

    assert check_test_determinism.main(["tests/unit"], tmp_path) == 0
    assert check_test_determinism.main([], tmp_path) == 1
    assert check_test_determinism.main(["--exclude", "tests/integration/*"], tmp_path) == 0


def test_determinism_missing_paths(tmp_path: Path) -> None:
    assert check_test_determinism.main([], tmp_path) == 0
    assert check_test_determinism.main(["tests/missing"], tmp_path) == 2


# verificar_comentarios

DIRTY = '''\
"""Module docstring.

Notes
-----
Rewritten on 2024-03-01 after the incident.
"""

VALUE = "2024-03-01"  # comment with 31/12/2024 inside


def run() -> None:
    # ===========
    # FIX: handle empty input
    # see cell 3 for the source table
    # kept since v2 for callers
    return None
'''

CLEAN = '''\
"""Loads the configuration and validates every gate.

The API pins api-version 2024-06-01 on purpose.
Dates use the format: 2024-01-31.
"""

LIMIT = "2024-03-01"  # a literal in code is data, not a comment


def run() -> None:
    # New items start open because the reviewer closes them.
    # fixed width columns keep the report aligned
    # 2024-03-01 stays here for an audited reason  comments: allow
    return None
'''


def comment_rules(text: str, path: str = "src/a.py") -> list[tuple[int, str]]:
    units = verificar_comentarios.units_for(text, path)
    return [(v.unit.line, v.rule) for v in verificar_comentarios.violations_in(units, path)]


def test_comments_flags_dates_banners_labels_cells_and_versions() -> None:
    assert comment_rules(DIRTY) == [
        (5, "DATE"),
        (8, "DATE"),
        (12, "BANNER"),
        (13, "LABEL"),
        (14, "CELL"),
        (15, "VERSION"),
    ]


def test_comments_accepts_present_tense_examples_and_allow_marker() -> None:
    assert comment_rules(CLEAN) == []


def test_comments_reads_notebook_markdown_and_code_cells() -> None:
    notebook = {
        "cells": [
            {"cell_type": "markdown", "source": ["# Report\n", "Updated 2024-05-02\n"]},
            {"cell_type": "code", "source": "%pip list\n# NEW: faster join\nx = 1\n"},
        ]
    }

    path = "notebooks/report.ipynb"
    units = verificar_comentarios.units_for(json.dumps(notebook), path)
    found = verificar_comentarios.violations_in(units, path)

    assert [(v.location(), v.rule) for v in found] == [
        ("notebooks/report.ipynb:cell 0:line 2", "DATE"),
        ("notebooks/report.ipynb:cell 1:line 2", "LABEL"),
    ]


def make_repo(root: Path) -> None:
    write(
        root / "harness.toml",
        '[project]\nname = "demo"\n\n[comments]\ninclude = ["src/**"]\n'
        'exempt_paths = ["src/legacy/"]\n',
    )
    write(root / "src" / "clean.py", CLEAN)
    write(root / "src" / "legacy" / "old.py", DIRTY)
    write(root / "other" / "outside.py", DIRTY)


def test_comments_main_is_clean_within_configured_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path)

    assert verificar_comentarios.main([], tmp_path) == 0
    assert "1 file(s) checked" in capsys.readouterr().out


def test_comments_main_fails_with_exit_1_and_repair_hints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path)
    write(tmp_path / "src" / "dirty.py", DIRTY)

    code = verificar_comentarios.main([], tmp_path)

    out = capsys.readouterr().out
    assert code == 1
    assert "src/dirty.py:13: [LABEL] # FIX: handle empty input" in out
    assert "src/legacy/old.py" not in out
    assert "other/outside.py" not in out
    assert "- BANNER: " in out
    assert verificar_comentarios.FOOTER in out


def test_comments_explicit_paths_skip_include_but_keep_exemptions(tmp_path: Path) -> None:
    make_repo(tmp_path)

    assert verificar_comentarios.main(["other/outside.py"], tmp_path) == 1
    assert verificar_comentarios.main(["src/legacy"], tmp_path) == 0
    assert verificar_comentarios.main(["src/missing.py"], tmp_path) == 2


def test_comments_without_config_scans_whole_repository(tmp_path: Path) -> None:
    write(tmp_path / "pkg" / "mod.py", DIRTY)
    write(tmp_path / ".venv" / "lib" / "dep.py", DIRTY)

    assert verificar_comentarios.main(["pkg"], tmp_path) == 1
    assert verificar_comentarios.main([], tmp_path) == 1
    (tmp_path / "pkg" / "mod.py").write_text(CLEAN, encoding="utf-8")
    assert verificar_comentarios.main([], tmp_path) == 0


@pytest.mark.parametrize(
    "config",
    [
        "[comments]\ninclude = [\n",
        '[comments]\ninclude = "src/**"\n',
        '[comments]\nunknown = ["x"]\n',
    ],
)
def test_comments_invalid_config_exits_2(
    tmp_path: Path, config: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "harness.toml", config)

    assert verificar_comentarios.main([], tmp_path) == 2
    assert "HARNESS CONFIG INVALID" in capsys.readouterr().out


def test_comments_unreadable_notebook_exits_2(tmp_path: Path) -> None:
    write(tmp_path / "nb.ipynb", "not json")

    assert verificar_comentarios.main([], tmp_path) == 2
