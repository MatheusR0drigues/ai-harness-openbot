"""Tests for the unified stdlib secret scanner (scripts/harness/check_secrets.py).

Fake secrets are built at runtime so this file never trips the scanner itself.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import check_secrets
import pytest
from config import SecretPattern
from config_fixtures import write_core

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp" + "_" + "a" * 36
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
URL_WITH_PASSWORD = "postgres" + "://user:" + "hunter2" + "@db.example.com/app"
ASSIGNMENT = "api_key = '" + "x" * 20 + "'"
GCP_API_KEY = "AIza" + "0123456789abcdef" + "0123456789abcdefXYZ"
GCP_OAUTH = "1//0" + "A" * 24
OPENAI_LIKE = "sk-" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0iL"
SLACK_LIKE = "xoxb-" + "1234567890-abcdef"
DATABRICKS_LIKE = "dapi" + "0123456789abcdef" * 2
AZURE_SAS = "https://acct.blob.core.windows.net/c/b?" + "sv=2022&sig=" + "A1b2C3d4E5f6G7h8I9j0"
CONN_STR = "Server=db;Database=app;Pwd=" + "Sup3rS3cret!" + ";Encrypt=True;"


def make_sa_json() -> str:
    payload = {
        "type": "service_" + "account",
        "project_id": "demo",
        "private_key": PRIVATE_KEY + "\\nABC\\n",
    }
    return json.dumps(payload, indent=2)


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        (f"key = {AWS_KEY}", "aws-access-key-id"),
        (PRIVATE_KEY, "private-key-block"),
        (f"token: {GITHUB_TOKEN}", "github-token"),
        (URL_WITH_PASSWORD, "password-in-url"),
        (ASSIGNMENT, "generic-secret-assignment"),
        (f"k = '{GCP_API_KEY}'", "gcp-api-key"),
        (f"rt = '{GCP_OAUTH}'", "gcp-oauth-refresh-token"),
        (f"k = '{OPENAI_LIKE}'", "provider-token"),
        (f"k = '{SLACK_LIKE}'", "provider-token"),
        (f"k = '{DATABRICKS_LIKE}'", "provider-token"),
        (f"url = '{AZURE_SAS}'", "azure-sas-token"),
        (f"cs = '{CONN_STR}'", "connection-string-credential"),
    ],
)
def test_scan_text_detects_builtin_patterns(line: str, rule: str) -> None:
    findings = check_secrets.scan_text(f"first line\n{line}\n", "a.py")

    assert [(f.line, f.rule) for f in findings] == [(2, rule)]


def test_scan_text_detects_unquoted_assignment_only_in_config_or_shell() -> None:
    content = "export API_KEY=" + "super_secret_token_99\n"

    assert [f.rule for f in check_secrets.scan_text(content, ".env")] == [
        "unquoted-secret-assignment"
    ]
    assert [f.rule for f in check_secrets.scan_text(content, "deploy.sh")] == [
        "unquoted-secret-assignment"
    ]
    assert check_secrets.scan_text("API_KEY=" + "super_secret_token_99\n", "app.py") == []


def test_scan_text_ignores_syntactic_placeholders_and_safe_values() -> None:
    text = (
        "password = os.environ['DB_PASSWORD']\n"
        "url = 'https://example.com/a@b'\n"
        "token = '${API_TOKEN_VALUE}'\n"
        "secret_key = '<your-secret-value>'\n"
        "custom = 'known-test-fixture-value'\n"
    )
    findings = check_secrets.scan_text(
        text,
        "cfg.env",
        safe_values=("known-test-fixture-value",),
    )

    assert findings == []


def test_scan_text_uses_config_safe_values_over_assignment() -> None:
    text = "api" + "_key = 'intentional_placeholder_value'\n"

    assert (
        check_secrets.scan_text(text, "a.py", safe_values=("intentional_placeholder_value",)) == []
    )
    assert [f.rule for f in check_secrets.scan_text(text, "a.py")] == ["generic-secret-assignment"]


def test_scan_text_multiline_sa_json_respects_line_scoped_allow_only() -> None:
    sa = make_sa_json()
    text_with_unrelated_allow = f"# ok {check_secrets.ALLOW_MARKER}\n{sa}\n"

    findings = check_secrets.scan_text(text_with_unrelated_allow, "creds.json")

    assert any(f.rule == "gcp-service-account-json" for f in findings)

    allowed_sa = sa.replace(
        '"service_account",', f'"service_account",  // {check_secrets.ALLOW_MARKER}'
    )
    allowed_sa = allowed_sa.replace(PRIVATE_KEY, f"{PRIVATE_KEY} {check_secrets.ALLOW_MARKER}")
    assert check_secrets.scan_text(allowed_sa, "creds.json") == []


def test_scan_text_ignores_allow_marker() -> None:
    text = f"key = {AWS_KEY}  # {check_secrets.ALLOW_MARKER}\n"

    assert check_secrets.scan_text(text, "a.py") == []


def test_scan_text_uses_extra_patterns() -> None:
    extra = (SecretPattern("demo-token", re.compile(r"demo_[0-9]{8}")),)

    findings = check_secrets.scan_text("x = demo_" + "12345678", "a.py", extra)

    assert [f.rule for f in findings] == ["demo-token"]


def make_repo(tmp_path: Path, gitignore: str = "") -> Path:
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    return tmp_path


def test_scan_files_flags_sensitive_file_not_gitignored(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / ".env").write_text("A=1\n", encoding="utf-8")

    findings = check_secrets.scan_files([root / ".env"], root)

    assert [(f.path, f.rule) for f in findings] == [(".env", "sensitive-file-not-gitignored")]


@pytest.mark.parametrize("name", [".env", "server.pem", "id.key", "prod.tfstate"])
def test_scan_files_accepts_gitignored_sensitive_file(tmp_path: Path, name: str) -> None:
    root = make_repo(tmp_path, ".env\n*.pem\n*.key\n*.tfstate\n")
    (root / name).write_text("A=1\n", encoding="utf-8")

    assert check_secrets.scan_files([root / name], root) == []


def test_env_example_and_env_test_are_never_sensitive(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    (root / ".env.test").write_text("API_KEY=\n", encoding="utf-8")

    assert check_secrets.scan_files([root / ".env.example", root / ".env.test"], root) == []


def test_exempt_paths_are_skipped(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "notes.md").write_text(AWS_KEY, encoding="utf-8")

    findings = check_secrets.scan_files([root / "docs" / "notes.md"], root, exempt=("docs/",))

    assert findings == []


def test_binary_and_large_files_are_skipped(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "blob.bin").write_bytes(b"\x00\x01" + AWS_KEY.encode())
    (root / "big.txt").write_text(AWS_KEY + "x" * check_secrets.MAX_FILE_BYTES, encoding="utf-8")

    assert check_secrets.scan_files([root / "blob.bin", root / "big.txt"], root) == []


def test_iter_repo_files_skips_excluded_dirs(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "y.py").write_text("y", encoding="utf-8")

    names = {p.name for p in check_secrets.iter_repo_files(tmp_path)}

    assert names == {"y.py"}


def test_main_expands_directory_argument_recursively(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    sub = root / "nested" / "sub"
    sub.mkdir(parents=True)
    (sub / "leak.py").write_text(f"k = '{AWS_KEY}'\n", encoding="utf-8")

    code = check_secrets.main(
        [str(root / "nested")], root=root, config_path=tmp_path / "missing.toml"
    )

    assert code == 1


def test_main_reports_findings_with_hint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    (root / "a.py").write_text(f"k = '{AWS_KEY}'\n", encoding="utf-8")

    code = check_secrets.main([], root=root, config_path=tmp_path / "missing.toml")

    out = capsys.readouterr().out
    assert code == 1
    assert "SECRET SCAN FAILED: 1 finding(s)" in out
    assert "a.py:1: [aws-access-key-id]" in out
    assert "--- fix hint ---" in out


def test_main_clean_repo_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")

    assert check_secrets.main([], root=root, config_path=tmp_path / "missing.toml") == 0
    assert "SECRET SCAN PASSED" in capsys.readouterr().out


SAFE_VALUE = "s3cret_allowed_" + "value"


def write_secret_settings(root: Path) -> Path:
    write_core(root)
    cfg = root / "harness.toml"
    cfg.write_text(
        '[secrets]\nextra_patterns = [{ name = "demo", regex = "demo_[0-9]{8}" }]\n'
        f'safe_values = ["{SAFE_VALUE}"]\n',
        encoding="utf-8",
    )
    return cfg


def test_main_uses_extra_patterns_from_harness_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    cfg = write_secret_settings(root)
    (root / "a.py").write_text("x = demo_" + "12345678\n", encoding="utf-8")

    code = check_secrets.main([str(root / "a.py")], root=root, config_path=cfg)

    out = capsys.readouterr().out
    assert code == 1
    assert "HARNESS CONFIG INVALID" not in out
    assert "a.py:1: [demo]" in out


def test_main_uses_safe_values_from_harness_toml(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path)
    cfg = write_secret_settings(root)
    (root / "a.py").write_text(f'api_key = "{SAFE_VALUE}"\n', encoding="utf-8")

    without_settings = check_secrets.scan_text(f'api_key = "{SAFE_VALUE}"\n', "a.py")
    code = check_secrets.main([str(root / "a.py")], root=root, config_path=cfg)

    assert [f.rule for f in without_settings] == ["generic-secret-assignment"]
    assert code == 0
    assert "SECRET SCAN PASSED" in capsys.readouterr().out


def test_scan_files_skips_gitignored_paths(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "*.local.json\n.work/\n/build/\n!keep.local.json\n")
    leak = f"k = '{AWS_KEY}'\n"
    for relative in ("settings.local.json", ".work/a.py", "build/b.py", "keep.local.json"):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(leak, encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "build").mkdir()
    (root / "src" / "build" / "c.py").write_text(leak, encoding="utf-8")

    files = list(check_secrets.iter_repo_files(root))

    findings = check_secrets.scan_files(files, root, tracked=lambda _root: frozenset())

    assert sorted(f.path for f in findings) == ["keep.local.json", "src/build/c.py"]


def test_tracked_files_are_scanned_even_when_gitignored(tmp_path: Path) -> None:
    """git never ignores a tracked file, so a `.gitignore` line cannot hide it from the gate."""
    root = make_repo(tmp_path, "tracked_secret.py\n.env\n")
    (root / "tracked_secret.py").write_text(f"k = '{AWS_KEY}'\n", encoding="utf-8")
    (root / ".env").write_text("A=1\n", encoding="utf-8")
    files = [root / "tracked_secret.py", root / ".env"]

    tracked = frozenset({"tracked_secret.py", ".env"})
    findings = check_secrets.scan_files(files, root, tracked=lambda _root: tracked)

    assert [(f.path, f.rule) for f in findings] == [
        ("tracked_secret.py", "aws-access-key-id"),
        (".env", "sensitive-file-tracked"),
    ]


def test_ignored_files_are_scanned_when_git_cannot_tell_what_is_tracked(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "*.local.json\n")
    (root / "a.local.json").write_text(f"k = '{AWS_KEY}'\n", encoding="utf-8")

    findings = check_secrets.scan_files([root / "a.local.json"], root, tracked=lambda _root: None)

    assert [f.path for f in findings] == ["a.local.json"]


@pytest.mark.parametrize(
    ("rel", "rules", "ignored"),
    [
        ("docs/x.html", ["docs/*.html"], True),
        ("docs/sub/x.html", ["docs/*.html"], False),
        ("docs/sub/x.html", ["docs/**/*.html"], True),
        ("a/b/c.log", ["**/c.log"], True),
        ("build/x.py", ["/build/"], True),
        ("src/build/x.py", ["/build/"], False),
        ("src/build/x.py", ["build/"], True),
        ("keep.local.json", ["*.local.json", "!keep.local.json"], False),
        ("cache/keep.txt", ["cache/", "!cache/keep.txt"], True),
    ],
)
def test_gitignore_matching_follows_git_semantics(
    rel: str, rules: list[str], ignored: bool
) -> None:
    assert check_secrets.is_ignored(rel, rules) is ignored


def test_git_tracked_files_parses_nul_separated_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()

    def fake_run(
        args: list[str], *, capture_output: bool, timeout: float, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        assert capture_output is True
        assert check is False
        assert timeout > 0
        return subprocess.CompletedProcess(args, 0, stdout=b"README.md\0src/app.py\0", stderr=b"")

    monkeypatch.setattr(check_secrets.subprocess, "run", fake_run)

    tracked = check_secrets.git_tracked_files(tmp_path)

    assert tracked == frozenset({"README.md", "src/app.py"})


@pytest.mark.parametrize("outcome", ["nonzero", "oserror", "timeout"])
def test_git_tracked_files_returns_none_on_git_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    (tmp_path / ".git").mkdir()

    def fake_run(
        args: list[str], *, capture_output: bool, timeout: float, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        if outcome == "oserror":
            raise OSError("git missing")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.CompletedProcess(args, 128, stdout=b"", stderr=b"fatal")

    monkeypatch.setattr(check_secrets.subprocess, "run", fake_run)

    assert check_secrets.git_tracked_files(tmp_path) is None


def test_git_tracked_files_is_unknown_outside_a_repository(tmp_path: Path) -> None:
    assert check_secrets.git_tracked_files(tmp_path) is None


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, timeout=60)


def test_candidate_files_equals_git_listing_on_disk(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    make_repo(tmp_path, "ignored/\n")
    for rel in ("tracked.py", "gone.py", "new.py", "ignored/local.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    git(tmp_path, "add", "tracked.py", "gone.py")
    (tmp_path / "gone.py").unlink()

    candidates = check_secrets.candidate_files(tmp_path)

    assert candidates is not None
    assert all(isinstance(path, Path) for path in candidates)
    assert sorted(check_secrets.relative(path, tmp_path) for path in candidates) == [
        ".gitignore",
        "new.py",
        "tracked.py",
    ]


def test_candidate_files_uses_fixed_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(check_secrets.subprocess, "run", fake_run)

    check_secrets.candidate_files(tmp_path)

    [(args, kwargs)] = calls
    assert args == [
        "git",
        "-c",
        "core.fsmonitor=false",
        "-C",
        str(tmp_path),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    ]
    assert kwargs["timeout"] == check_secrets.GIT_TIMEOUT
    assert kwargs.get("shell", False) is False


def test_git_tracked_files_disables_fsmonitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # D18 applies to every git call of the scanners, not only the candidate listing.
    (tmp_path / ".git").mkdir()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(check_secrets.subprocess, "run", fake_run)

    check_secrets.git_tracked_files(tmp_path)

    [args] = calls
    assert args[:3] == ["git", "-c", "core.fsmonitor=false"]


def test_tracked_env_still_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    make_repo(tmp_path, ".env\n")
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")
    git(tmp_path, "add", "-f", ".env")

    code = check_secrets.main([], root=tmp_path, config_path=tmp_path / "missing.toml")

    assert code == 1
    assert "  .env: [sensitive-file-tracked]" in capsys.readouterr().out


def test_scan_text_multiline_allow_marker_only_counts_on_the_first_line() -> None:
    sa = make_sa_json()
    marked_last = sa.replace(PRIVATE_KEY, f"{PRIVATE_KEY} {check_secrets.ALLOW_MARKER}")

    findings = check_secrets.scan_text(marked_last, "creds.json")

    assert [f.rule for f in findings] == ["gcp-service-account-json"]


def test_repository_is_clean() -> None:
    assert check_secrets.main([]) == 0
