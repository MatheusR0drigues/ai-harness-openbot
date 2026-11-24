"""Cross-platform entry point for the consolidated OpenBot harness.

  python scripts/harness/cli.py hook <event> --agent antigravity
      (<event>: pre | post | pre-invocation | post-invocation | stop | session-start)
  python scripts/harness/cli.py verify [--fast]
  python scripts/harness/cli.py doctor
  python scripts/harness/cli.py init [--packs ...] [--dry-run] [--force]

Checks Python >= 3.11 BEFORE importing other harness modules so an old
interpreter returns a clear error (Python 3.6-safe syntax intentionally).
PreToolUse hooks fail closed (JSON `{"decision": "deny"}` for OpenBot).
"""

import base64
import contextlib
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple, cast

MIN_VERSION = (3, 11)
USAGE = (
    "usage: cli.py hook <event> --agent antigravity | verify [--fast] | doctor | init [--packs ...]"
)
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(tempfile.gettempdir()) / "ai-harness"
SNAPSHOT_TTL = 30.0
PROTECTED_MODULES = (
    "scripts/harness/cli.py",
    "scripts/harness/hook.py",
    "scripts/harness/guards.py",
    "scripts/harness/payload.py",
    "scripts/harness/config.py",
    "scripts/harness/dialect.py",
    "scripts/harness/check_secrets.py",
    "scripts/harness/check_untrusted.py",
    "scripts/harness/check_structure.py",
    "scripts/harness/check_controls.py",
    "scripts/harness/check_code_risks.py",
    "scripts/harness/verify.py",
    "scripts/harness/check_tamper.py",
)

PROTECTED_SET = frozenset(PROTECTED_MODULES)
SESSION_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def check_version(version: Sequence[int], argv: Sequence[str]) -> Optional[Tuple[int, str]]:
    """Return (exit_code, message) when the interpreter is too old, else None."""
    if tuple(version[:2]) >= MIN_VERSION:
        return None
    found = ".".join(str(part) for part in version[:2])
    message = (
        "harness: Python {}.{}+ is required, found {}. Install it and make `python` "
        "(or `python3`) point to it."
    ).format(MIN_VERSION[0], MIN_VERSION[1], found)
    blocking = list(argv[:2]) == ["hook", "pre"]
    return (2 if blocking else 1), message


def _agent(args: Sequence[str]) -> str:
    if "--agent" in args:
        index = list(args).index("--agent")
        return args[index + 1] if index + 1 < len(args) else ""
    return ""


def block_pre(args: Sequence[str], message: str) -> int:
    """Fail closed on a PreToolUse hook using OpenBot's JSON deny contract."""
    agent = _agent(args)
    if agent in ("antigravity", ""):
        sys.stdout.write('{"decision": "deny", "reason": %s}\n' % json.dumps(message))
        return 0
    sys.stderr.write(message + "\n")
    return 2


def _norm(value: str) -> str:
    return value.lower() if os.name == "nt" else value


NORMALIZED_PROTECTED: FrozenSet[str] = frozenset(_norm(path) for path in PROTECTED_SET)


