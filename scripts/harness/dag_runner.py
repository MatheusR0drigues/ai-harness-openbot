"""Level-2 topological DAG runner and shared SQLite state (stdlib only).

Parses `specs/<feature>/tasks.md`, groups pending leaf tasks into topological waves, slices
execution into semaphore-bounded batches (1..4 workers, default 2), applies Hydrogen
escalation (`flash` -> `pro` -> `ANTI_LOOP_BLOCKED`), and persists task/verdict records
with commit-SHA invalidation and Ratchet Principle candidate detection.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_PARALLEL_WORKERS = 2
MIN_PARALLEL_WORKERS = 1
MAX_PARALLEL_WORKERS = 4
VALID_VERDICTS = frozenset({"PASS", "FAIL", "BLOCKED"})

_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
_TASK_RE = re.compile(
    r"^\s*[-*]\s*\[(?P<state>[ xX~-])\](?P<optional>\*)?\s+"
    r"(?P<id>\d+(?:\.\d+)*)\.?\s+(?P<title>.*)$"
)
_DEPENDS_RE = re.compile(
    r"^\s*(?:[-*]\s+)?_?(?:Depende[ _]de|Depends[ _]on)\s*:\s*(?P<ids>.*?)_?\s*$",
    re.IGNORECASE,
)
_ID_RE = re.compile(r"\d+(?:\.\d+)*")


class DagError(ValueError):
    """Raised when `tasks.md`, semaphore bounds, or verdict state fail validation."""


@dataclass(frozen=True, slots=True)
class DagTask:
    task_id: str
    title: str
    done: bool
    optional: bool
    depends_on: tuple[str, ...]
    is_leaf: bool


@dataclass(frozen=True, slots=True)
class TaskAttemptResult:
    task_id: str
    model_used: str
    attempt: int
    status: str
    verify_output: str


@dataclass(frozen=True, slots=True)
class DagRunReport:
    waves: list[list[str]]
    batches: list[list[str]]
    results: list[TaskAttemptResult]
    status: str
    blocked: bool


TaskExecutor = Callable[[str, str], tuple[str, str]]
VerifyFn = Callable[[str], tuple[int, str]]


def _iter_non_fenced_lines(text: str) -> list[str]:
    lines: list[str] = []
    fence: str | None = None
    for raw_line in text.removeprefix("\ufeff").splitlines():
        stripped = raw_line.strip()
        if fence is not None:
            if stripped.startswith(fence) and stripped == fence[0] * len(stripped):
                fence = None
            continue
        match = _FENCE_RE.match(raw_line)
        if match is not None:
            fence = match.group("fence")
            continue
        lines.append(raw_line)
    return lines


def parse_tasks(tasks_path: Path) -> list[DagTask]:
    """Parse task checkboxes and `_Depende de:_` metadata outside fenced code blocks."""
    try:
        text = tasks_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DagError(f"cannot read tasks file {tasks_path}: {exc}") from exc

    raw_tasks: list[tuple[str, str, bool, bool, list[str]]] = []
    seen_ids: set[str] = set()
    current_deps: list[str] | None = None

    for line in _iter_non_fenced_lines(text):
        task_match = _TASK_RE.match(line)
        if task_match is not None:
            task_id = task_match.group("id")
            if task_id in seen_ids:
                raise DagError(f"duplicate task id `{task_id}` in {tasks_path}")
            seen_ids.add(task_id)
            done = task_match.group("state").lower() == "x"
            optional = task_match.group("optional") == "*"
            deps: list[str] = []
            raw_tasks.append((task_id, task_match.group("title").strip(), done, optional, deps))
            current_deps = deps
            continue

        if current_deps is not None:
            dep_match = _DEPENDS_RE.match(line)
            if dep_match is not None:
                for dep_id in _ID_RE.findall(dep_match.group("ids")):
                    if dep_id not in current_deps:
                        current_deps.append(dep_id)

    all_ids = [item[0] for item in raw_tasks]
    parsed: list[DagTask] = []
    for task_id, title, done, optional, deps in raw_tasks:
        prefix = f"{task_id}."
        is_leaf = not any(other.startswith(prefix) for other in all_ids)
        parsed.append(
            DagTask(
                task_id=task_id,
                title=title,
                done=done,
                optional=optional,
                depends_on=tuple(deps),
                is_leaf=is_leaf,
            )
        )
    return parsed


def _ancestors_of(task_id: str) -> list[str]:
    parts = task_id.split(".")
    return [".".join(parts[:idx]) for idx in range(1, len(parts))]


def _detect_cycle(leaf_deps: dict[str, set[str]]) -> None:
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        mark = state.get(node, 0)
        if mark == 1:
            raise DagError(f"dependency cycle detected at task `{node}`")
        if mark == 2:
            return
        state[node] = 1
        for dep in sorted(leaf_deps.get(node, set())):
            visit(dep)
        state[node] = 2

    for leaf_id in leaf_deps:
        if state.get(leaf_id, 0) == 0:
            visit(leaf_id)


def build_waves(tasks_path: Path) -> list[list[str]]:
    """Return pending leaf task IDs grouped into topological execution waves."""
    tasks = parse_tasks(tasks_path)
    by_id = {task.task_id: task for task in tasks}
    leaves = [task for task in tasks if task.is_leaf]

    for task in tasks:
        for dep in task.depends_on:
            if dep not in by_id:
                raise DagError(f"task `{task.task_id}` references unknown dependency `{dep}`")
            if dep == task.task_id:
                raise DagError(f"task `{task.task_id}` depends on itself")

    leaf_ids_by_prefix: dict[str, list[str]] = {}
    for leaf in leaves:
        leaf_ids_by_prefix.setdefault(leaf.task_id, []).append(leaf.task_id)
        for anc in _ancestors_of(leaf.task_id):
            leaf_ids_by_prefix.setdefault(anc, []).append(leaf.task_id)

    leaf_deps: dict[str, set[str]] = {}
    for leaf in leaves:
        combined_raw: list[str] = list(leaf.depends_on)
        for anc in _ancestors_of(leaf.task_id):
            anc_task = by_id.get(anc)
            if anc_task is not None:
                combined_raw.extend(anc_task.depends_on)

        expanded: set[str] = set()
        for dep in combined_raw:
            if leaf.task_id == dep or leaf.task_id.startswith(f"{dep}."):
                raise DagError(
                    f"dependency cycle: leaf `{leaf.task_id}` depends on ancestor `{dep}`"
                )
            for target_leaf in leaf_ids_by_prefix.get(dep, ()):
                expanded.add(target_leaf)
        leaf_deps[leaf.task_id] = expanded

    _detect_cycle(leaf_deps)

    pending_leaves = [leaf.task_id for leaf in leaves if not leaf.done]
    pending_set = set(pending_leaves)
    pending_deps = {
        tid: {dep for dep in leaf_deps[tid] if dep in pending_set} for tid in pending_leaves
    }

    waves: list[list[str]] = []
    remaining: list[str] = list(pending_leaves)
    while remaining:
        rem_set: set[str] = set(remaining)
        ready: list[str] = [tid for tid in remaining if not (pending_deps[tid] & rem_set)]
        if not ready:
            raise DagError("dependency cycle detected among pending tasks")
        waves.append(ready)
        ready_set: set[str] = set(ready)
        remaining = [tid for tid in remaining if tid not in ready_set]
    return waves


def slice_batches(
    waves: Sequence[Sequence[str]],
    max_parallel_workers: int = DEFAULT_MAX_PARALLEL_WORKERS,
) -> list[list[str]]:
    """Slice each topological wave into batches capped by `max_parallel_workers` (1..4)."""
    if isinstance(max_parallel_workers, bool) or not (
        MIN_PARALLEL_WORKERS <= max_parallel_workers <= MAX_PARALLEL_WORKERS
    ):
        raise DagError(
            f"max_parallel_workers must be between {MIN_PARALLEL_WORKERS} and "
            f"{MAX_PARALLEL_WORKERS}, got {max_parallel_workers!r}"
        )
    batches: list[list[str]] = []
    for wave in waves:
        wave_list = list(wave)
        for index in range(0, len(wave_list), max_parallel_workers):
            batches.append(wave_list[index : index + max_parallel_workers])
    return batches


def run_dag_waves(
    tasks_path: Path,
    execute_fn: TaskExecutor,
    verify_fn: VerifyFn,
    *,
    max_parallel_workers: int = DEFAULT_MAX_PARALLEL_WORKERS,
) -> DagRunReport:
    """Execute topological batches with Hydrogen escalation and strict 2-failure anti-loop."""
    waves = build_waves(tasks_path)
    batches = slice_batches(waves, max_parallel_workers=max_parallel_workers)
    results: list[TaskAttemptResult] = []

    for batch in batches:
        for task_id in batch:
            exec_status, exec_output = execute_fn(task_id, "flash")
            normalized = exec_status.strip().upper()
            if normalized == "BLOCKED":
                results.append(
                    TaskAttemptResult(
                        task_id=task_id,
                        model_used="flash",
                        attempt=1,
                        status="BLOCKED",
                        verify_output=exec_output,
                    )
                )
                return DagRunReport(
                    waves=waves,
                    batches=batches,
                    results=results,
                    status="BLOCKED",
                    blocked=True,
                )

            if normalized == "OK":
                verify_rc, verify_out = verify_fn(task_id)
                if verify_rc == 0:
                    results.append(
                        TaskAttemptResult(
                            task_id=task_id,
                            model_used="flash",
                            attempt=1,
                            status="PASS",
                            verify_output=verify_out,
                        )
                    )
                    continue

            exec_status2, exec_output2 = execute_fn(task_id, "pro")
            normalized2 = exec_status2.strip().upper()
            if normalized2 == "BLOCKED":
                results.append(
                    TaskAttemptResult(
                        task_id=task_id,
                        model_used="pro",
                        attempt=2,
                        status="BLOCKED",
                        verify_output=exec_output2,
                    )
                )
                return DagRunReport(
                    waves=waves,
                    batches=batches,
                    results=results,
                    status="BLOCKED",
                    blocked=True,
                )

            failure_output = exec_output2
            if normalized2 == "OK":
                verify_rc2, verify_out2 = verify_fn(task_id)
                if verify_rc2 == 0:
                    results.append(
                        TaskAttemptResult(
                            task_id=task_id,
                            model_used="pro",
                            attempt=2,
                            status="PASS",
                            verify_output=verify_out2,
                        )
                    )
                    continue
                failure_output = verify_out2

            results.append(
                TaskAttemptResult(
                    task_id=task_id,
                    model_used="pro",
                    attempt=2,
                    status="ANTI_LOOP_BLOCKED",
                    verify_output=failure_output,
                )
            )
            return DagRunReport(
                waves=waves,
                batches=batches,
                results=results,
                status="ANTI_LOOP_BLOCKED",
                blocked=True,
            )

    return DagRunReport(
        waves=waves,
        batches=batches,
        results=results,
        status="PASS",
        blocked=False,
    )


def init_tables(db_path: Path) -> None:
    """Create shared `harness_tasks` and `harness_verdicts` SQLite tables if absent."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS harness_tasks (
                task_id TEXT PRIMARY KEY,
                feature TEXT NOT NULL,
                tier TEXT NOT NULL,
                worktree TEXT NOT NULL,
                branch TEXT NOT NULL,
                status TEXT NOT NULL,
                pr_url TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS harness_verdicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK(verdict IN ('PASS', 'FAIL', 'BLOCKED')),
                failure_category TEXT NOT NULL DEFAULT '',
                evidence TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


