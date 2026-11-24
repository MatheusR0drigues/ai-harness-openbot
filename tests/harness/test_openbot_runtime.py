"""Runtime, DAG, init, doctor, and tamper tests for OpenBot."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import check_structure
import check_tamper
import config
import dag_runner
import dialect
import doctor
import init
import pytest

REPO_ROOT = config.REPO_ROOT


def test_openbot_dialect_and_doctor_are_hookless(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# AGENTS.md\n", encoding="utf-8")

    assert dialect.DIALECT == "openbot"
    assert dialect.AGENT == "openbot"
    assert dialect.HOOKS_REL == ""
    assert dialect.kit_items({}) == []
    assert dialect.guidance_set(agents, tmp_path) == ([agents], [])

    check = doctor.check_hooks_file(tmp_path)
    assert check.ok is True
    assert check.detail == "hookless OpenBot mode (CI-first)"
    assert "[PASS] hooks: hookless OpenBot mode (CI-first)" in doctor.render([check])


def test_dag_runner_waves_escalation_and_sqlite_tables(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text(
        "\n".join(
            [
                "- [ ] 1.1 Primeiro",
                "- [ ] 1.2 Segundo",
                "- [ ] 2.1 Terceiro",
                "  - _Depende de: 1.1, 1.2_",
                "",
            ]
        ),
        encoding="utf-8",
    )
    waves = dag_runner.build_waves(tasks_path)
    assert waves == [["1.1", "1.2"], ["2.1"]]
    assert dag_runner.slice_batches(waves, max_parallel_workers=1) == [["1.1"], ["1.2"], ["2.1"]]

    calls: list[tuple[str, str]] = []

    def fake_exec(task_id: str, model: str) -> tuple[str, str]:
        calls.append((task_id, model))
        return ("OK", "done")

    def fake_verify(task_id: str) -> tuple[int, str]:
        if task_id == "1.1" and calls.count(("1.1", "pro")) == 0:
            return (1, "first failure")
        return (0, "ALL GATES PASSED")

    report = dag_runner.run_dag_waves(tasks_path, fake_exec, fake_verify, max_parallel_workers=2)
    assert report.status == "PASS"
    assert ("1.1", "flash") in calls
    assert ("1.1", "pro") in calls

    db_path = tmp_path / "state.db"
    dag_runner.init_tables(db_path)
    dag_runner.upsert_task(
        db_path,
        task_id="1.1",
        feature="demo",
        tier="tier-2",
        worktree="../wt-demo",
        branch="feat/demo",
        status="DONE",
        updated_at="2026-11-23T12:00:00Z",
    )
    assert len(dag_runner.list_tasks(db_path, feature="demo")) == 1
    dag_runner.record_verdict(
        db_path,
        feature="demo",
        commit_sha="abc123",
        verdict="PASS",
        evidence="verify passed",
        created_at="2026-11-23T12:01:00Z",
    )
    assert dag_runner.is_verdict_current(db_path, "demo", "abc123") is True
    assert dag_runner.is_verdict_current(db_path, "demo", "def456") is False


def test_spec_dag_runner_dry_run_and_init_ci_projection(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.md"
    tasks_path.write_text("- [ ] 1.1 Unica\n", encoding="utf-8")

    wf = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "workflows" / "spec_dag_runner.py"),
            "--tasks",
            str(tasks_path),
            "--feature",
            "demo",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert wf.returncode == 0, wf.stderr
    payload = json.loads(wf.stdout)
    assert payload == {"feature": "demo", "waves": [["1.1"]], "batches": [["1.1"]]}

    proj = tmp_path / "proj"
    proj.mkdir()
    assert init.main(["--target", str(proj)], source=REPO_ROOT) == 0
    assert (proj / ".github" / "workflows" / "harness-verify.yml").is_file()
    assert not (proj / ".agents" / "hooks.json").exists()
    assert check_tamper.verify(proj) == []

    target_dag = proj / "scripts" / "harness" / "dag_runner.py"
    target_dag.write_text(target_dag.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    assert check_tamper.verify(proj) != []
    with pytest.raises(dag_runner.DagError):
        dag_runner.slice_batches([["1.1"]], max_parallel_workers=5)


def test_local_code_reviewer_divergence_triggers_collision(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "plugin" / "agents").mkdir(parents=True)
    (repo / ".agents" / "agents").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "plugin" / "agents" / "code-reviewer.md",
        repo / "plugin" / "agents" / "code-reviewer.md",
    )
    shutil.copy2(
        REPO_ROOT / ".agents" / "agents" / "code-reviewer.md",
        repo / ".agents" / "agents" / "code-reviewer.md",
    )
    shutil.copy2(REPO_ROOT / "harness.toml", repo / "harness.toml")
    assert check_structure.local_agent_collisions(repo) == []

    tampered = repo / ".agents" / "agents" / "code-reviewer.md"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\n# modified\n", encoding="utf-8")
    collisions = check_structure.local_agent_collisions(repo)
    assert any("code-reviewer" in err for err in collisions)


def test_spec_dag_runner_rejects_cyclic_tasks(tmp_path: Path) -> None:
    cyclic_tasks = tmp_path / "cyclic_tasks.md"
    cyclic_tasks.write_text(
        "- [ ] 1.1 A\n  - _Depende de: 1.2_\n- [ ] 1.2 B\n  - _Depende de: 1.1_\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "workflows" / "spec_dag_runner.py"),
            "--tasks",
            str(cyclic_tasks),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 1
    assert "DAG ERROR" in proc.stderr


def test_claude_agents_exist_with_claude_code_tools() -> None:
    claude_agents_dir = REPO_ROOT / "claude" / "agents"
    assert claude_agents_dir.is_dir()
    agent_files = sorted(claude_agents_dir.glob("*.md"))
    assert len(agent_files) == 9
    forbidden_tools = (
        "read_file",
        "run_command",
        "edit_file",
        "write_file",
        "manage_task",
        "search_web",
    )
    for path in agent_files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines and lines[0].strip() == "---"
        end = lines.index("---", 1)
        frontmatter = "\n".join(lines[1:end])
        assert f"name: {path.stem}" in frontmatter
        assert "description:" in frontmatter
        assert "model:" in frontmatter
        assert "tools:" in frontmatter
        assert "subagent:" not in frontmatter
        assert "mainAgent:" not in frontmatter
        assert "workspace:" not in frontmatter
        for bad_tool in forbidden_tools:
            assert bad_tool not in text
