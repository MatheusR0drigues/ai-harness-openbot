"""Stdlib-only sensor for the insecure patterns most often produced by code generation.

Studies of LLM-generated code keep finding the same classic weaknesses: queries and commands
built by string concatenation, dynamic evaluation, unsafe deserialization, non-cryptographic
randomness for tokens, broken hashes, disabled TLS verification, DOM injection and network
calls without a timeout. This sensor looks for those shapes in Python and JavaScript/TypeScript.

It is deliberately inert until a project declares where its code lives:

    [code_risks]
    include = ["src/**", "app/**"]

With no `include`, the sensor prints a warning and exits 0, the same way `verify.py` reports a
project with no stack gates. It is a lint, not a proof: it reads one line at a time and cannot
follow data flow, so it complements review instead of replacing it.

Usage:
  python scripts/harness/check_code_risks.py            # scan the configured paths
  python scripts/harness/check_code_risks.py src/a.py   # scan specific files

Allowlist: append the marker `code-risk: allow` to a line to accept a proven false positive.
Exit code: 0 when clean or unconfigured, 1 when findings exist or the config is invalid.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

import check_secrets
import check_untrusted
import config
from config import ConfigError, ScanSettings

REPO_ROOT = config.REPO_ROOT
ALLOW_MARKER = "code-risk: allow"
PYTHON = (".py", ".pyi")
WEB = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
SECRET_WORDS = r"token|secret|password|passwd|key|nonce|salt|otp|session|csrf"
# Real SQL grammar, not a bare keyword: `delete it and re-run ...` in a message is not a query.
SQL_STATEMENT = (
    r"(?:select\b[^\"'`]*\bfrom|insert\s+into|update\b[^\"'`]*\bset|delete\s+from|merge\s+into)"
)


@dataclass(frozen=True, slots=True)
class CodeRule:
    name: str
    regex: re.Pattern[str]
    extensions: tuple[str, ...]
    absent: re.Pattern[str] | None = None  # match is a finding only without this inside it


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}]"


RULES: tuple[CodeRule, ...] = (
    CodeRule(
        "sql-concatenation",
        re.compile(rf"""(?i)["'][^"']*\b{SQL_STATEMENT}\b[^"']*["']\s*(?:\+|%)\s*\w"""),
        PYTHON,
    ),
    CodeRule(
        "sql-concatenation",
        re.compile(rf"""(?i)f["'][^"']*\b{SQL_STATEMENT}\b[^"']*\{{"""),
        PYTHON,
    ),
    CodeRule(
        "sql-concatenation",
        re.compile(rf"(?i)`[^`]*\b{SQL_STATEMENT}\b[^`]*\$\{{"),
        WEB,
    ),
    CodeRule("shell-injection", re.compile(r"\bshell\s*=\s*True\b"), PYTHON),
    CodeRule(
        "shell-injection",
        re.compile(
            r"(?i)\b(?:os\.system|os\.popen|subprocess\.(?:run|call|check_call|check_output"
            r"|Popen))\s*\(\s*f[\"'][^\"']*\{"
        ),
        PYTHON,
    ),
    CodeRule(
        "shell-injection",
        re.compile(r"(?i)\b(?:exec|execSync|spawn|spawnSync)\s*\(\s*[`\"'][^`\"']*\$\{"),
        WEB,
    ),
    CodeRule("dynamic-evaluation", re.compile(r"\b(?:eval|exec)\s*\("), PYTHON),
    CodeRule("dynamic-evaluation", re.compile(r"\beval\s*\(|\bnew\s+Function\s*\("), WEB),
    CodeRule(
        "unsafe-deserialization",
        re.compile(r"\b(?:pickle|cPickle|dill|shelve)\.loads?\s*\("),
        PYTHON,
    ),
    CodeRule(
        "unsafe-deserialization",
        re.compile(r"\byaml\.load\s*\([^)]*\)?"),
        PYTHON,
        absent=re.compile(r"(?i)safe_?loader"),
    ),
    CodeRule(
        "weak-randomness",
        re.compile(
            rf"(?i)(?=.*\b(?:{SECRET_WORDS})\b).*"
            r"\brandom\.(?:random|randint|randrange|choice|choices|shuffle|uniform)\s*\("
        ),
        PYTHON,
    ),
    CodeRule(
        "weak-randomness",
        re.compile(rf"(?i)(?=.*\b(?:{SECRET_WORDS})\b).*\bMath\.random\s*\("),
        WEB,
    ),
    CodeRule("broken-hash", re.compile(r"(?i)\bhashlib\.(?:md5|sha1)\s*\("), PYTHON),
    CodeRule(
        "broken-hash",
        re.compile(r"(?i)createHash\s*\(\s*[\"'](?:md5|sha1)[\"']"),
        WEB,
    ),
    CodeRule(
        "missing-timeout",
        re.compile(
            r"\b(?:requests|httpx)\.(?:get|post|put|patch|delete|head|options|request)"
            r"\s*\([^)]*\)"
        ),
        PYTHON,
        absent=re.compile(r"timeout\s*="),
    ),
    CodeRule("tls-verification-disabled", re.compile(r"(?i)\bverify\s*=\s*False\b"), PYTHON),
    CodeRule(
        "tls-verification-disabled",
        re.compile(r"(?i)rejectUnauthorized\s*:\s*false"),
        WEB,
    ),
    CodeRule("dom-injection", re.compile(r"\.(?:innerHTML|outerHTML)\s*="), WEB),
    CodeRule("dom-injection", re.compile(r"\bdangerouslySetInnerHTML\b"), WEB),
)

