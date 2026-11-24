"""Project the local OpenBot harness kit into a target repository (stdlib only).

  python scripts/harness/cli.py init [--target PATH]
      [--packs python,node,web-ui,research-guard,data-engineering,bi-pbip] [--dry-run] [--force]

Run it from the ai-harness source repository (or point `--target` at the project). It writes:
  kit-owned      scripts/harness/*.py, harness/core.toml, harness/baseline.json,
                 harness/packs/<pack>/** and the pack rules under .agents/rules/
  project-owned  AGENTS.md, harness.toml, .github/workflows/harness-verify.yml,
                 .agents/rules/{anti-patterns,product,structure,tech}.md,
                 docs/adr/0000-template.md, docs/links.txt (research-guard only)

Project-owned files are created once and never overwritten (not even with `--force`), so a
re-run upgrades the kit without touching what the project wrote. The rule seeds named in
`[init] skip_templates` of the target's harness.toml are reported as skipped and never read,
created or changed. A kit-owned file that differs
from the kit is a conflict: nothing is written unless `--force` is given. The hooks file is
merged: missing kit entries are added and every other entry is kept as is; a kit entry that
differs from the kit (or a retired pack group) is a conflict, and `--force` replaces only the
kit entries. An invalid hooks file stops the run before any write. The whole plan is
computed and validated before the first write, so an invalid request or a conflict writes
nothing; each file is then replaced atomically, but an OS error in the middle of the apply step
can leave earlier files written (re-run after fixing the cause). No CI propagation workflow,
lock file or GitHub App integration is ever generated (ADR-0012).

Exit code: 0 when the plan was applied (or is applicable, with `--dry-run`), 1 otherwise.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import check_tamper
import config
import dialect
from config import ConfigError, Pack

SOURCE_ROOT = config.REPO_ROOT
TEMPLATES = Path("harness") / "templates"
KIT_SCRIPTS = Path("scripts") / "harness"
HOOKS_TEMPLATE = "hooks.antigravity.json"
HARNESS_TEMPLATE = "harness.toml"
ADR_TEMPLATE = "docs/adr/0000-template.md"
PROJECT_TEMPLATES = (
    ("AGENTS.md", "AGENTS.md"),
    (".agents/rules/anti-patterns.md", "anti-patterns.md"),
    (".agents/rules/product.md", "product.md"),
    (".agents/rules/structure.md", "structure.md"),
    (".agents/rules/tech.md", "tech.md"),
    (".github/workflows/harness-verify.yml", "harness-verify.yml"),
)
# Project-owned seeds a pack needs in the target, as (destination, harness/templates/ file).
PACK_PROJECT_TEMPLATES: dict[str, tuple[tuple[str, str], ...]] = {
    "research-guard": (("docs/links.txt", "links.txt"),),
}
SKIPPED_PARTS = frozenset({"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"})
SKIPPED_SUFFIXES = frozenset({".pyc", ".pyo"})
PROJECT_NAME_PLACEHOLDER = re.compile(r'(?m)^name = "projeto-sem-nome"$')
PACKS_PLACEHOLDER = re.compile(r"(?m)^enabled = \[\]$")
USAGE = (
    "usage: cli.py init [--target PATH] "
    "[--packs python,node,web-ui,research-guard,data-engineering,bi-pbip] "
    "[--dry-run] [--force]"
)
WRITE_STATUSES = frozenset({"create", "overwrite", "merge"})
REPORT_STATUSES = ("create", "overwrite", "unchanged", "kept", "conflict", "merge", "skipped")


class InitError(ValueError):
    """The requested projection is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class Options:
    target: Path
    packs: tuple[str, ...] = ()
    dry_run: bool = False
    force: bool = False


@dataclass(frozen=True, slots=True)
class Action:
    path: str  # POSIX path relative to the target
    status: str  # create | unchanged | overwrite | conflict | kept | merge | skipped
    data: bytes