def _repo_relative(path: str, cwd: str, root: Path) -> Optional[str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(cwd or root) / candidate
    try:
        relative = candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    return _norm(relative)


def protected_paths(paths: Sequence[str], cwd: str, root: Path = REPO_ROOT) -> Tuple[Path, ...]:
    """Return deduplicated existing repository Paths matching PROTECTED_MODULES."""
    found: List[Path] = []
    for raw in paths:
        relative = _repo_relative(raw, cwd, root)
        if relative in NORMALIZED_PROTECTED:
            candidate = root / relative
            if candidate.is_file():
                found.append(candidate)
    return tuple(dict.fromkeys(found))


def _journal_path(root: Path, state_dir: Path, session: str) -> Path:
    repo = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    safe_session = SESSION_SAFE.sub("_", session or "default")[:80]
    return state_dir / "integrity-{}-{}.json".format(repo, safe_session)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def prepare_integrity_snapshot(
    paths: Sequence[str],
    session: str,
    root: Path = REPO_ROOT,
    state_dir: Path = STATE_DIR,
    now: Optional[float] = None,
) -> None:
    """Journal exact pre-write bytes for existing protected modules."""
    targets = protected_paths(paths, str(root), root)
    files: List[Dict[str, str]] = []
    for target in targets:
        data = target.read_bytes()
        files.append(
            {
                "path": target.relative_to(root).as_posix(),
                "sha256": _digest(data),
                "data": base64.b64encode(data).decode("ascii"),
            }
        )
    if not files:
        return
    document: Dict[str, object] = {
        "version": 1,
        "created": time.time() if now is None else now,
        "root": str(root.resolve()),
        "files": files,
    }
    encoded = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(_journal_path(root, state_dir, session), encoded)


def clear_integrity_snapshot(
    session: str, root: Path = REPO_ROOT, state_dir: Path = STATE_DIR
) -> None:
    with contextlib.suppress(FileNotFoundError):
        _journal_path(root, state_dir, session).unlink()


def _failure_paths(exc: BaseException, root: Path) -> FrozenSet[str]:
    found: Set[str] = set()
    filename = getattr(exc, "filename", None)
    if isinstance(filename, str):
        relative = _repo_relative(filename, str(root), root)
        if relative:
            found.add(relative)
    traceback = exc.__traceback__
    while traceback is not None:
        relative = _repo_relative(traceback.tb_frame.f_code.co_filename, str(root), root)
        if relative:
            found.add(relative)
        traceback = traceback.tb_next
    return frozenset(found)


def _validated_files(document: Dict[str, object], root: Path) -> Optional[List[Tuple[Path, bytes]]]:
    raw_files = document.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return None
    files: List[Tuple[Path, bytes]] = []
    for item in cast(List[object], raw_files):
        if not isinstance(item, dict):
            return None
        raw = cast(Dict[str, object], item)
        relative = raw.get("path")
        encoded = raw.get("data")
        expected = raw.get("sha256")
        if not isinstance(relative, str) or _norm(relative) not in NORMALIZED_PROTECTED:
            return None
        if not isinstance(encoded, str) or not isinstance(expected, str):
            return None
        try:
            data = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            return None
        if _digest(data) != expected:
            return None
        target = (root / relative).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            return None
        files.append((target, data))
    return files


def _default_import_check() -> None:
    for relative in PROTECTED_MODULES:
        module = Path(relative).stem
        if module != "cli":
            sys.modules.pop(module, None)
    sys.modules.pop("hook", None)
    importlib.invalidate_caches()
    importlib.import_module("hook")


def recover_integrity_snapshot(
    exc: BaseException,
    root: Path = REPO_ROOT,
    state_dir: Path = STATE_DIR,
    now: Optional[float] = None,
    import_fn: Callable[[], None] = _default_import_check,
) -> Tuple[bool, str]:
    """Restore one recent matching journal after an import-time failure."""
    current_time = time.time() if now is None else now
    failed = _failure_paths(exc, root)
    candidates: List[Tuple[Path, List[Tuple[Path, bytes]]]] = []
    invalid = False
    journals: List[Path] = sorted(state_dir.glob("integrity-*.json")) if state_dir.is_dir() else []
    for journal in journals:
        try:
            loaded: object = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            invalid = True
            continue
        if not isinstance(loaded, dict):
            invalid = True
            continue
        document = cast(Dict[str, object], loaded)
        if document.get("version") != 1:
            invalid = True
            continue
        if document.get("root") != str(root.resolve()):
            continue
        created = document.get("created")
        if not isinstance(created, (int, float)) or not 0 <= current_time - created <= SNAPSHOT_TTL:
            invalid = True
            continue
        files = _validated_files(document, root)
        relative_paths: Set[str] = {
            _norm(path.relative_to(root.resolve()).as_posix()) for path, _data in files or []
        }
        if files is None:
            invalid = True
        elif failed & relative_paths:
            candidates.append((journal, files))
    if invalid or len(candidates) != 1:
        detail = "no recent matching snapshot" if not invalid else "no recent valid snapshot"
        return False, detail + "; recovery remains fail-closed"

    journal, files = candidates[0]
    changed: List[Tuple[Path, bytes]] = [
        (path, data) for path, data in files if not path.is_file() or path.read_bytes() != data
    ]
    if not changed:
        return False, "the matching snapshot is already current; recovery remains fail-closed"
    for target, data in changed:
        _atomic_write(target, data)
    try:
        import_fn()
    except BaseException as import_error:
        return False, "snapshot restored, but the harness still cannot import ({}: {})".format(
            type(import_error).__name__, import_error
        )
    with contextlib.suppress(FileNotFoundError):
        journal.unlink()
    names = ", ".join(path.name for path, _data in changed)
    return True, "restored the last known-good bytes for {}".format(names)


def _crash_response(rest: List[str], exc: BaseException) -> int:
    is_pre = rest[:1] == ["pre"]
    message = (
        "BLOCKED: the harness hook crashed ({}: {}). Fix the harness (run `python "
        "scripts/harness/verify.py`) or ask the human."
    ).format(type(exc).__name__, exc)
    if is_pre:
        return block_pre(rest, message)
    sys.stderr.write("WARNING: " + message[len("BLOCKED: ") :] + "\n")
    return 1


def _recovered_response(rest: List[str], detail: str) -> int:
    message = "Harness integrity recovery {}. The current tool call was not run.".format(detail)
    if rest[:1] == ["pre"]:
        return block_pre(rest, message)
    sys.stderr.write("WARNING: " + message + "\n")
    return 1


def run_hook(rest: List[str]) -> int:
    """Import failures may roll back one journaled edit; runtime failures stay fail-closed."""
    is_pre = rest[:1] == ["pre"]
    try:
        import hook
    except BaseException as exc:  # noqa: BLE001 - import failures are the recovery trigger
        recovered, detail = recover_integrity_snapshot(exc)
        if recovered:
            return _recovered_response(rest, detail)
        return _crash_response(rest, exc)
    try:
        return hook.main(rest)
    except BaseException as exc:  # noqa: BLE001 - a crashing hook must never allow a pre call
        if isinstance(exc, SystemExit) and not is_pre:
            raise
        return _crash_response(rest, exc)


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    problem = check_version((sys.version_info[0], sys.version_info[1]), args)
    if problem is not None:
        if problem[0] == 2:
            return block_pre(args, problem[1])
        sys.stderr.write(problem[1] + "\n")
        return problem[0]
    command, rest = (args[0], args[1:]) if args else ("", [])
    if command == "hook":
        return run_hook(rest)
    if command == "verify":
        import verify

        return verify.main(rest)
    if command == "doctor":
        import doctor

        return doctor.main(rest)
    if command == "init":
        import init

        return init.main(rest)
    sys.stderr.write(USAGE + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