PR_STATUSES = ("PR_PENDING_APPROVAL", "PR_OPENED")


def upsert_task(
    db_path: Path,
    *,
    task_id: str,
    feature: str,
    tier: str,
    worktree: str,
    branch: str,
    status: str,
    pr_url: str = "",
    updated_at: str,
) -> None:
    """Insert or update a task row in `harness_tasks` (supports PR_PENDING_APPROVAL/PR_OPENED)."""
    with contextlib.closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(
            """
            INSERT INTO harness_tasks (
                task_id, feature, tier, worktree, branch, status, pr_url, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                feature = excluded.feature,
                tier = excluded.tier,
                worktree = excluded.worktree,
                branch = excluded.branch,
                status = excluded.status,
                pr_url = excluded.pr_url,
                updated_at = excluded.updated_at
            """,
            (task_id, feature, tier, worktree, branch, status, pr_url, updated_at),
        )


def list_tasks(db_path: Path, *, feature: str | None = None) -> list[dict[str, str]]:
    """Return task rows from `harness_tasks`, optionally filtered by `feature`."""
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        if feature is None:
            cursor = conn.execute(
                """
                SELECT task_id, feature, tier, worktree, branch, status, pr_url, updated_at
                FROM harness_tasks
                ORDER BY task_id ASC
                """
            )
        else:
            cursor = conn.execute(
                """
                SELECT task_id, feature, tier, worktree, branch, status, pr_url, updated_at
                FROM harness_tasks
                WHERE feature = ?
                ORDER BY task_id ASC
                """,
                (feature,),
            )
        rows = cursor.fetchall()
    return [
        {
            "task_id": str(row[0]),
            "feature": str(row[1]),
            "tier": str(row[2]),
            "worktree": str(row[3]),
            "branch": str(row[4]),
            "status": str(row[5]),
            "pr_url": str(row[6]),
            "updated_at": str(row[7]),
        }
        for row in rows
    ]


