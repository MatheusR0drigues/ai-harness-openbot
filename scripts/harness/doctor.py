"""Explicit, stdlib-only diagnostics for the harness environment (ADR-0007).

Reports, without changing anything:
- the Python interpreter (>= 3.11 required);
- harness/core.toml + harness.toml load (schema, enabled packs);
- hooks mode is verified via dialect (`hookless OpenBot mode (CI-first)` when `HOOKS_REL` is empty);
- every enabled pack is installed under harness/packs/<name>/pack.toml;
- each gate's top-level executable resolves on PATH (never executed);
- for `harness` group gates run through `uv run`: uv, .venv and bounded `--version` probes of the
  allowlisted tools ruff, pyright and pytest (`uv run --no-sync`).

Usage: python scripts/harness/doctor.py
Exit code: 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import json
import shutil
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import check_structure
import config
import dialect
import verify
from config import ConfigError, HarnessConfig
from verify import RunResult

REPO_ROOT = config.REPO_ROOT
MIN_PYTHON = (3, 11)
PROBE_TIMEOUT = 10
HARNESS_TOOLS = frozenset({"ruff", "pyright", "pytest"})
HOOKS_FILE = dialect.HOOKS_REL
STALE_SHIM = verify.STALE_SHIM

Runner = Callable[[Sequence[str], int], RunResult]
Which = Callable[[str], str | None]


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "no output")[:240]


def check_python(version: Sequence[int], executable: str) -> Check:
    supported = tuple(version[:2]) >= MIN_PYTHON
    return Check(
        "python",
        supported,
        f"{version[0]}.{version[1]} at {executable}",
        "" if supported else "Install Python 3.11+ and run the doctor with that interpreter.",
    )


def load_config(target: Path) -> tuple[HarnessConfig | None, Check]:
    try:
        cfg = config.load(target)
    except ConfigError as exc:
        return None, Check(
            "config",
            False,
            str(exc),
            "Fix harness.toml / harness/core.toml (schema in scripts/harness/config.py).",
        )
    packs = ", ".join(cfg.packs) or "none"
    detail = f"harness/core.toml + harness.toml loaded ({len(cfg.gates)} gate(s), packs: {packs})"
    return cfg, Check("config", True, detail)


def check_hooks_file(root: Path) -> Check:
    if not HOOKS_FILE:
        return Check("hooks", True, "hookless OpenBot mode (CI-first)")
    path = root / HOOKS_FILE
    hint = (
        "Restore hooks file (`python scripts/harness/cli.py init`), then run "
        "`python scripts/harness/check_structure.py`."
    )
    if not path.is_file():
        return Check("hooks", False, f"{HOOKS_FILE} is missing", hint)
    try:
        data: object = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return Check("hooks", False, f"{HOOKS_FILE} does not parse: {exc}", hint)
    if not isinstance(data, dict):
        return Check("hooks", False, f"{HOOKS_FILE} must be a JSON object", hint)
    groups = len(cast(dict[str, object], data))
    return Check("hooks", True, f"{HOOKS_FILE} parses ({groups} group(s))")


def check_local_agents(root: Path) -> Check:
    collisions = check_structure.local_agent_collisions(root)
    if not collisions:
        return Check(
            "local-agents",
            True,
            "no undeclared collisions with global or reserved agents",
        )
    detail = f"{len(collisions)} collision(s): {'; '.join(collisions)}"
    hint = (
        "Declare allowed overrides in harness.toml [agents].allow_override "
        "or rename colliding local agents."
    )
    return Check("local-agents", False, detail, hint)


def enabled_packs(target: Path) -> tuple[str, ...]:
    """`[packs].enabled` read leniently, so pack checks still run when the full config fails."""
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ()
    packs = data.get("packs")
    enabled = cast(dict[str, object], packs).get("enabled") if isinstance(packs, dict) else None
    if not isinstance(enabled, list):
        return ()
    return tuple(item for item in cast(list[object], enabled) if isinstance(item, str))


def check_packs(root: Path, packs: Sequence[str]) -> list[Check]:
    checks: list[Check] = []
    for name in packs:
        manifest = root / config.PACKS_RELATIVE / name / config.PACK_FILE
        installed = manifest.is_file()
        checks.append(
            Check(
                f"pack:{name}",
                installed,
                manifest.relative_to(root).as_posix()
                if installed
                else f"enabled in harness.toml but harness/packs/{name}/pack.toml is missing",
                "" if installed else f"Run `python scripts/harness/cli.py init --packs {name}`.",
            )
        )
    return checks


def _probe(name: str, command: Sequence[str], runner: Runner) -> Check:
    result = runner(command, PROBE_TIMEOUT)
    if result.returncode == 0:
        return Check(name, True, _first_line(result.output))
    if STALE_SHIM in result.output.lower():
        return Check(
            name,
            False,
            "stale virtual-environment shim (failed to canonicalize script path)",
            "Run `uv sync --reinstall`, then run the doctor again.",
        )
    return Check(
        name,
        False,
        f"probe failed with exit code {result.returncode}: {_first_line(result.output)}",
        "Repair or reinstall the tool, then run the doctor again.",
    )


def _uv_tool(gate: config.Gate) -> str | None:
    command = gate.command
    if gate.group != "harness" or len(command) < 3 or command[:2] != ("uv", "run"):
        return None
    tool = next((part for part in command[2:] if not part.startswith("-")), "")
    return tool if tool in HARNESS_TOOLS else None


def diagnose(
    cfg: HarnessConfig,
    *,
    runner: Runner = verify.subprocess_runner,
    which: Which = shutil.which,
    root: Path = REPO_ROOT,
) -> tuple[Check, ...]:
    """Gate executables on PATH, plus uv/.venv/tool probes for `harness` gates run via uv."""
    checks: list[Check] = []
    executables = sorted({gate.command[0] for gate in cfg.gates if gate.command[0] != "python"})
    resolved = {name: which(name) for name in executables}
    for name in executables:
        path = resolved[name]
        checks.append(
            Check(
                f"executable:{name}",
                path is not None,
                path or "not found on PATH",
                f"Install `{name}` or fix the gate command." if path is None else "",
            )
        )

    tools = sorted({tool for gate in cfg.gates if (tool := _uv_tool(gate))})
    if not tools or resolved.get("uv") is None:
        return tuple(checks)

    checks.append(_probe("uv", ("uv", "--version"), runner))
    venv_exists = (root / ".venv").is_dir()
    checks.append(
        Check(
            "venv",
            venv_exists,
            str(root / ".venv") if venv_exists else ".venv is missing",
            "" if venv_exists else "Run `uv sync` to create the harness development environment.",
        )
    )
    if venv_exists:
        for tool in tools:
            checks.append(_probe(tool, ("uv", "run", "--no-sync", tool, "--version"), runner))
    return tuple(checks)


def run_checks(
    *,
    runner: Runner = verify.subprocess_runner,
    which: Which = shutil.which,
    root: Path = REPO_ROOT,
    config_path: Path | None = None,
    version: Sequence[int] = (sys.version_info.major, sys.version_info.minor),
    executable: str = sys.executable,
) -> tuple[Check, ...]:
    target = root / "harness.toml" if config_path is None else config_path
    cfg, config_check = load_config(target)
    checks = [
        check_python(version, executable),
        config_check,
        check_hooks_file(root),
        check_local_agents(root),
    ]
    checks += check_packs(root, cfg.packs if cfg is not None else enabled_packs(target))
    if cfg is not None:
        checks += diagnose(cfg, runner=runner, which=which, root=root)
    return tuple(checks)


def render(checks: Sequence[Check]) -> str:
    lines: list[str] = []
    for check in checks:
        lines.append(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
        if check.hint:
            lines.append(f"  Fix: {check.hint}")
    lines.append("DOCTOR PASSED" if all(check.ok for check in checks) else "DOCTOR FAILED")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    runner: Runner = verify.subprocess_runner,
    which: Which = shutil.which,
    root: Path = REPO_ROOT,
    config_path: Path | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("usage: doctor.py")
        return 1
    checks = run_checks(runner=runner, which=which, root=root, config_path=config_path)
    print(render(checks))
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
