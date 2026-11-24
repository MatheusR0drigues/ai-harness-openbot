"""OpenBot hookless dialect: CI-first contract with no local hooks file (stdlib only).

Implements the same dialect contract as `scripts/harness/dialect.py` (ADR-0022) for the
exported OpenBot target repository, where deterministic validation runs through workflows and CI
gates rather than a local hooks file.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import config

DIALECT = "openbot"
HOOKS_REL = ""
AGENT = "openbot"
CLI = "scripts/harness/cli.py"
RENDERED_EVENTS: dict[str, str] = {}
KNOWN_EVENTS: frozenset[str] = frozenset()
TOOL_EVENTS: frozenset[str] = frozenset()
QUOTES_RULE_APPLIES_TO_THIRD_PARTY = False
IS_HOOKLESS = True


@dataclass(frozen=True)
class HookEntry:
    event: str
    label: str
    raw: object
    owner: Literal["kit", "third"]
    matcher: str | None
    commands: tuple[str, ...]


class HooksFileError(Exception):
    """The parsed payload is not a JSON object; the message never quotes the file content."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """JSON object hook: a repeated key at any depth is an error, not 'last value wins'."""
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise HooksFileError(f"{DIALECT}: duplicate key `{key}`")
        obj[key] = value
    return obj


def load(data: bytes) -> dict[str, object]:
    """Decode UTF-8 JSON bytes into a top-level object with unique keys."""
    try:
        loaded: object = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except UnicodeDecodeError as exc:
        raise HooksFileError(f"{DIALECT}: not valid JSON (not UTF-8 text)") from exc
    except json.JSONDecodeError as exc:
        raise HooksFileError(f"{DIALECT}: not valid JSON ({exc.msg}, line {exc.lineno})") from exc
    except RecursionError as exc:
        raise HooksFileError(f"{DIALECT}: not valid JSON (nesting too deep)") from exc
    if not isinstance(loaded, dict):
        raise HooksFileError(f"{DIALECT}: top level must be a JSON object")
    return cast(dict[str, object], loaded)


def kit_items(doc: dict[str, object]) -> list[dict[str, object]]:
    """Hookless dialect has no kit hook items."""
    del doc
    return []


def strip_kit(doc: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy of `doc` unchanged for hookless targets."""
    return dict(doc)


def insert_kit(stripped: dict[str, object], rendered: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy of `stripped` unchanged for hookless targets."""
    del rendered
    return dict(stripped)


def add_pack_hooks(doc: dict[str, object], packs: Sequence[config.Pack]) -> None:
    """No-op for hookless targets: pack hooks are not written locally."""
    del doc, packs


def dump(doc: dict[str, object]) -> bytes:
    """Serialize `doc` as formatted UTF-8 JSON ending with a newline."""
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def walk(doc: dict[str, object]) -> tuple[list[HookEntry], list[str]]:
    """Hookless dialect defines no local hook entries or shape errors."""
    del doc
    return ([], [])


def top_level_errors(doc: dict[str, object]) -> list[str]:
    """Hookless dialect requires no top-level hooks keys."""
    del doc
    return []


def third_party_errors(entry: HookEntry) -> list[str]:
    """Hookless dialect defines no third-party hook validation errors."""
    del entry
    return []


def guidance_set(path: Path, root: Path) -> tuple[list[Path], list[str]]:
    """OpenBot guidance uses the file itself without external `@` imports."""
    del root
    return ([path], [])