def record_verdict(
    db_path: Path,
    *,
    feature: str,
    commit_sha: str,
    verdict: str,
    failure_category: str = "",
    evidence: str,
    created_at: str,
) -> int:
    """Persist a ternary verdict (`PASS`, `FAIL`, `BLOCKED`) bound to `commit_sha`."""
    if not commit_sha.strip():
        raise DagError("commit_sha must be non-empty")
    if verdict not in VALID_VERDICTS:
        raise DagError(f"invalid verdict `{verdict}`; expected one of {sorted(VALID_VERDICTS)}")
    with contextlib.closing(sqlite3.connect(db_path)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO harness_verdicts (
                feature, commit_sha, verdict, failure_category, evidence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (feature, commit_sha, verdict, failure_category, evidence, created_at),
        )
        return int(cursor.lastrowid or 0)


def is_verdict_current(db_path: Path, feature: str, head_sha: str) -> bool:
    """Return True only when the latest verdict for `feature` is `PASS` at `head_sha`."""
    if not head_sha or head_sha.strip() in ("", "unknown"):
        return False
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT commit_sha, verdict
            FROM harness_verdicts
            WHERE feature = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (feature,),
        ).fetchone()
    if row is None or str(row[0]).strip() in ("", "unknown"):
        return False
    return str(row[1]) == "PASS" and str(row[0]) == head_sha


def detect_ratchet_candidates(db_path: Path, threshold: int = 3) -> list[tuple[str, int]]:
    """Return `(failure_category, fail_count)` pairs meeting or exceeding `threshold`."""
    if threshold < 1:
        raise DagError(f"threshold must be >= 1, got {threshold}")
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT failure_category, COUNT(*)
            FROM harness_verdicts
            WHERE verdict = 'FAIL' AND failure_category != ''
            GROUP BY failure_category
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC, failure_category ASC
            """,
            (threshold,),
        ).fetchall()
    return [(str(row[0]), int(row[1])) for row in rows]