HINT = (
    "Fix the pattern, do not silence it: parameterize the query, pass an argument list instead of "
    "a command string, parse instead of evaluating, use a safe loader, take randomness from a "
    "cryptographic source, hash with SHA-256 or stronger, keep TLS verification on, and set a "
    f"timeout on every network call. For a proven false positive, append `{ALLOW_MARKER}` (in a "
    "comment) to that line."
)


def rules_for(path: str) -> tuple[CodeRule, ...]:
    suffix = PurePath(path).suffix.lower()
    return tuple(rule for rule in RULES if suffix in rule.extensions)


def scan_text(text: str, path: str, rules: Sequence[CodeRule]) -> list[Finding]:
    findings: list[Finding] = []
    if not rules:
        return findings
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for rule in rules:
            for match in rule.regex.finditer(line):
                if rule.absent is None or not rule.absent.search(match[0]):
                    findings.append(Finding(path, number, rule.name))
                    break
    return findings


def scan_files(
    files: Iterable[Path],
    root: Path,
    exempt: Sequence[str] = (),
    include: Sequence[str] = (),
) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        rel = check_secrets.relative(path, root)
        if not path.is_file() or check_secrets.is_excluded(rel, path.name, exempt):
            continue
        if not check_untrusted.is_included(rel, include):
            continue
        rules = rules_for(rel)
        text = check_secrets.read_text_file(path) if rules else None
        if text is not None:
            findings.extend(scan_text(text, rel, rules))
    return findings


def load_settings(config_path: Path | None = None) -> ScanSettings:
    """`[code_risks]` from harness.toml; a missing file means the sensor stays inert."""
    target = config.CONFIG_PATH if config_path is None else config_path
    if not target.is_file():
        return ScanSettings()
    return config.load(target).code_risks


def main(
    argv: Sequence[str] | None = None,
    root: Path = REPO_ROOT,
    config_path: Path | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        settings = load_settings(config_path)
    except ConfigError as exc:
        print(f"HARNESS CONFIG INVALID: {exc}")
        return 1
    if not settings.include and not args:
        print("WARNING: no code paths configured (see [code_risks] in harness.toml)")
        return 0
    files = check_secrets.expand_targets(args, root)
    include = () if args else settings.include
    findings = scan_files(files, root, settings.exempt_paths, include)
    if not findings:
        print("CODE RISK SCAN PASSED")
        return 0
    print(f"CODE RISK SCAN FAILED: {len(findings)} finding(s)")
    for finding in findings:
        print(f"  {finding.render()}")
    print("--- fix hint ---")
    print(HINT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
