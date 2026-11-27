"""Tests for plugin/scripts/pr_via_rest_api.py (offline, deterministic)."""

from __future__ import annotations

import importlib.util
import io
import json
import ssl
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "plugin" / "scripts" / "pr_via_rest_api.py"


def _load_mod() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_via_rest_api", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["pr_via_rest_api"] = module
    spec.loader.exec_module(module)
    return module


pr_mod = _load_mod()
FAKE_TOKEN = "ghp_" + "SyntheticTokenValue1234567890"


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _fake_git(
    *,
    branch: str = "feat/demo",
    remote: str = "https://github.com/acme/repo.git",
    token: str = FAKE_TOKEN,
    commits: str = "abc1234 feat: demo\n",
) -> object:
    def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["credential", "fill"]:
            out = f"protocol=https\nhost=github.com\nusername=x\npassword={token}\n"
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"{branch}\n", stderr="")
        if args[:2] == ["remote", "get-url"]:
            return subprocess.CompletedProcess(args, 0, stdout=f"{remote}\n", stderr="")
        if args[:1] == ["log"]:
            return subprocess.CompletedProcess(args, 0, stdout=commits, stderr="")
        raise AssertionError(f"unexpected git call: {args}")

    return runner


def test_create_pr_success_auto_head_and_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_opener(request: object, *, timeout: int, context: ssl.SSLContext) -> _FakeResponse:
        req = request
        captured["url"] = req.full_url  # type: ignore[attr-defined]
        captured["method"] = req.get_method()  # type: ignore[attr-defined]
        captured["headers"] = dict(req.header_items())  # type: ignore[attr-defined]
        captured["body"] = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        captured["timeout"] = timeout
        captured["verify_mode"] = context.verify_mode
        return _FakeResponse({"number": 42, "html_url": "https://github.com/acme/repo/pull/42"})

    code = pr_mod.main(
        [
            "--title",
            "feat: add feature",
            "--body",
            "Details",
            "--draft",
            "--approved-by",
            "matheus",
            "--approval-ref",
            "msg-1",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=_fake_git(remote="git@github.com:acme/repo.git"),
        opener=fake_opener,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "PR CREATED: #42 https://github.com/acme/repo/pull/42" in out
    assert captured["url"] == "https://api.github.com/repos/acme/repo/pulls"
    assert captured["method"] == "POST"
    assert captured["timeout"] == pr_mod.DEFAULT_TIMEOUT
    assert captured["verify_mode"] == ssl.CERT_REQUIRED
    assert captured["body"] == {
        "title": "feat: add feature",
        "head": "feat/demo",
        "base": "main",
        "body": "Details\n\nAprovado por matheus (msg-1)",
        "draft": True,
    }


def test_create_pr_reads_body_file(tmp_path: Path) -> None:
    body_file = tmp_path / "pr.md"
    body_file.write_text("Line 1\nLine 2\n", encoding="utf-8")
    seen_body: list[str] = []

    def fake_opener(request: object, **_kwargs: object) -> _FakeResponse:
        payload = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
        seen_body.append(payload["body"])
        return _FakeResponse({"number": 7, "html_url": "https://github.com/acme/repo/pull/7"})

    code = pr_mod.main(
        [
            "--title",
            "fix: bug",
            "--body-file",
            str(body_file),
            "--approved-by",
            "matheus",
            "--approval-ref",
            "msg-2",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=_fake_git(),
        opener=fake_opener,
    )

    assert code == 0
    assert seen_body == ["Line 1\nLine 2\n\nAprovado por matheus (msg-2)"]


def test_http_error_sanitizes_token_from_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing_opener(request: object, **_kwargs: object) -> _FakeResponse:
        del request
        fp = io.BytesIO(f"bad request with secret {FAKE_TOKEN}".encode())
        raise urllib.error.HTTPError("https://api.github.com", 422, "Unprocessable", {}, fp)  # type: ignore[arg-type]

    code = pr_mod.main(
        [
            "--title",
            "feat: x",
            "--approved-by",
            "matheus",
            "--approval-ref",
            "msg-3",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=_fake_git(),
        opener=failing_opener,
    )

    err = capsys.readouterr().err
    assert code == 1
    assert FAKE_TOKEN not in err
    assert "[REDACTED]" in err
    assert "HTTP 422" in err


def test_missing_credential_fails_without_calling_api(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    called = False

    def opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        nonlocal called
        called = True
        return _FakeResponse({})

    code = pr_mod.main(
        [
            "--title",
            "feat: x",
            "--approved-by",
            "matheus",
            "--approval-ref",
            "msg-4",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=_fake_git(token=""),
        opener=opener,
    )

    assert code == 1
    assert not called
    assert "no credential password" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--title", "   "],
        ["--title", "ok", "--base", "feat/demo", "--head", "feat/demo"],
        ["--title", "ok", "--repo", "invalid-slug"],
        ["--title", "ok", "--timeout", "0"],
    ],
)
def test_argument_validation_rejects_invalid_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    def noop_opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        return _FakeResponse({})

    code = pr_mod.main(
        [
            *argv,
            "--approved-by",
            "matheus",
            "--approval-ref",
            "msg-5",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=_fake_git(),
        opener=noop_opener,
    )
    assert code == 1
    assert "PR CREATION FAILED:" in capsys.readouterr().err


def test_mutually_exclusive_body_flags_rejected() -> None:
    assert pr_mod.main(["--title", "x", "--body", "a", "--body-file", "b.md"]) == 2
    assert (
        pr_mod.detect_current_branch(
            Path("."),
            git_runner=_fake_git(branch="HEAD"),  # type: ignore[arg-type]
        )
        if False
        else True
    )
    with pytest.raises(pr_mod.PrError, match="detached HEAD"):
        pr_mod.detect_current_branch(Path("."), git_runner=_fake_git(branch="HEAD"))


def test_request_approval_prints_summary_without_network_or_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbid_opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise AssertionError("network must not be called during --request-approval")

    def git_no_cred(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["credential", "fill"]:
            raise AssertionError("credentials must not be read during --request-approval")
        return _fake_git(commits="111aaaa feat: step 1\n222bbbb test: step 2\n")(args)  # type: ignore[operator]

    code = pr_mod.main(
        [
            "--request-approval",
            "--title",
            "feat: worktree pr flow",
            "--body",
            "Resumo das mudancas.",
            "--repo-root",
            str(tmp_path),
        ],
        git_runner=git_no_cred,
        opener=forbid_opener,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "feat: worktree pr flow" in out
    assert "main <- feat/demo" in out
    assert "111aaaa feat: step 1" in out
    assert "Resumo das mudancas." in out
    assert "aguarde aprovação explícita" in out.lower()


@pytest.mark.parametrize(
    "extra_args",
    [
        [],
        ["--approved-by", "matheus"],
        ["--approval-ref", "msg-1"],
    ],
)
def test_create_pr_requires_approval_flags_without_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra_args: list[str]
) -> None:
    def forbid_opener(*_args: object, **_kwargs: object) -> _FakeResponse:
        raise AssertionError("network must not be called without approval flags")

    def forbid_git(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"git must not run without approval flags: {args}")

    code = pr_mod.main(
        ["--title", "feat: x", *extra_args, "--repo-root", str(tmp_path)],
        git_runner=forbid_git,
        opener=forbid_opener,
    )

    assert code == 2
    assert "--approved-by" in capsys.readouterr().err
