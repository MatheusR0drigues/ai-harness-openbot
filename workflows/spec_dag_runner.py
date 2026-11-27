"""Workflow entrypoint for Level-2 DAG execution in OpenBot (stdlib only).

Coordinates `scripts/harness/dag_runner.py` over `specs/<feature>/tasks.md`, verifies
every completed task with `python scripts/harness/verify.py --fast`, and records results in
shared SQLite tables.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "scripts" / "harness"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import dag_runner  # noqa: E402 - runtime path setup for standalone workflow execution


def _run_verify_fast(repo_root: Path) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "scripts/harness/verify.py", "--fast"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def _git_head_sha(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return completed.stdout.strip()
    return "unknown"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute specs/<feature>/tasks.md in Level-2 topological DAG waves."
    )
    parser.add_argument("--tasks", type=Path, required=True, help="Path to tasks.md")
    parser.add_argument("--feature", default="", help="Feature slug for shared SQLite tracking")
    parser.add_argument(
        "--max-workers",
        type=int,
        default=dag_runner.DEFAULT_MAX_PARALLEL_WORKERS,
        help="Maximum parallel workers per batch (1..4, default 2)",
    )
    parser.add_argument("--db", type=Path, default=None, help="Optional SQLite state database path")
    parser.add_argument("--dry-run", action="store_true", help="Print waves and batches only")
    return parser


def _build_mark_pr_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record PR_PENDING_APPROVAL or PR_OPENED status in harness_tasks."
    )
    parser.add_argument("--db", type=Path, required=True, help="SQLite state database path")
    parser.add_argument("--task-id", required=True, help="Task identifier")
    parser.add_argument("--feature", required=True, help="Feature slug")
    parser.add_argument(
        "--status",
        required=True,
        choices=("PR_PENDING_APPROVAL", "PR_OPENED"),
        help="PR workflow status",
    )
    parser.add_argument("--pr-url", default="", help="Pull Request URL when opened")
    parser.add_argument("--branch", default="", help="Feature branch name")
    return parser


def _run_mark_pr(argv: Sequence[str]) -> int:
    args = _build_mark_pr_parser().parse_args(list(argv))
    dag_runner.init_tables(args.db)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    dag_runner.upsert_task(
        args.db,
        task_id=args.task_id,
        feature=args.feature,
        tier="tier-2",
        worktree=str(_REPO_ROOT),
        branch=args.branch,
        status=args.status,
        pr_url=args.pr_url,
        updated_at=now,
    )
    print(
        json.dumps(
            {
                "task_id": args.task_id,
                "feature": args.feature,
                "status": args.status,
                "pr_url": args.pr_url,
            }
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arg_list = list(sys.argv[1:] if argv is None else argv)
    if arg_list and arg_list[0] == "mark-pr":
        return _run_mark_pr(arg_list[1:])
    args = _build_parser().parse_args(arg_list)
    tasks_path: Path = args.tasks.resolve()
    feature: str = args.feature.strip() or tasks_path.parent.name or "default"

    try:
        waves = dag_runner.build_waves(tasks_path)
        batches = dag_runner.slice_batches(waves, max_parallel_workers=args.max_workers)
    except dag_runner.DagError as exc:
        print(f"DAG ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            json.dumps(
                {"feature": feature, "waves": waves, "batches": batches},
                indent=2,
            )
        )
        return 0

    if args.db is not None:
        dag_runner.init_tables(args.db)

    def execute_stub(task_id: str, model: str) -> tuple[str, str]:
        return (
            "BLOCKED",
            f"no external executor wired for task `{task_id}` (model `{model}`); "
            "invoke subagent via OpenBot workflow adapter",
        )

    def verify_task(task_id: str) -> tuple[int, str]:
        del task_id
        return _run_verify_fast(_REPO_ROOT)

    report = dag_runner.run_dag_waves(
        tasks_path,
        execute_stub,
        verify_task,
        max_parallel_workers=args.max_workers,
    )

    if args.db is not None:
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        head_sha = _git_head_sha(_REPO_ROOT)
        verdict = (
            "PASS"
            if report.status == "PASS"
            else ("BLOCKED" if report.status == "BLOCKED" else "FAIL")
        )
        for item in report.results:
            dag_runner.upsert_task(
                args.db,
                task_id=item.task_id,
                feature=feature,
                tier="tier-2",
                worktree=str(_REPO_ROOT),
                branch="",
                status=item.status,
                updated_at=now,
            )
        dag_runner.record_verdict(
            args.db,
            feature=feature,
            commit_sha=head_sha,
            verdict=verdict,
            failure_category="" if verdict == "PASS" else report.status.lower(),
            evidence=f"status={report.status} results={len(report.results)}",
            created_at=now,
        )

    print(json.dumps({"feature": feature, "status": report.status, "blocked": report.blocked}))
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
