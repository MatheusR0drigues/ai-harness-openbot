"""Tests for the unified gate runner (scripts/harness/verify.py)."""

from __future__ import annotations

import io
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
import verify
from config import Gate
from config_fixtures import write_core
from verify import RunResult


def gate(name: str, *, fast: bool = False, group: str = "core", requires_glob: str = "") -> Gate:
    return Gate(
        name=name,
        command=("python", name),
        hint=f"fix {name}",
        group=group,
        fast=fast,
        requires_glob=requires_glob,
    )


class FakeRunner:
    def __init__(self, results: dict[str, RunResult] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, command: Sequence[str], timeout: int) -> RunResult:
        self.calls.append((list(command), timeout))
        return self.results.get(command[-1], RunResult(0, "ok"))

    @property
    def ran(self) -> list[str]:
        return [argv[-1] for argv, _ in self.calls]


def touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def test_python_token_resolves_to_current_interpreter() -> None:
    assert verify.resolve_command(("python", "-m", "x")) == [sys.executable, "-m", "x"]
    assert verify.resolve_command(("uv", "run", "python")) == ["uv", "run", "python"]


def test_all_gates_pass_prints_banner_with_gate_names(tmp_path: Path) -> None:
    runner = FakeRunner()

    ok, report = verify.run_gates((gate("a"), gate("b")), runner, root=tmp_path)

    assert ok
    assert report == f"{verify.SUCCESS_BANNER} (a, b)"
    assert runner.ran == ["a", "b"]


def test_run_stops_at_first_failure_and_reports_it(tmp_path: Path) -> None:
    runner = FakeRunner({"b": RunResult(1, "line1\n\nline2")})

    ok, report = verify.run_gates((gate("a"), gate("b"), gate("c")), runner, root=tmp_path)

    assert not ok
    assert runner.ran == ["a", "b"]
    assert report.startswith("Passed: a\nGATE FAILED: b (exit code 1)")
    assert "--- output ---\nline1\nline2" in report
    assert "--- fix hint ---\nfix b\n" in report
    assert report.endswith(verify.RERUN)


def test_first_gate_failure_reports_none_passed(tmp_path: Path) -> None:
    runner = FakeRunner({"a": RunResult(2, "boom")})

    ok, report = verify.run_gates((gate("a"),), runner, root=tmp_path)

    assert not ok
    assert report.startswith("Passed: (none)\nGATE FAILED: a (exit code 2)")


def test_failure_output_is_truncated(tmp_path: Path) -> None:
    output = "\n".join(f"l{i}" for i in range(50))
    runner = FakeRunner({"a": RunResult(1, output)})

    _, report = verify.run_gates((gate("a"),), runner, max_lines=5, root=tmp_path)

    assert "\nl4\n" in report
    assert "\nl5\n" not in report
    assert "... (45 more lines truncated)" in report


def test_default_truncation_is_forty_lines(tmp_path: Path) -> None:
    output = "\n".join(f"l{i}" for i in range(41))
    runner = FakeRunner({"a": RunResult(1, output)})

    _, report = verify.run_gates((gate("a"),), runner, root=tmp_path)

    assert verify.MAX_LINES == 40
    assert "\nl39\n" in report
    assert "\nl40\n" not in report
    assert "... (1 more lines truncated)" in report


def test_select_gates_fast_keeps_only_fast_gates() -> None:
    gates = (gate("a", fast=True), gate("b"), gate("c", fast=True))

    assert [g.name for g in verify.select_gates(gates, fast=True)] == ["a", "c"]
    assert [g.name for g in verify.select_gates(gates, fast=False)] == ["a", "b", "c"]


def test_select_gates_filters_by_group() -> None:
    gates = (gate("a"), gate("b", group="stack", fast=True), gate("c", group="harness"))

    assert [g.name for g in verify.select_gates(gates, False, "stack")] == ["b"]
    assert [g.name for g in verify.select_gates(gates, True, "core")] == []


def test_gate_timeout_is_passed_to_runner(tmp_path: Path) -> None:
    runner = FakeRunner()
    slow = Gate(name="s", command=("python", "s"), hint="h", group="core", timeout=7)

    verify.run_gates((slow,), runner, root=tmp_path)

    assert runner.calls[0][1] == 7