def parse_args(argv: Sequence[str], cwd: Path) -> Options:
    """Manual parsing on purpose: usage errors must exit 1, not argparse's 2."""
    target = cwd
    packs: tuple[str, ...] = ()
    dry_run = force = False
    args = list(argv)
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--target", "--packs"):
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise InitError(f"{arg} needs a value")
            value = args[index + 1]
            index += 2
            if arg == "--target":
                candidate = Path(value)
                target = candidate if candidate.is_absolute() else cwd / candidate
            else:
                names = [name.strip() for name in value.split(",") if name.strip()]
                packs = tuple(dict.fromkeys(names))
            continue
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--force":
            force = True
        else:
            raise InitError(f"unknown argument `{arg}`")
        index += 1
    for name in packs:
        if name not in config.SUPPORTED_PACKS:
            supported = ", ".join(sorted(config.SUPPORTED_PACKS))
            raise InitError(f"unsupported pack `{name}` (supported: {supported})")
    return Options(target=target, packs=packs, dry_run=dry_run, force=force)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def check_target(source: Path, target: Path) -> Path:
    """Resolve the target and refuse the kit itself and the global OpenBot config."""
    resolved = target.resolve()
    if not resolved.is_dir():
        raise InitError(f"target `{target}` is not an existing directory")
    if resolved == source.resolve() or _is_within(resolved, source.resolve()):
        raise InitError(
            "refusing to project the kit onto its own source repository (or a folder inside "
            "it); pass `--target <project repository>`"
        )
    gemini = (Path.home() / ".gemini").resolve()
    if resolved == gemini or _is_within(resolved, gemini):
        raise InitError(
            "refusing to write under `~/.gemini/`: the global OpenBot configuration is "
            "installed by the human (Stage 4), never by `cli.py init`"
        )
    return resolved


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InitError(f"kit file `{path.as_posix()}` cannot be read ({exc})") from exc


