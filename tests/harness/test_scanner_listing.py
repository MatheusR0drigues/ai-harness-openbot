"""Candidate listing shared by the core and pack scanners (Requisito 6: 6.2 a 6.7).

Each scanner runs on a synthetic repository in `tmp_path`, built with a local `git init` and
`git add` (fixed argv, no shell, timeout). The offending content is assembled at runtime so this
file never trips the scanners of this repository. Pack scanners are standalone scripts, loaded by
path like `test_domain_packs.py` does, and receive the root through `--root`.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Protocol

import check_code_risks
import check_secrets
import check_untrusted
import pytest
from config_fixtures import write_core

PACKS_DIR = Path(__file__).resolve().parents[2] / "harness" / "packs"
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
ZERO_WIDTH = chr(0x200B)


def load_pack(rel: str, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, PACKS_DIR / rel)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


check_spark_antipatterns = load_pack(
    "data-engineering/scripts/check_spark_antipatterns.py", "check_spark_antipatterns"
)
check_pbip_sanity = load_pack("bi-pbip/scripts/check_pbip_sanity.py", "check_pbip_sanity")


class ScannerMain(Protocol):
    def __call__(
        self,
        argv: Sequence[str] | None = ...,
        root: Path = ...,
        config_path: Path | None = ...,
    ) -> int: ...


class ScannerRun(Protocol):
    def __call__(self, args: list[str], root: Path, config_path: Path) -> int: ...


def core_run(main: ScannerMain) -> ScannerRun:
    def run(args: list[str], root: Path, config_path: Path) -> int:
        return main(args, root=root, config_path=config_path)

    return run


def pack_run(module: ModuleType) -> ScannerRun:
    """Pack scripts read no harness config; the root goes through `--root`."""

    def run(args: list[str], root: Path, config_path: Path) -> int:
        del config_path
        return module.main([*args, "--root", str(root)])

    return run


@dataclass(frozen=True, slots=True)
class Scanner:
    name: str
    run: ScannerRun
    content: str
    suffix: str
    finding: str
    stream: str

    def rel(self, stem: str) -> str:
        return stem + self.suffix

    def reported(self, out: str, err: str) -> str:
        return out if self.stream == "out" else err


SCANNERS = [
    Scanner(
        "secrets",
        core_run(check_secrets.main),
        f"k = '{AWS_KEY}'\n",
        ".py",
        "{rel}:1: [aws-access-key-id]",
        "out",
    ),
    Scanner(
        "untrusted",
        core_run(check_untrusted.main),
        f"text = 1  # visible{ZERO_WIDTH}hidden\n",
        ".py",
        "{rel}:1: [invisible-characters]",
        "out",
    ),
    Scanner(
        "code-risks",
        core_run(check_code_risks.main),
        "value = eval(payload)\n",
        ".py",
        "{rel}:1: [dynamic-evaluation]",
        "out",
    ),
    Scanner(
        "spark-antipatterns",
        pack_run(check_spark_antipatterns),
        "rows = df.toPandas()\n",
        ".py",
        "[spark-antipatterns] {rel}:1: Evite .toPandas()",
        "err",
    ),
    Scanner(
        "pbip-sanity",
        pack_run(check_pbip_sanity),
        " measure Total = 1\n",
        ".tmdl",
        "[pbip-sanity] {rel}:1: Indentacao TMDL",
        "err",
    ),
]
SCANNER_IDS = [scanner.name for scanner in SCANNERS]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, timeout=60)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def configure(root: Path) -> Path:
    """`[code_risks]` needs an include to scan; the other scanners read their defaults."""
    write_core(root)
    return write(root, "harness.toml", '[code_risks]\ninclude = ["**"]\n')


def make_git_repo(root: Path, gitignore: str = "") -> Path:
    git(root, "init", "-q")
    write(root, ".gitignore", gitignore)
    return configure(root)


@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_ignored_file_not_reported(
    tmp_path: Path, scanner: Scanner, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = make_git_repo(tmp_path, "ignored/\n")
    ignored = scanner.rel("ignored/leak")
    write(tmp_path, ignored, scanner.content)

    code = scanner.run([], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 0
    assert ignored not in captured.out + captured.err


@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_tracked_file_reported(
    tmp_path: Path, scanner: Scanner, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = make_git_repo(tmp_path)
    leak = scanner.rel("pkg/leak")
    write(tmp_path, leak, scanner.content)
    git(tmp_path, "add", leak)

    code = scanner.run([], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 1
    assert scanner.finding.format(rel=leak) in scanner.reported(captured.out, captured.err)


@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_untracked_not_ignored_file_reported(
    tmp_path: Path, scanner: Scanner, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = make_git_repo(tmp_path, "ignored/\n")
    leak = scanner.rel("pkg/leak")
    write(tmp_path, leak, scanner.content)

    code = scanner.run([], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 1
    assert scanner.finding.format(rel=leak) in scanner.reported(captured.out, captured.err)


@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_deleted_tracked_file_ignored(
    tmp_path: Path, scanner: Scanner, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = make_git_repo(tmp_path)
    gone_rel = scanner.rel("pkg/gone")
    gone = write(tmp_path, gone_rel, scanner.content)
    git(tmp_path, "add", gone_rel)
    gone.unlink()

    code = scanner.run([], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 0
    assert gone_rel not in captured.out + captured.err


@pytest.mark.parametrize("mode", ["no-git", "git-exit-128", "git-oserror"])
@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_fallback_walks_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scanner: Scanner,
    mode: str,
) -> None:
    cfg = configure(tmp_path)
    leak = scanner.rel("pkg/leak")
    write(tmp_path, leak, scanner.content)
    write(tmp_path, scanner.rel("node_modules/dep/leak"), scanner.content)
    if mode != "no-git":
        (tmp_path / ".git").mkdir()

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            if mode == "git-oserror":
                raise OSError("git missing")
            return subprocess.CompletedProcess(["git"], 128, stdout=b"", stderr=b"fatal")

        monkeypatch.setattr(check_secrets.subprocess, "run", fake_run)

    code = scanner.run([], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 1
    assert scanner.finding.format(rel=leak) in scanner.reported(captured.out, captured.err)
    assert "node_modules" not in captured.out + captured.err


@pytest.mark.parametrize("scanner", SCANNERS, ids=SCANNER_IDS)
def test_explicit_ignored_path_is_scanned(
    tmp_path: Path, scanner: Scanner, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = make_git_repo(tmp_path, "ignored/\n")
    ignored = scanner.rel("ignored/leak")
    target = write(tmp_path, ignored, scanner.content)

    code = scanner.run([str(target)], tmp_path, cfg)
    captured = capsys.readouterr()

    assert code == 1
    assert scanner.finding.format(rel=ignored) in scanner.reported(captured.out, captured.err)
