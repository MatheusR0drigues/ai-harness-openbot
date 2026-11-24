"""Deterministic SHA-256 tamper baseline for critical harness files (stdlib only).

Monitors `harness/core.toml`, `scripts/harness/*.py`, and `HOOKS_REL` when configured using
LF-normalized SHA-256 digests stored in `harness/baseline.json` (ADR-0014). The hooks file is
digested over its canonical kit entries only, so third-party hooks never look like tampering.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import config
import dialect

REPO_ROOT = config.REPO_ROOT
BASELINE_REL = "harness/baseline.json"
HOOKS_REL = dialect.HOOKS_REL
CORE_REL = "harness/core.toml"
SCRIPTS_DIR_REL = "scripts/harness"
BASELINE_VERSION = 2
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
USAGE = "Usage: python scripts/harness/check_tamper.py [--update]"


def digest_bytes(data: bytes) -> str:
    """LF-normalized SHA-256 hex digest so CRLF/LF checkouts compare identically."""
    normalized = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def canonical_bytes(value: object) -> bytes:
    """Key-sorted, compact, ASCII-only JSON: independent of key order and whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def hooks_digest(data: bytes) -> str | None:
    """SHA-256 of the canonical kit entries of the hooks file; None when it is not valid."""
    try:
        doc = dialect.load(data)
    except dialect.HooksFileError:
        return None
    items = sorted(dialect.kit_items(doc), key=canonical_bytes)
    return hashlib.sha256(canonical_bytes(items)).hexdigest()


def digest_for(rel: str, data: bytes) -> str | None:
    if HOOKS_REL and rel == HOOKS_REL:
        return hooks_digest(data)
    return digest_bytes(data)


def is_monitored_path(rel: str) -> bool:
    if rel == CORE_REL or (HOOKS_REL and rel == HOOKS_REL):
        return True
    prefix = f"{SCRIPTS_DIR_REL}/"
    if not (rel.startswith(prefix) and rel.endswith(".py")):
        return False
    parts = rel[len(prefix) :].split("/")
    return all(part and part not in (".", "..", "__pycache__") for part in parts)


def collect_blobs(root: Path = REPO_ROOT) -> dict[str, bytes]:
    """Read every monitored file present on disk under `root`."""
    blobs: dict[str, bytes] = {}
    root_resolved = root.resolve()
    candidates: list[tuple[str, Path]] = [(CORE_REL, root / CORE_REL)]
    if HOOKS_REL:
        candidates.insert(0, (HOOKS_REL, root / HOOKS_REL))
    scripts_dir = root / SCRIPTS_DIR_REL
    if scripts_dir.is_dir():
        for py_file in sorted(scripts_dir.rglob("*.py"), key=lambda p: p.as_posix()):
            try:
                resolved = py_file.resolve()
                rel = resolved.relative_to(root_resolved).as_posix()
            except (OSError, ValueError):
                continue
            if "__pycache__" in rel.split("/"):
                continue
            candidates.append((rel, resolved))

    for rel, path in candidates:
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(root_resolved)
            blobs[rel] = path.read_bytes()
        except (OSError, ValueError):
            continue
    return blobs


def build_baseline(blobs: Mapping[str, bytes]) -> dict[str, object]:
    files: dict[str, str] = {}
    for rel, data in sorted(blobs.items()):
        if not is_monitored_path(rel):
            continue
        digest = digest_for(rel, data)
        if digest is None:
            raise ValueError(f"{rel} is not valid JSON")
        files[rel] = digest
    return {"version": BASELINE_VERSION, "files": files}


