"""Stdlib-only secret scanner (computational sensor).

Detects credential patterns (generic, cloud/GCP, provider tokens, connection
strings, Azure SAS URLs, and unquoted shell/config assignments) as well as
unignored sensitive files (.env, *.pem, *.key, *.tfstate, ...). Exposes
`scan_text` so PreToolUse guards can block secrets before touching disk.

Runs both inside repositories configured with `harness.toml` + `config.py`
and standalone inside the global OpenBot plugin (`plugin/scripts/`).

Usage:
  python scripts/harness/check_secrets.py              # scan whole repository
  python scripts/harness/check_secrets.py path [path]  # scan files or directories

Allowlist: append `secret-scan: allow` on the offending line (or within the
spanning lines of a multiline finding).
"""

from __future__ import annotations

import fnmatch
import importlib
import os
import re

# Bandit B404: only `git ls-files` runs, with a fixed argv list and no shell.
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol


def find_repo_root() -> Path:
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _load_config_module() -> Any:
    """Use the harness `config` module only when it ships next to this file (local kit).

    In the global plugin copy there is no sibling config.py; an unrelated `config` package
    installed in the environment must never be picked up instead.
    """
    if not Path(__file__).with_name("config.py").is_file():
        return None
    try:
        return importlib.import_module("config")
    except ModuleNotFoundError:
        return None


_CONFIG_MODULE = _load_config_module()
REPO_ROOT: Path = _CONFIG_MODULE.REPO_ROOT if _CONFIG_MODULE is not None else find_repo_root()
ALLOW_MARKER = "secret-scan: allow"
MAX_FILE_BYTES = 1_000_000
GIT_TIMEOUT = 30
BINARY_SNIFF_BYTES = 8192
BINARY_SUFFIXES = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".zip",
        ".abf",
        ".xlsx",
        ".parquet",
        ".pbix",
        ".pbit",
        ".docx",
        ".pptx",
        ".webp",
        ".ico",
    }
)

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".pyright",
        ".terraform",
    }
)
EXCLUDED_FILES = frozenset({"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"})
SENSITIVE_FILE_GLOBS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa",
    "id_ed25519",
    "*.tfstate",
    "*.tfstate.*",
)
SENSITIVE_FILE_EXCEPTIONS = frozenset({".env.example", ".env.test"})
UNQUOTED_EXTENSIONS = frozenset({".sh", ".env", ".ini", ".cfg", ".yml", ".yaml", ".toml"})

_FIELD_PREFIX = (
    r"(?<![A-Za-z0-9])[\w.-]*?"
    r"(?:client_?secret|clientsecret|api_?key|apikey|secret(?:_?key)?|"
    r"access_?token|refresh_?token|token|passw(?:or)?d|senha)"
)

_SYNTACTIC_SAFE_VALUE = re.compile(
    r"^(?:<[^>]+>|\$\{[\w.:-]+\}|\$\{\{.*\}\}|\$\([^)]+\)|\$[A-Za-z_][A-Za-z0-9_]*|"
    r"\{[A-Za-z_][\w.:-]*\}|%\([^)]+\)s)$"
)


