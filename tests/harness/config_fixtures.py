"""Shared test helpers: a harness.toml always loads with its harness/core.toml and packs."""

from pathlib import Path


def write_core(root: Path, text: str = "") -> Path:
    """Write `root/harness/core.toml` (empty = no core gates and no controls baseline)."""
    path = root / "harness" / "core.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_pack(root: Path, name: str, body: str = "") -> Path:
    """Write a minimal `root/harness/packs/<name>/pack.toml` followed by `body`."""
    path = root / "harness" / "packs" / name / "pack.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f'[pack]\nname = "{name}"\ndescription = "Pacote de teste {name}."\n'
    path.write_text(header + body, encoding="utf-8")
    return path