def render_baseline(blobs: Mapping[str, bytes]) -> bytes:
    return (json.dumps(build_baseline(blobs), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_baseline(root: Path = REPO_ROOT, baseline_path: Path | None = None) -> tuple[Path, int]:
    """Compute digests from monitored files on disk and write `harness/baseline.json`."""
    blobs = collect_blobs(root)
    required = (HOOKS_REL, CORE_REL) if HOOKS_REL else (CORE_REL,)
    missing = [rel for rel in required if rel not in blobs]
    if missing:
        raise ValueError(f"cannot generate baseline without {', '.join(missing)}")
    if not any(rel.startswith(f"{SCRIPTS_DIR_REL}/") for rel in blobs):
        raise ValueError(f"cannot generate baseline without {SCRIPTS_DIR_REL}/*.py")
    target = (root / BASELINE_REL) if baseline_path is None else baseline_path
    payload = build_baseline(blobs)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(target, data)
    files = cast(dict[str, str], payload["files"])
    return target, len(files)


def should_enforce_in_repo(root: Path = REPO_ROOT) -> bool:
    """True when `root` hosts an installed harness (or already has `harness/baseline.json`)."""
    return (
        (root / BASELINE_REL).exists()
        or bool(HOOKS_REL and (root / HOOKS_REL).exists())
        or (root / SCRIPTS_DIR_REL).is_dir()
    )


def _load_expected_files(target: Path) -> tuple[dict[str, str] | None, str | None]:
    if not target.is_file():
        return None, f"missing tamper baseline (`{BASELINE_REL}`)"
    try:
        loaded: object = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid tamper baseline (`{BASELINE_REL}`: {exc})"
    if not isinstance(loaded, dict):
        return None, f"invalid tamper baseline (`{BASELINE_REL}`: expected JSON object)"
    raw = cast(dict[str, object], loaded)
    if raw.get("version") == 1:
        return None, (
            f"invalid tamper baseline (`{BASELINE_REL}`: version 1 predates kit-entry digests; "
            "ask the human to run `python scripts/harness/cli.py init --force` or "
            "`check_tamper.py --update`)"
        )
    if raw.get("version") != BASELINE_VERSION:
        return None, f"invalid tamper baseline (`{BASELINE_REL}`: unsupported version)"
    raw_files = raw.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        return None, f"invalid tamper baseline (`{BASELINE_REL}`: missing `files` map)"
    expected: dict[str, str] = {}
    for key, val in cast(dict[object, object], raw_files).items():
        if (
            not isinstance(key, str)
            or not is_monitored_path(key)
            or not isinstance(val, str)
            or not _SHA256_HEX_RE.match(val)
        ):
            return None, f"invalid tamper baseline entry (`{key}`)"
        expected[key] = val
    return expected, None


def verify(root: Path = REPO_ROOT, baseline_path: Path | None = None) -> list[str]:
    """Return tamper findings for `root`; an empty list means all monitored files match."""
    target = (root / BASELINE_REL) if baseline_path is None else baseline_path
    expected, load_error = _load_expected_files(target)
    if load_error is not None or expected is None:
        return [load_error or f"invalid tamper baseline (`{BASELINE_REL}`)"]

    blobs = collect_blobs(root)
    findings: list[str] = []
    for rel, expected_sha in sorted(expected.items()):
        if rel not in blobs:
            findings.append(f"missing protected harness file: {rel}")
        elif digest_for(rel, blobs[rel]) != expected_sha:
            findings.append(f"modified protected harness file: {rel}")
    for rel in sorted(blobs):
        if rel not in expected:
            findings.append(f"unexpected harness file added: {rel}")
    return findings


def notice(root: Path = REPO_ROOT, baseline_path: Path | None = None) -> str | None:
    """Human-readable warning when tamper findings are detected, else None."""
    findings = verify(root, baseline_path)
    if not findings:
        return None
    details = "; ".join(findings)
    return (
        f"Harness tamper baseline violation ({details}). Restore the protected file(s) or ask "
        "the human to refresh `harness/baseline.json` "
        "(`python scripts/harness/check_tamper.py --update`)."
    )


def main(argv: Sequence[str] | None = None, root: Path = REPO_ROOT) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if args == ["--update"]:
        try:
            target, count = write_baseline(root)
        except (OSError, ValueError) as exc:
            print(f"TAMPER BASELINE UPDATE FAILED: {exc}")
            return 1
        print(f"TAMPER BASELINE UPDATED: {target.as_posix()} ({count} file(s))")
        return 0
    if args:
        print(USAGE)
        return 2

    findings = verify(root)
    if findings:
        print("TAMPER CHECK FAILED:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    expected, _ = _load_expected_files(root / BASELINE_REL)
    count = len(expected) if expected else 0
    print(f"TAMPER CHECK PASSED ({count} file(s) verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