class PatternRule(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def regex(self) -> re.Pattern[str]: ...


@dataclass(frozen=True, slots=True)
class _BuiltinRule:
    name: str
    regex: re.Pattern[str]
    value_group: int = 0
    unquoted_only: bool = False
    multiline: bool = False


BUILTIN_PATTERNS: tuple[_BuiltinRule, ...] = (
    _BuiltinRule("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    _BuiltinRule("private-key-block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    _BuiltinRule(
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{40,})\b"),
    ),
    _BuiltinRule(
        "provider-token",
        re.compile(r"\b(?:sk-[A-Za-z0-9_-]{32,}|xox[baprs]-[A-Za-z0-9-]{10,}|dapi[0-9a-f]{32})\b"),
    ),
    _BuiltinRule("gcp-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    _BuiltinRule("gcp-oauth-refresh-token", re.compile(r"\b1//0[0-9A-Za-z_-]{20,}\b")),
    _BuiltinRule(
        "gcp-service-account-json",
        re.compile(r"\"type\"\s*:\s*\"service_account\".*?\"private_key\"\s*:", re.DOTALL),
        multiline=True,
    ),
    _BuiltinRule(
        "azure-sas-token",
        re.compile(r"[?&]sig=([A-Za-z0-9%+/=]{20,})"),
        value_group=1,
    ),
    _BuiltinRule(
        "password-in-url",
        re.compile(r"\b[a-z][a-z0-9+.\-]*://([^\s'\"/:@{}<>]+:[^\s'\"/@{}<>]+)@"),
        value_group=1,
    ),
    _BuiltinRule(
        "connection-string-credential",
        re.compile(
            r"(?<![\w$])(?:password|pwd|accountkey|sharedaccesskey)\s*=\s*"
            r"([^;\"'\s(),[\]{}]{6,})(?=\s*[;\"'])",
            re.IGNORECASE,
        ),
        value_group=1,
    ),
    _BuiltinRule(
        "generic-secret-assignment",
        re.compile(
            _FIELD_PREFIX + r"\b[\"']?\s*[=:]\s*[\"']([^\"'\s]{12,})[\"']",
            re.IGNORECASE,
        ),
        value_group=1,
    ),
    _BuiltinRule(
        "unquoted-secret-assignment",
        re.compile(
            r"^\s*(?:export\s+)?" + _FIELD_PREFIX + r"\s*[:=]\s*([^\s'\"#]{12,})\s*(?:#.*)?$",
            re.IGNORECASE,
        ),
        value_group=1,
        unquoted_only=True,
    ),
)

HINT = (
    "Remove secrets from files. Load credentials from environment variables, "
    "a git-ignored .env file, or Application Default Credentials (ADC). "
    f"For a proven false positive, append `{ALLOW_MARKER}` (in a comment) to that line."
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: [{self.rule}]"


def _is_safe_match(rule_name: str, candidate: str, safe_values: Sequence[str]) -> bool:
    parts = [candidate]
    if rule_name == "password-in-url" and ":" in candidate:
        parts.append(candidate.split(":", 1)[1])
    return any(part in safe_values or _SYNTACTIC_SAFE_VALUE.match(part) for part in parts)


def _allows_unquoted(path: str) -> bool:
    pure = PurePosixPath(path.replace("\\", "/"))
    return pure.suffix.lower() in UNQUOTED_EXTENSIONS or pure.name.startswith(".env")


def scan_text(
    text: str,
    path: str = "input",
    extra: Sequence[PatternRule] = (),
    safe_values: Sequence[str] = (),
) -> list[Finding]:
    lines = text.splitlines()
    findings: list[Finding] = []

    for rule in BUILTIN_PATTERNS:
        if not rule.multiline:
            continue
        for match in rule.regex.finditer(text):
            start_line = text.count("\n", 0, match.start()) + 1
            # Only the line where the block starts may carry the marker: a marker further down
            # (or on an unrelated line above) never exempts a multiline credential.
            if start_line <= len(lines) and ALLOW_MARKER in lines[start_line - 1]:
                continue
            findings.append(Finding(path, start_line, rule.name))

    allow_unquoted = _allows_unquoted(path)
    for number, line in enumerate(lines, start=1):
        if ALLOW_MARKER in line:
            continue
        for rule in BUILTIN_PATTERNS:
            if rule.multiline or (rule.unquoted_only and not allow_unquoted):
                continue
            for match in rule.regex.finditer(line):
                if rule.value_group:
                    candidate = match.group(rule.value_group)
                    if _is_safe_match(rule.name, candidate, safe_values):
                        continue
                findings.append(Finding(path, number, rule.name))
                break
        for pattern in extra:
            if pattern.regex.search(line):
                findings.append(Finding(path, number, pattern.name))

    return findings


def load_gitignore(root: Path) -> list[str]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return []
    lines = gitignore.read_text(encoding="utf-8-sig").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _segments_match(pattern: Sequence[str], path: Sequence[str]) -> bool:
    """Match path segments like git: `*` never crosses `/`, `**` spans zero or more folders."""
    if not pattern:
        return not path
    head = pattern[0]
    if head == "**":
        return any(_segments_match(pattern[1:], path[index:]) for index in range(len(path) + 1))
    return (
        bool(path) and fnmatch.fnmatchcase(path[0], head) and _segments_match(pattern[1:], path[1:])
    )


def _rule_matches(rule: str, candidate: str, is_dir: bool) -> bool | None:
    """True/False when `rule` ignores/re-includes `candidate`; None when it does not apply."""
    negate = rule.startswith("!")
    pattern = rule[1:] if negate else rule
    dir_only = pattern.endswith("/")
    pattern = pattern.rstrip("/")
    if not pattern or (dir_only and not is_dir):
        return None
    if "/" in pattern:  # anchored to the repository root
        matched = _segments_match(pattern.lstrip("/").split("/"), candidate.split("/"))
    else:
        matched = fnmatch.fnmatchcase(candidate.rsplit("/", 1)[-1], pattern)
    return (not negate) if matched else None


def is_ignored(rel: str, rules: Sequence[str]) -> bool:
    """Minimal .gitignore semantics on a POSIX path relative to the repository root.

    A pattern containing `/` is anchored to the root, a trailing `/` matches directories only,
    `!` re-includes and the last matching rule wins. As in git, a file inside an ignored
    directory cannot be re-included.
    """
    parts = rel.split("/")
    for depth in range(1, len(parts) + 1):
        candidate = "/".join(parts[:depth])
        is_dir = depth < len(parts)
        ignored = False
        for rule in rules:
            decision = _rule_matches(rule, candidate, is_dir)
            if decision is not None:
                ignored = decision
        if ignored:
            return True
    return False


def canonical_name(name: str) -> str:
    """The file name the OS actually opens, lowercased.

    NTFS and APFS are case-insensitive (`.ENV`), Windows drops trailing dots and spaces
    (`.env.`) and `name::$DATA` / `name:stream` address a stream of `name`.
    """
    lowered = name.lower()
    base = lowered.split(":", 1)[0] if ":" in lowered else lowered
    return base.rstrip(". ") or base


def is_sensitive_file(name: str) -> bool:
    """Case-, stream- and trailing-dot-insensitive on every OS (see `canonical_name`)."""
    lowered = canonical_name(name)
    if lowered in SENSITIVE_FILE_EXCEPTIONS:
        return False
    return any(fnmatch.fnmatchcase(lowered, glob) for glob in SENSITIVE_FILE_GLOBS)


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def is_excluded(rel: str, name: str, exempt: Sequence[str]) -> bool:
    parts = rel.split("/")
    if name in EXCLUDED_FILES or any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in exempt)


def iter_repo_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def is_binary(path: Path, head: bytes) -> bool:
    """Binary by suffix (case-insensitive) or by a NUL byte in the first `BINARY_SNIFF_BYTES`."""
    return path.suffix.lower() in BINARY_SUFFIXES or b"\x00" in head[:BINARY_SNIFF_BYTES]


def read_text_file(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if is_binary(path, data[:BINARY_SNIFF_BYTES]):
        return None
    return data.decode("utf-8", errors="replace")


def candidate_files(root: Path) -> list[Path] | None:
    """Tracked plus untracked, not ignored files that exist under `root`; None when git cannot say.

    `core.fsmonitor=false` keeps a tampered `.git/config` from running a command during the
    listing. Entries that leave `root` (through `..` or a symbolic link) are dropped.
    """
    if not (root / ".git").exists():
        return None
    try:
        # Bandit B603, B607: fixed argv without a shell; `git` is the user's own tool on PATH.
        completed = subprocess.run(  # nosec B603 B607
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    base = Path(os.path.normpath(root))
    try:
        resolved_base = base.resolve()
    except OSError:
        return None
    found: set[Path] = set()
    for entry in completed.stdout.decode("utf-8", errors="replace").split("\0"):
        if not entry:
            continue
        candidate = Path(os.path.normpath(base / entry))
        try:
            inside = candidate.resolve().is_relative_to(resolved_base)
            if inside and candidate.is_file():
                found.add(candidate)
        except OSError:
            continue
    return sorted(found)


def git_tracked_files(root: Path) -> frozenset[str] | None:
    """Paths git tracks under the repository `root`, or None when that cannot be known."""
    if not (root / ".git").exists():
        return None
    try:
        # Bandit B603, B607: fixed argv without a shell; `git` is the user's own tool on PATH.
        completed = subprocess.run(  # nosec B603 B607
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), "ls-files", "-z", "--cached"],
            capture_output=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return frozenset(p for p in completed.stdout.decode("utf-8", "replace").split("\0") if p)


TrackedFiles = Callable[[Path], "frozenset[str] | None"]


def scan_files(
    files: Iterable[Path],
    root: Path,
    exempt: Sequence[str] = (),
    extra: Sequence[PatternRule] = (),
    safe_values: Sequence[str] = (),
    tracked: TrackedFiles = git_tracked_files,
    explicit: bool = False,
) -> list[Finding]:
    """Scan files; `.gitignore` only skips files git confirms are untracked.

    git never ignores a tracked file, so a new `.gitignore` line must not hide committed content
    from the gate; when git cannot answer (no repository, no git), ignored files are scanned too.
    With `explicit=True` (paths named on the command line) ignored files are scanned as well.
    """
    rules = load_gitignore(root)
    tracked_set = tracked(root)
    findings: list[Finding] = []
    for path in files:
        rel = relative(path, root)
        if not path.is_file() or is_excluded(rel, path.name, exempt):
            continue
        ignored = is_ignored(rel, rules)
        is_tracked = tracked_set is not None and rel in tracked_set
        if is_sensitive_file(path.name):
            if is_tracked:
                findings.append(Finding(rel, 0, "sensitive-file-tracked"))
            elif not ignored:
                findings.append(Finding(rel, 0, "sensitive-file-not-gitignored"))
            continue  # never read credential files, even ignored ones
        if not explicit and ignored and tracked_set is not None and not is_tracked:
            continue  # untracked local overrides and scratch never reach a commit
        text = read_text_file(path)
        if text is not None:
            findings.extend(scan_text(text, rel, extra, safe_values))
    return findings


def load_settings(
    config_path: Path | None = None,
) -> tuple[tuple[str, ...], tuple[PatternRule, ...], tuple[str, ...]]:
    """Secret settings from harness.toml; standalone mode or missing file returns empty tuples."""
    if _CONFIG_MODULE is None:
        return (), (), ()
    target = _CONFIG_MODULE.CONFIG_PATH if config_path is None else config_path
    if not isinstance(target, Path) or not target.is_file():
        return (), (), ()
    cfg = _CONFIG_MODULE.load(target)
    return cfg.exempt_paths, cfg.extra_patterns, cfg.safe_values


def expand_targets(args: Sequence[str], root: Path) -> list[Path]:
    """Without arguments, the git candidate listing (disk walk when git cannot answer)."""
    if not args:
        candidates = candidate_files(root)
        return list(iter_repo_files(root)) if candidates is None else candidates
    targets: list[Path] = []
    for raw in args:
        candidate = Path(raw)
        if not candidate.is_absolute() and not candidate.exists():
            candidate = root / candidate
        if candidate.is_dir():
            targets.extend(iter_repo_files(candidate))
        else:
            targets.append(candidate)
    return targets


def main(
    argv: Sequence[str] | None = None,
    root: Path = REPO_ROOT,
    config_path: Path | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        exempt, extra, safe_values = load_settings(config_path)
    except Exception as exc:
        if _CONFIG_MODULE is not None and isinstance(exc, _CONFIG_MODULE.ConfigError):
            print(f"HARNESS CONFIG INVALID: {exc}")
            return 1
        raise
    files = expand_targets(args, root)
    findings = scan_files(files, root, exempt, extra, safe_values, explicit=bool(args))
    if not findings:
        print("SECRET SCAN PASSED")
        return 0
    print(f"SECRET SCAN FAILED: {len(findings)} finding(s)")
    for finding in findings:
        print(f"  {finding.render()}")
    print("--- fix hint ---")
    print(HINT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