def test_subprocess_runner_reports_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs, argv=argv)
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    result = verify.subprocess_runner(["tool", "--slow"], 1)

    assert result == RunResult(verify.TIMEOUT_EXIT, "command timed out after 1s")
    assert seen["argv"] == ["tool", "--slow"]
    assert seen["timeout"] == 1
    assert seen["cwd"] == verify.REPO_ROOT
    assert seen["errors"] == "replace"
    assert "shell" not in seen


def test_subprocess_runner_reports_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    result = verify.subprocess_runner(["definitely-not-a-real-tool"], 5)

    assert result.returncode == verify.NOT_FOUND_EXIT
    assert "`definitely-not-a-real-tool` not found" in result.output


def test_subprocess_runner_joins_stdout_and_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 3, stdout="out\n", stderr="err\n")

    monkeypatch.setattr(verify.subprocess, "run", fake_run)

    assert verify.subprocess_runner(["tool"], 5) == RunResult(3, "out\nerr\n")


def test_failure_reports_stale_uv_shim_recovery() -> None:
    stale = RunResult(1, "error: Failed to canonicalize script path")

    report = verify.format_failure(gate("types"), stale)

    assert "--- environment diagnosis ---" in report
    assert "uv sync --reinstall" in report
    assert "doctor.py" in report


@pytest.mark.parametrize(
    ("pattern", "files", "expected"),
    [
        ("**/*.py", ["main.py"], True),
        ("**/*.py", ["src/pkg/mod.py"], True),
        ("**/*.py", ["README.md"], False),
        ("infra/**/*.tf", ["infra/main.tf"], True),
        ("infra/**/*.tf", ["infra/env/prod.tf"], True),
        ("infra/**/*.tf", ["other/main.tf"], False),
        ("package.json", ["package.json"], True),
        ("package.json", ["web/package.json"], False),
        ("**/*.py", [".venv/lib/site.py", "node_modules/x/y.py"], False),
    ],
)
def test_has_matching_file(tmp_path: Path, pattern: str, files: list[str], expected: bool) -> None:
    for rel in files:
        touch(tmp_path, rel)

    assert verify.has_matching_file(tmp_path, pattern) is expected


def test_conditional_gate_without_match_is_skipped_explicitly(tmp_path: Path) -> None:
    touch(tmp_path, "README.md")
    runner = FakeRunner()
    gates = (gate("secrets"), gate("py-lint", group="stack", requires_glob="**/*.py"))

    ok, report = verify.run_gates(gates, runner, root=tmp_path)

    assert ok
    assert runner.ran == ["secrets"]
    assert report.splitlines() == [
        f"{verify.SUCCESS_BANNER} (secrets)",
        "SKIPPED: py-lint (requires_glob **/*.py matched no file)",
    ]


def test_conditional_gate_with_match_runs_and_can_fail(tmp_path: Path) -> None:
    touch(tmp_path, "app.py")
    runner = FakeRunner({"py-lint": RunResult(1, "E501")})
    gates = (gate("py-lint", group="stack", requires_glob="**/*.py"),)

    ok, report = verify.run_gates(gates, runner, root=tmp_path)

    assert not ok
    assert runner.ran == ["py-lint"]
    assert "GATE FAILED: py-lint" in report
    assert "SKIPPED" not in report


def test_skipped_gates_are_listed_before_a_later_failure(tmp_path: Path) -> None:
    runner = FakeRunner({"b": RunResult(1, "boom")})
    gates = (gate("a"), gate("tf", requires_glob="infra/**/*.tf"), gate("b"))

    ok, report = verify.run_gates(gates, runner, root=tmp_path)

    assert not ok
    assert report.splitlines()[:3] == [
        "Passed: a",
        "SKIPPED: tf (requires_glob infra/**/*.tf matched no file)",
        "GATE FAILED: b (exit code 1)",
    ]