def _tree(folder: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIPPED_PARTS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix not in SKIPPED_SUFFIXES:
                yield path


def kit_files(source: Path) -> Iterator[tuple[str, bytes]]:
    """Kit-owned runtime: every module in scripts/harness/ plus the controls baseline."""
    scripts = sorted((source / KIT_SCRIPTS).glob("*.py"))
    if not scripts:
        raise InitError(f"kit source `{source.as_posix()}` has no {KIT_SCRIPTS.as_posix()}/")
    for path in scripts:
        yield (KIT_SCRIPTS / path.name).as_posix(), _read_bytes(path)
    yield config.CORE_RELATIVE.as_posix(), _read_bytes(source / config.CORE_RELATIVE)


def load_packs(source: Path, names: Sequence[str]) -> tuple[Pack, ...]:
    try:
        return tuple(config.load_pack(source, name) for name in names)
    except ConfigError as exc:
        raise InitError(f"kit pack is invalid: {exc}") from exc


def pack_files(source: Path, pack: Pack) -> Iterator[tuple[str, bytes]]:
    for path in _tree(pack.root):
        yield path.relative_to(source).as_posix(), _read_bytes(path)
    for rule in pack.rules:
        yield f".agents/rules/{Path(rule).name}", _read_bytes(pack.root / rule)


def render_hooks(source: Path, packs: Sequence[Pack]) -> bytes:
    """The hooks template verbatim, plus the hooks of every pack declaring them (dialect)."""
    template = _read_bytes(source / TEMPLATES / HOOKS_TEMPLATE)
    with_hooks = [pack for pack in packs if pack.hooks]
    if not with_hooks:
        return template
    try:
        loaded: object = json.loads(template.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InitError(f"{HOOKS_TEMPLATE} template is not valid JSON ({exc})") from exc
    if not isinstance(loaded, dict):
        raise InitError(f"{HOOKS_TEMPLATE} template must be a JSON object")
    data = cast(dict[str, object], loaded)
    try:
        dialect.add_pack_hooks(data, with_hooks)
    except dialect.HooksFileError as exc:
        raise InitError(f"{HOOKS_TEMPLATE} template is invalid ({exc})") from exc
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def project_name(target: Path) -> str:
    name = re.sub(r"[^\w.-]+", "-", target.name).strip("-.")
    return name or "projeto"


def render_harness_toml(source: Path, name: str, packs: Sequence[str]) -> bytes:
    """Fill the project name and the enabled packs into the clean harness.toml template."""
    # A CRLF checkout hides the `$`-anchored placeholders from the regex (ADR-0021).
    text = _read_bytes(source / TEMPLATES / HARNESS_TEMPLATE).decode("utf-8-sig")
    text = text.replace("\r\n", "\n")
    if not PROJECT_NAME_PLACEHOLDER.search(text) or not PACKS_PLACEHOLDER.search(text):
        raise InitError(
            f"{HARNESS_TEMPLATE} template lost its `name`/`enabled` placeholders; restore "
            "harness/templates/harness.toml"
        )
    text = PROJECT_NAME_PLACEHOLDER.sub(f"name = {json.dumps(name)}", text, count=1)
    enabled = ", ".join(json.dumps(pack) for pack in packs)
    text = PACKS_PLACEHOLDER.sub(f"enabled = [{enabled}]", text, count=1)
    try:
        config.parse(tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ConfigError) as exc:
        raise InitError(f"rendered harness.toml is invalid ({exc})") from exc
    return text.encode("utf-8")


def project_files(source: Path, target: Path, packs: Sequence[str]) -> Iterator[tuple[str, bytes]]:
    for destination, template in PROJECT_TEMPLATES:
        yield destination, _read_bytes(source / TEMPLATES / template)
    for pack in packs:
        for destination, template in PACK_PROJECT_TEMPLATES.get(pack, ()):
            yield destination, _read_bytes(source / TEMPLATES / template)
    yield "harness.toml", render_harness_toml(source, project_name(target), packs)
    yield ADR_TEMPLATE, _read_bytes(source / ADR_TEMPLATE)


def skip_names(target: Path) -> frozenset[str]:
    """Rule seeds the target asks to skip: only [init] of its harness.toml is validated (D15)."""
    path = target / "harness.toml"
    if not path.is_file():
        return frozenset()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InitError(f"harness.toml is not valid TOML ({exc})") from exc
    except OSError as exc:
        raise InitError(f"harness.toml cannot be read ({exc})") from exc
    table = data.get("init")
    if table is None:
        return frozenset()
    try:
        return frozenset(config.parse_init(table))
    except ConfigError as exc:
        raise InitError(str(exc)) from exc


def _status(target: Path, relative: str, data: bytes, *, kit_owned: bool, force: bool) -> str:
    path = target / relative
    if not _is_within(path.resolve(), target):
        raise InitError(f"`{relative}` resolves outside the target (symlink?); refusing to write")
    if not path.exists():
        return "create"
    if not path.is_file():
        raise InitError(f"`{relative}` exists in the target but is not a file")
    if path.read_bytes() == data:
        return "unchanged"
    if not kit_owned:
        return "kept"
    return "overwrite" if force else "conflict"


def _kit_multiset(doc: dict[str, object]) -> Counter[bytes]:
    return Counter(check_tamper.canonical_bytes(item) for item in dialect.kit_items(doc))


def hooks_action(target: Path, rendered: bytes, force: bool) -> Action:
    """Merge the kit entries into the hooks file, keeping every third-party entry as is."""
    relative = dialect.HOOKS_REL
    status = _status(target, relative, rendered, kit_owned=True, force=force)
    if status in ("create", "unchanged"):
        return Action(relative, status, rendered)
    current = (target / relative).read_bytes()
    try:
        existing = dialect.load(current)
    except dialect.HooksFileError as exc:
        raise InitError(str(exc)) from exc
    try:
        wanted = dialect.load(rendered)
    except dialect.HooksFileError as exc:
        raise InitError(f"{HOOKS_TEMPLATE} template is invalid ({exc})") from exc
    try:
        found, kit = _kit_multiset(existing), _kit_multiset(wanted)
        if found == kit:
            return Action(relative, "unchanged", current)  # D14: same kit entries, keep formatting
        if not force and not found <= kit:
            return Action(relative, "conflict", rendered)
        merged = dialect.dump(dialect.insert_kit(dialect.strip_kit(existing), wanted))
    except dialect.HooksFileError as exc:
        raise InitError(str(exc)) from exc
    return Action(relative, "merge", merged)


def plan(source: Path, options: Options) -> list[Action]:
    """Every file the projection touches, decided before anything is written."""
    target = check_target(source, options.target)
    names = skip_names(target)
    skipped = {path for path, _ in PROJECT_TEMPLATES if Path(path).stem in names}
    packs = load_packs(source, options.packs)
    entries: dict[str, tuple[bytes, bool]] = {}
    kit: list[tuple[str, bytes]] = [*kit_files(source)]
    for pack in packs:
        kit.extend(pack_files(source, pack))
    if dialect.HOOKS_REL:
        kit.append((dialect.HOOKS_REL, render_hooks(source, packs)))
    # The hooks digest covers only the kit entries, which a merge copies from the rendered file.
    kit.append((check_tamper.BASELINE_REL, check_tamper.render_baseline(dict(kit))))
    for relative, data in kit:
        if relative in entries and entries[relative][0] != data:
            raise InitError(f"two kit sources want to write `{relative}` with different content")
        entries[relative] = (data, True)
    for relative, data in project_files(source, target, options.packs):
        if relative in entries:
            raise InitError(f"`{relative}` is both kit-owned and project-owned")
        entries[relative] = (data, False)
    return [
        Action(relative, "skipped", b"")
        if relative in skipped
        else hooks_action(target, data, options.force)
        if dialect.HOOKS_REL and relative == dialect.HOOKS_REL
        else Action(
            relative, _status(target, relative, data, kit_owned=owned, force=options.force), data
        )
        for relative, (data, owned) in sorted(entries.items())
    ]


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


def apply(target: Path, actions: Sequence[Action]) -> None:
    for action in actions:
        if action.status in WRITE_STATUSES:
            _atomic_write(target / action.path, action.data)


def pack_warnings(target: Path, actions: Sequence[Action], packs: Sequence[str]) -> list[str]:
    """A kept harness.toml is never edited, so say which requested packs it does not enable."""
    kept = any(a.path == "harness.toml" and a.status == "kept" for a in actions)
    if not kept or not packs:
        return []
    try:
        data = tomllib.loads((target / "harness.toml").read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"WARNING: the existing harness.toml could not be read ({exc})"]
    table = data.get("packs")
    raw_enabled = cast(dict[str, object], table).get("enabled") if isinstance(table, dict) else None
    items = cast(list[object], raw_enabled) if isinstance(raw_enabled, list) else []
    enabled = {item for item in items if isinstance(item, str)}
    missing = [pack for pack in packs if pack not in enabled]
    if not missing:
        return []
    return [
        "WARNING: harness.toml was kept (project-owned); add "
        f"{', '.join(json.dumps(p) for p in missing)} to [packs].enabled to activate the gates"
    ]


def render_report(target: Path, actions: Sequence[Action], options: Options) -> str:
    mode = " (dry-run, nothing written)" if options.dry_run else ""
    lines = [f"HARNESS INIT{mode}: {target.as_posix()}"]
    lines.extend(f"  {action.status}: {action.path}" for action in actions)
    counts = {status: 0 for status in REPORT_STATUSES}
    for action in actions:
        counts[action.status] += 1
    lines.append("Summary: " + ", ".join(f"{count} {name}" for name, count in counts.items()))
    lines.extend(pack_warnings(target, actions, options.packs))
    return "\n".join(lines)


NEXT_STEPS = (
    "Next steps: run `python scripts/harness/verify.py` in the target, review "
    "`.github/workflows/harness-verify.yml`, fill `.agents/rules/{product,tech,structure}.md` "
    "with the `harness-setup` skill and review `git diff --stat` before committing."
)


def main(
    argv: Sequence[str] | None = None,
    source: Path = SOURCE_ROOT,
    cwd: Path | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    try:
        options = parse_args(args, Path.cwd() if cwd is None else cwd)
        actions = plan(source, options)
    except InitError as exc:
        print(f"HARNESS INIT FAILED: {exc}")
        print(USAGE)
        return 1
    target = options.target.resolve()
    print(render_report(target, actions, options))
    conflicts = [action.path for action in actions if action.status == "conflict"]
    if conflicts:
        print(
            f"HARNESS INIT FAILED: {len(conflicts)} kit-owned file(s) differ from the kit; nothing "
            "was written. Re-run with `--force` to overwrite them (project-owned files are never "
            "overwritten)."
        )
        return 1
    if options.dry_run:
        return 0
    try:
        apply(target, actions)
    except OSError as exc:
        print(f"HARNESS INIT FAILED: could not write the target ({exc})")
        return 1
    written = sum(1 for action in actions if action.status in WRITE_STATUSES)
    print(f"HARNESS INIT DONE: {written} file(s) written")
    print(NEXT_STEPS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
