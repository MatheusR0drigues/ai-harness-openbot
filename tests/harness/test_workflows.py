"""Static security checks of the repository's GitHub Actions workflows (stdlib text checks).

- only the declared `ci.yml`, `sync-claude.yml`, and `sync-openbot.yml` workflows exist
  (ADR-0012, ADR-0017, ADR-0027);
- every `uses:` is pinned to a full 40-hex commit SHA;
- every workflow declares top-level read-only `permissions:`;
- no `${{ ... }}` expression is interpolated inside a `run:` script;
- checkout does not persist credentials and CI runs the locked dev tools and the full verify.
"""

import re
from pathlib import Path

import config
import pytest

ROOT = config.REPO_ROOT
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.y*ml"))
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
RUN = re.compile(r"^(\s*)(?:-\s+)?run:\s*(.*)$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_scripts(text: str) -> list[str]:
    """The body of every `run:` key, inline or block scalar."""
    lines = text.splitlines()
    scripts: list[str] = []
    index = 0
    while index < len(lines):
        match = RUN.match(lines[index])
        index += 1
        if not match:
            continue
        indent, rest = len(match.group(1)), match.group(2).strip()
        if rest not in ("|", ">", "|-", ">-"):
            scripts.append(rest)
            continue
        body: list[str] = []
        while index < len(lines) and (
            not lines[index].strip() or len(lines[index]) - len(lines[index].lstrip()) > indent
        ):
            body.append(lines[index])
            index += 1
        scripts.append("\n".join(body))
    return scripts


def test_only_the_local_ci_workflow_exists() -> None:
    assert [p.name for p in WORKFLOWS] == ["ci.yml"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_sha(path: Path) -> None:
    refs = [m.group(1) for line in read(path).splitlines() if (m := USES.match(line))]

    assert refs
    assert [ref for ref in refs if not PINNED.match(ref)] == []


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_declares_read_only_permissions(path: Path) -> None:
    text = read(path)

    assert re.search(r"(?m)^permissions:\s*\n\s+contents:\s*read\s*$", text)
    assert not re.search(r"(?m)^\s+\w[\w-]*:\s*write\s*$", text)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_expression_is_interpolated_into_a_run_script(path: Path) -> None:
    assert [script for script in run_scripts(read(path)) if "${{" in script] == []


def test_ci_checks_out_without_credentials_and_runs_the_full_verify() -> None:
    text = read(ROOT / ".github" / "workflows" / "ci.yml")
    scripts = run_scripts(text)

    assert "persist-credentials: false" in text
    assert "uv sync --locked" in scripts
    assert "uv run python scripts/harness/verify.py" in scripts


def test_run_scripts_reads_inline_and_block_scalars() -> None:
    text = "steps:\n  - run: echo one\n  - run: |\n      echo two\n      echo three\n  - name: x\n"

    assert run_scripts(text) == ["echo one", "      echo two\n      echo three"]