def test_only_skipped_gates_still_pass(tmp_path: Path) -> None:
    ok, report = verify.run_gates((gate("tf", requires_glob="*.tf"),), FakeRunner(), root=tmp_path)

    assert ok
    assert report.splitlines()[0] == f"{verify.SUCCESS_BANNER} (none)"


def write_config(tmp_path: Path, groups: Sequence[str], extra: str = "") -> Path:
    """Core-group gates go to harness/core.toml, the others to harness.toml (ADR-0011)."""

    def gates(core: bool) -> str:
        return "".join(
            f'[[gates]]\nname = "g{i}"\ncommand = ["python", "g{i}"]\nhint = "h"\ngroup = "{g}"\n'
            for i, g in enumerate(groups)
            if (g == "core") == core
        )

    write_core(tmp_path, gates(core=True))
    path = tmp_path / "harness.toml"
    path.write_text(gates(core=False) + extra, encoding="utf-8")
    return path


def test_main_warns_when_no_stack_gates_but_still_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(tmp_path, ["core"])

    code = verify.main([], runner=FakeRunner(), config_path=path, root=tmp_path)

    out = capsys.readouterr().out
    assert code == 0
    assert f"{verify.SUCCESS_BANNER} (g0)" in out
    assert verify.NO_STACK_WARNING in out


@pytest.mark.parametrize("group", ["stack", "harness"])
def test_main_does_not_warn_when_a_project_gate_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], group: str
) -> None:
    path = write_config(tmp_path, ["core", group])

    code = verify.main([], runner=FakeRunner(), config_path=path, root=tmp_path)

    assert code == 0
    assert verify.NO_STACK_WARNING not in capsys.readouterr().out


def test_main_returns_1_on_failure(tmp_path: Path) -> None:
    runner = FakeRunner({"g0": RunResult(2, "boom")})
    path = write_config(tmp_path, ["core"])

    assert verify.main([], runner=runner, config_path=path, root=tmp_path) == 1


def test_main_reports_invalid_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = verify.main([], runner=FakeRunner(), config_path=tmp_path / "missing.toml")

    out = capsys.readouterr().out
    assert code == 1
    assert "HARNESS CONFIG INVALID" in out
    assert "--- fix hint ---" in out


