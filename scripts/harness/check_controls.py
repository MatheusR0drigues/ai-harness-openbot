"""Stdlib-only sensor that detects weakened harness controls (computational sensor).

"A disabled gate, a removed hook or a widened permission without an ADR is a security finding"
is turned into a gate here. The sensor compares the controls the repository refuses to lose
(`[controls]` in harness/core.toml, extended by harness.toml) with the controls that actually
run: the configured gates and the guards in `guards.ALL`. A core-required gate must stay in the
`core` group and keep `fast = true`, because those sensors run on every turn. Exception markers
are counted and printed even on success, so weakening by piling up allowlist entries stays
visible.

`hook.py` calls `check(cfg, guard_names)` at SessionStart to warn the agent early.

Usage: python scripts/harness/check_controls.py
Exit code: 0 when the baseline holds, 1 otherwise.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import check_code_risks
import check_secrets
import check_tamper
import check_untrusted
import config
import guards
from config import ConfigError, HarnessConfig

REPO_ROOT = config.REPO_ROOT
REQUIRED_GROUP = "core"
MARKERS = (
    check_secrets.ALLOW_MARKER,
    check_untrusted.ALLOW_MARKER,
    check_code_risks.ALLOW_MARKER,
)
HINT = (
    "Restore the control, or justify its removal: an intentional change to a gate, a guard or a "
    "hook needs an ADR in docs/adr/ and the matching update of `[controls]` in harness/core.toml, "
    "in the same change set. Never edit this sensor to make it pass."
)


def check(cfg: HarnessConfig, guard_names: Sequence[str]) -> list[str]:
    problems: list[str] = []
    gates = {gate.name: gate for gate in cfg.gates}
    for name in cfg.controls.required_gates:
        gate = gates.get(name)
        if gate is None:
            problems.append(
                f"gate `{name}` is required by [controls] but is not declared in "
                "harness/core.toml or harness.toml; restore it or record its removal in docs/adr/"
            )
            continue
        # Core-required gates stay in core; a gate a project requires itself may be a stack gate.
        core_required = name in cfg.core_required_gates or not cfg.core_required_gates
        if core_required and gate.group != REQUIRED_GROUP:
            problems.append(
                f"gate `{name}` moved to group `{gate.group}`; a required control stays in "
                f"`{REQUIRED_GROUP}` so that it runs in every project"
            )
        if not gate.fast:
            problems.append(
                f"gate `{name}` lost `fast = true`; a required control runs on every turn, not "
                "only in the full verify"
            )
    available = set(guard_names)
    problems.extend(
        f"guard `{name}` is required by [controls] but is not in guards.ALL; restore it or "
        "record its removal in docs/adr/"
        for name in cfg.controls.required_guards
        if name not in available
    )
    return problems


def count_markers(root: Path, exempt: Sequence[str] = ()) -> dict[str, int]:
    """How many exception markers each file carries, so silent weakening is visible."""
    counts: dict[str, int] = {}
    for path in check_secrets.iter_repo_files(root):
        rel = check_secrets.relative(path, root)
        if not path.is_file() or check_secrets.is_excluded(rel, path.name, exempt):
            continue
        if check_secrets.is_sensitive_file(path.name):
            continue
        text = check_secrets.read_text_file(path)
        if text is None:
            continue
        total = sum(line.count(marker) for line in text.splitlines() for marker in MARKERS)
        if total:
            counts[rel] = total
    return counts


def main(
    argv: Sequence[str] | None = None,
    root: Path = REPO_ROOT,
    config_path: Path | None = None,
) -> int:
    _ = list(sys.argv[1:] if argv is None else argv)
    target = config.CONFIG_PATH if config_path is None else config_path
    try:
        cfg = config.load(target)
    except ConfigError as exc:
        print(f"HARNESS CONFIG INVALID: {exc}")
        return 1
    if not (cfg.controls.required_gates or cfg.controls.required_guards):
        print("WARNING: no controls baseline configured (see [controls] in harness/core.toml)")
        return 0
    problems = check(cfg, [guard.__name__ for guard in (*guards.ALL, *guards.CONFIRM)])
    if check_tamper.should_enforce_in_repo(root):
        problems.extend(check_tamper.verify(root))
    if problems:
        print(f"CONTROLS WEAKENED: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  {problem}")
        print("--- fix hint ---")
        print(HINT)
        return 1
    markers = count_markers(root, cfg.untrusted.exempt_paths)
    gate_count = len(cfg.controls.required_gates)
    guard_count = len(cfg.controls.required_guards)
    print(f"CONTROLS INTACT ({gate_count} gate(s), {guard_count} guard(s))")
    for section, prefix in exempt_scopes(cfg):
        print(f"  exempt path [{section}]: {prefix}")
    for rel, total in sorted(markers.items()):
        print(f"  exception markers: {rel} ({total})")
    return 0


def exempt_scopes(cfg: HarnessConfig) -> list[tuple[str, str]]:
    """Every path a scanner skips: widening an exemption weakens a gate, so it stays visible."""
    sections = (
        ("secrets", cfg.exempt_paths),
        ("untrusted", cfg.untrusted.exempt_paths),
        ("code_risks", cfg.code_risks.exempt_paths),
    )
    return [(name, prefix) for name, paths in sections for prefix in paths]


if __name__ == "__main__":
    sys.exit(main())