def test_verify_fails_on_invalid_skip_templates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Requisito 8.6: a bad [init] skip_templates in the target stops verify before any gate."""
    path = write_config(tmp_path, ["core"], '[init]\nskip_templates = ["AGENTS"]\n')
    runner = FakeRunner()

    code = verify.main([], runner=runner, config_path=path, root=tmp_path)

    out = capsys.readouterr().out
    assert code == 1
    assert "HARNESS CONFIG INVALID: [init] skip_templates" in out
    assert "`AGENTS`" in out
    assert runner.calls == []


def test_main_group_runs_only_that_group(tmp_path: Path) -> None:
    runner = FakeRunner()
    path = write_config(tmp_path, ["core", "stack", "core"])

    code = verify.main(["--group", "core"], runner=runner, config_path=path, root=tmp_path)

    assert code == 0
    assert runner.ran == ["g0", "g2"]


def test_main_group_without_gates_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_config(tmp_path, ["stack"])

    code = verify.main(["--group", "core"], runner=FakeRunner(), config_path=path, root=tmp_path)

    assert code == 1
    assert "no gates in group `core`" in capsys.readouterr().out


def test_main_fast_skips_non_fast_gates(tmp_path: Path) -> None:
    extra = '[[gates]]\nname = "quick"\ncommand = ["python", "quick"]\nhint = "h"\n'
    extra += 'group = "stack"\nfast = true\n'
    runner = FakeRunner()
    path = write_config(tmp_path, ["core", "stack"], extra)

    code = verify.main(["--fast"], runner=runner, config_path=path, root=tmp_path)

    assert code == 0
    assert runner.ran == ["quick"]


def test_main_honors_requires_glob_from_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = '[[gates]]\nname = "py-lint"\ncommand = ["python", "lint"]\nhint = "h"\n'
    extra += 'group = "stack"\nrequires_glob = "**/*.py"\n'
    runner = FakeRunner()
    path = write_config(tmp_path, ["core"], extra)

    code = verify.main([], runner=runner, config_path=path, root=tmp_path)

    assert code == 0
    assert runner.ran == ["g0"]
    assert "SKIPPED: py-lint (requires_glob **/*.py matched no file)" in capsys.readouterr().out


def test_unknown_group_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        verify.main(["--group", "nope"], runner=FakeRunner())


CHECK_MARK = chr(0x2713)  # U+2713 has no cp1252 representation
ESCAPED_CHECK_MARK = b"\\u2713"
# The gate name carries the character too, so the report printed on success (banner with the
# gate names) also holds it; on failure the gate output is printed as well.
CHECK_GATE = f"check-{CHECK_MARK}"


def write_check_config(tmp_path: Path) -> Path:
    write_core(tmp_path)
    path = tmp_path / "harness.toml"
    path.write_text(
        f'[[gates]]\nname = "{CHECK_GATE}"\ncommand = ["python", "check"]\nhint = "h"\n'
        'group = "stack"\n',
        encoding="utf-8",
    )
    return path


def console(monkeypatch: pytest.MonkeyPatch, encoding: str) -> io.BytesIO:
    """Replace stdout and stderr by text streams over byte buffers; return the stdout bytes."""
    stdout = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(stdout, encoding=encoding))
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding=encoding))
    return stdout


def written(buffer: io.BytesIO) -> bytes:
    sys.stdout.flush()
    return buffer.getvalue()


def test_cp1252_console_escapes_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"check": RunResult(1, f"{CHECK_MARK} done")})
    path = write_check_config(tmp_path)
    stdout = console(monkeypatch, "cp1252")

    verify.main([], runner=runner, config_path=path, root=tmp_path)

    assert ESCAPED_CHECK_MARK + b" done" in written(stdout)


@pytest.mark.parametrize(("returncode", "expected"), [(0, 0), (1, 1)])
def test_cp1252_console_keeps_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, returncode: int, expected: int
) -> None:
    runner = FakeRunner({"check": RunResult(returncode, f"{CHECK_MARK} done")})
    path = write_check_config(tmp_path)
    stdout = console(monkeypatch, "cp1252")

    code = verify.main([], runner=runner, config_path=path, root=tmp_path)

    assert code == expected
    assert ESCAPED_CHECK_MARK in written(stdout)


def test_utf8_console_prints_raw_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner({"check": RunResult(1, f"{CHECK_MARK} done")})
    path = write_check_config(tmp_path)
    stdout = console(monkeypatch, "utf-8")

    verify.main([], runner=runner, config_path=path, root=tmp_path)

    out = written(stdout)
    assert f"{CHECK_MARK} done".encode() in out
    assert ESCAPED_CHECK_MARK not in out


def test_resolve_command_rewrites_harness_scripts_in_external_mode(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    ext_cfg = tmp_path / "ext.toml"
    ext_cfg.write_text("", encoding="utf-8")

    cmd = verify.resolve_command(
        ("python", "scripts/harness/check_secrets.py", "--diff"),
        repo_root=target,
        harness_root=verify.REPO_ROOT,
        config_path=ext_cfg,
    )

    assert cmd[0] == sys.executable
    assert Path(cmd[1]) == verify.REPO_ROOT / "scripts/harness/check_secrets.py"
    assert "--diff" in cmd
    assert "--repo-root" in cmd
    assert str(target) in cmd
    assert "--config" in cmd
    assert str(ext_cfg) in cmd


def test_main_external_repo_root_and_config_runs_without_local_harness(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "clean_target"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n", encoding="utf-8")

    ext_cfg = tmp_path / "external-harness.toml"
    ext_cfg.write_text(
        '[project]\nname = "ext"\n\n'
        '[[gates]]\nname = "py-check"\ncommand = ["python", "-c", "print(1)"]\n'
        'hint = "h"\ngroup = "stack"\nrequires_glob = "**/*.py"\n',
        encoding="utf-8",
    )

    runner = FakeRunner()
    code = verify.main(
        ["--repo-root", str(target), "--config", str(ext_cfg), "--group", "stack"],
        runner=runner,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert f"{verify.SUCCESS_BANNER} (py-check)" in out
    assert runner.ran == ["print(1)"]
