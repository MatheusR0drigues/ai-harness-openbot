"""Loader and schema validation for harness/core.toml + harness.toml (stdlib only).

harness/core.toml (harness-owned) holds the core gates and the controls baseline;
harness.toml (project-owned) holds project settings, opt-in packs and custom gates
(ADR-0011). Harness Python code remains stack-agnostic: projects configure data here.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "harness.toml"
CORE_RELATIVE = Path("harness") / "core.toml"
CORE_KEYS = frozenset({"controls", "gates"})
DEFAULT_TIMEOUT = 600
GROUPS = ("core", "harness", "stack")
SUPPORTED_PACKS = frozenset(
    {"python", "node", "web-ui", "research-guard", "data-engineering", "bi-pbip"}
)
GLOBAL_AGENT_NAMES = frozenset(
    {
        "researcher",
        "planner",
        "implementer",
        "code-reviewer",
        "security-auditor",
        "databricks-architect",
        "claude-architect",
        "github-architect",
        "powerbi-architect",
    }
)

TOP_LEVEL_KEYS = frozenset(
    {
        "project",
        "packs",
        "secrets",
        "untrusted",
        "code_risks",
        "comments",
        "controls",
        "gates",
        "agents",
        "init",
    }
)
PROJECT_KEYS = frozenset({"name"})
PACKS_KEYS = frozenset({"enabled"})
AGENTS_KEYS = frozenset({"allow_override"})
INIT_KEYS = frozenset({"skip_templates"})
INIT_TEMPLATE_NAMES = ("anti-patterns", "product", "structure", "tech")
SECRETS_KEYS = frozenset({"extra_patterns", "exempt_paths", "safe_values"})
SCAN_KEYS = frozenset({"include", "exempt_paths"})
CONTROLS_KEYS = frozenset({"required_gates", "required_guards"})
PATTERN_KEYS = frozenset({"name", "regex"})
GATE_KEYS = frozenset({"name", "command", "hint", "fast", "group", "timeout", "requires_glob"})
GATE_REQUIRED = ("name", "command", "hint", "group")
PACKS_RELATIVE = Path("harness") / "packs"
PACK_FILE = "pack.toml"
PACK_TOP_KEYS = frozenset({"pack", "gates", "hooks"})
PACK_META_KEYS = frozenset({"name", "description", "rules"})
PACK_HOOK_KEYS = frozenset({"event", "command", "timeout", "matcher"})
PACK_HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "SessionStart",
    "PreInvocation",
    "PostInvocation",
    "Stop",
)
DEFAULT_HOOK_TIMEOUT = 30


class ConfigError(ValueError):
    """harness.toml or harness/core.toml is missing or does not match the schema."""


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    command: tuple[str, ...]
    hint: str
    group: str
    fast: bool = False
    timeout: int = DEFAULT_TIMEOUT
    requires_glob: str = ""


@dataclass(frozen=True, slots=True)
class SecretPattern:
    name: str
    regex: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class ScanSettings:
    """Which paths a file scanner inspects. Empty `include` means the whole repository."""

    include: tuple[str, ...] = ()
    exempt_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ControlsBaseline:
    """The gates and guards the repository refuses to lose."""

    required_gates: tuple[str, ...] = ()
    required_guards: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    project_name: str
    exempt_paths: tuple[str, ...]
    extra_patterns: tuple[SecretPattern, ...]
    gates: tuple[Gate, ...]
    packs: tuple[str, ...] = ()
    safe_values: tuple[str, ...] = ()
    untrusted: ScanSettings = ScanSettings()
    code_risks: ScanSettings = ScanSettings()
    comments: ScanSettings = ScanSettings()
    controls: ControlsBaseline = ControlsBaseline()
    core_required_gates: tuple[str, ...] = ()
    agents_allow_override: tuple[str, ...] = ()
    init_skip_templates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackHook:
    """One extra OpenBot hook handler a pack asks `cli.py init` to register."""

    event: str
    command: str
    timeout: int = DEFAULT_HOOK_TIMEOUT
    matcher: str = ""


@dataclass(frozen=True, slots=True)
class Pack:
    """An opt-in stack pack read from harness/packs/<name>/pack.toml."""

    name: str
    description: str
    root: Path
    rules: tuple[str, ...] = ()
    gates: tuple[Gate, ...] = ()
    hooks: tuple[PackHook, ...] = ()


def _table(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a table")
    return cast(dict[str, object], value)


def _check_keys(table: dict[str, object], allowed: frozenset[str], where: str) -> None:
    for key in table:
        if key not in allowed:
            raise ConfigError(
                f"{where}: unknown key `{key}` (allowed: {', '.join(sorted(allowed))})"
            )


def _str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} must be a non-empty string")
    return value


def _str_list(value: object, where: str, *, allow_empty: bool) -> tuple[str, ...]:
    items = cast(list[object], value) if isinstance(value, list) else None
    if items is None or not all(isinstance(i, str) and i for i in items):
        raise ConfigError(f"{where} must be a non-empty list of strings")
    if not items and not allow_empty:
        raise ConfigError(f"{where} must be a non-empty list of strings")
    return tuple(cast(list[str], items))


def _parse_gate(raw: object, index: int) -> Gate:
    table = _table(raw, f"gates[{index}]")
    label = f"gates[{index}]" + (
        f" ({table['name']})" if isinstance(table.get("name"), str) else ""
    )
    _check_keys(table, GATE_KEYS, label)
    for key in GATE_REQUIRED:
        if key not in table:
            raise ConfigError(f"{label}: missing required key `{key}`")
    group = _str(table["group"], f"{label}.group")
    if group not in GROUPS:
        raise ConfigError(f"{label}: group must be one of {', '.join(GROUPS)}; got `{group}`")
    fast = table.get("fast", False)
    if not isinstance(fast, bool):
        raise ConfigError(f"{label}.fast must be a boolean")
    timeout = table.get("timeout", DEFAULT_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError(f"{label}.timeout must be a positive integer (seconds)")
    requires_glob = ""
    if "requires_glob" in table:
        requires_glob = _str(table["requires_glob"], f"{label}.requires_glob")
    return Gate(
        name=_str(table["name"], f"{label}.name"),
        command=_str_list(table["command"], f"{label}.command", allow_empty=False),
        hint=_str(table["hint"], f"{label}.hint"),
        group=group,
        fast=fast,
        timeout=timeout,
        requires_glob=requires_glob,
    )


def _parse_patterns(value: object) -> tuple[SecretPattern, ...]:
    if not isinstance(value, list):
        raise ConfigError("secrets.extra_patterns must be a list of {name, regex} tables")
    patterns: list[SecretPattern] = []
    for index, raw in enumerate(cast(list[object], value)):
        where = f"secrets.extra_patterns[{index}]"
        table = _table(raw, where)
        _check_keys(table, PATTERN_KEYS, where)
        name = _str(table.get("name"), f"{where}.name")
        source = _str(table.get("regex"), f"{where}.regex")
        try:
            patterns.append(SecretPattern(name, re.compile(source)))
        except re.error as exc:
            raise ConfigError(f"{where}: invalid regex `{source}`: {exc}") from exc
    return tuple(patterns)


def _parse_packs(value: object) -> tuple[str, ...]:
    table = _table(value, "packs")
    _check_keys(table, PACKS_KEYS, "packs")
    enabled = _str_list(table.get("enabled", []), "packs.enabled", allow_empty=True)
    for pack in enabled:
        if pack not in SUPPORTED_PACKS:
            raise ConfigError(
                f"packs.enabled: unsupported pack `{pack}` "
                f"(supported: {', '.join(sorted(SUPPORTED_PACKS))})"
            )
    return tuple(dict.fromkeys(enabled))


def _parse_scan(value: object, where: str) -> ScanSettings:
    table = _table(value, where)
    _check_keys(table, SCAN_KEYS, where)
    return ScanSettings(
        include=_str_list(table.get("include", []), f"{where}.include", allow_empty=True),
        exempt_paths=_str_list(
            table.get("exempt_paths", []), f"{where}.exempt_paths", allow_empty=True
        ),
    )


def _parse_controls(value: object, where: str) -> ControlsBaseline:
    table = _table(value, where)
    _check_keys(table, CONTROLS_KEYS, where)
    return ControlsBaseline(
        required_gates=_str_list(
            table.get("required_gates", []), f"{where}.required_gates", allow_empty=True
        ),
        required_guards=_str_list(
            table.get("required_guards", []), f"{where}.required_guards", allow_empty=True
        ),
    )


def _parse_agents(value: object) -> tuple[str, ...]:
    table = _table(value, "agents")
    _check_keys(table, AGENTS_KEYS, "agents")
    overrides = _str_list(
        table.get("allow_override", []), "agents.allow_override", allow_empty=True
    )
    for name in overrides:
        if name not in GLOBAL_AGENT_NAMES:
            raise ConfigError(
                f"agents.allow_override: unknown agent `{name}` "
                f"(allowed: {', '.join(sorted(GLOBAL_AGENT_NAMES))})"
            )
    return tuple(dict.fromkeys(overrides))


def parse_init(table: object) -> tuple[str, ...]:
    """Validate the [init] table; return the rule seeds `cli.py init` must skip."""
    init = _table(table, "init")
    _check_keys(init, INIT_KEYS, "init")
    raw = init.get("skip_templates", [])
    items = cast(list[object], raw) if isinstance(raw, list) else None
    if items is None or not all(isinstance(item, str) for item in items):
        raise ConfigError("[init] skip_templates must be a list of strings")
    names = cast(list[str], items)
    for name in names:
        if name not in INIT_TEMPLATE_NAMES:
            raise ConfigError(
                f"[init] skip_templates: unknown template `{name}` "
                f"(allowed: {', '.join(INIT_TEMPLATE_NAMES)})"
            )
    return tuple(dict.fromkeys(names))


def agent_overrides(root: Path) -> tuple[str, ...]:
    """Read [agents].allow_override leniently from harness.toml under `root`."""
    target = root / "harness.toml"
    try:
        data = tomllib.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ()
    agents = data.get("agents")
    if not isinstance(agents, dict):
        return ()
    raw = cast(dict[str, object], agents).get("allow_override")
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in cast(list[object], raw) if isinstance(item, str))


def parse(data: dict[str, object]) -> HarnessConfig:
    _check_keys(data, TOP_LEVEL_KEYS, "harness.toml")
    project = _table(data.get("project", {}), "project")
    _check_keys(project, PROJECT_KEYS, "project")
    secrets = _table(data.get("secrets", {}), "secrets")
    _check_keys(secrets, SECRETS_KEYS, "secrets")
    agents_table = data.get("agents")
    agents_allow_override = _parse_agents(agents_table) if agents_table is not None else ()
    init_table = data.get("init")
    init_skip_templates = parse_init(init_table) if init_table is not None else ()
    raw_gates = data.get("gates", [])
    if not isinstance(raw_gates, list):
        raise ConfigError("gates must be an array of tables ([[gates]])")
    gates = tuple(_parse_gate(raw, i) for i, raw in enumerate(cast(list[object], raw_gates)))
    seen: set[str] = set()
    for gate in gates:
        if gate.name in seen:
            raise ConfigError(f"duplicate gate name `{gate.name}`")
        seen.add(gate.name)
    return HarnessConfig(
        project_name=_str(project.get("name", "unnamed-project"), "project.name"),
        packs=_parse_packs(data.get("packs", {})),
        exempt_paths=_str_list(
            secrets.get("exempt_paths", []), "secrets.exempt_paths", allow_empty=True
        ),
        safe_values=_str_list(
            secrets.get("safe_values", []), "secrets.safe_values", allow_empty=True
        ),
        extra_patterns=_parse_patterns(secrets.get("extra_patterns", [])),
        gates=gates,
        untrusted=_parse_scan(data.get("untrusted", {}), "untrusted"),
        code_risks=_parse_scan(data.get("code_risks", {}), "code_risks"),
        comments=_parse_scan(data.get("comments", {}), "comments"),
        controls=_parse_controls(data.get("controls", {}), "controls"),
        agents_allow_override=agents_allow_override,
        init_skip_templates=init_skip_templates,
    )


def _read(target: Path) -> dict[str, object]:
    try:
        # utf-8-sig removes BOM potentially added by Windows editors or PowerShell.
        return tomllib.loads(target.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{target.as_posix()} is not valid TOML: {exc}") from exc


def _union(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    return first + tuple(name for name in second if name not in first)


def merge(core: HarnessConfig, project: HarnessConfig) -> HarnessConfig:
    """Core gates first; a project may add gates and controls, never shadow or drop core ones."""
    core_names = {gate.name for gate in core.gates}
    for gate in core.gates:
        if gate.group != "core":
            raise ConfigError(f"harness/core.toml: gate `{gate.name}` must be in group `core`")
    for gate in project.gates:
        if gate.name in core_names:
            raise ConfigError(
                f"harness.toml: gate `{gate.name}` is a core gate defined in harness/core.toml; "
                "a project cannot redefine it (pick another name)"
            )
        if gate.group == "core":
            raise ConfigError(
                f"harness.toml: gate `{gate.name}` uses group `core`, which only "
                "harness/core.toml may declare; use `stack` (or `harness`)"
            )
    controls = ControlsBaseline(
        required_gates=_union(core.controls.required_gates, project.controls.required_gates),
        required_guards=_union(core.controls.required_guards, project.controls.required_guards),
    )
    return replace(
        project,
        gates=core.gates + project.gates,
        controls=controls,
        core_required_gates=core.controls.required_gates,
    )


def _parse_pack_hook(raw: object, where: str) -> PackHook:
    table = _table(raw, where)
    _check_keys(table, PACK_HOOK_KEYS, where)
    event = _str(table.get("event"), f"{where}.event")
    if event not in PACK_HOOK_EVENTS:
        raise ConfigError(f"{where}.event must be one of {', '.join(PACK_HOOK_EVENTS)}")
    command = _str(table.get("command"), f"{where}.command")
    if '"' in command:
        raise ConfigError(
            f"{where}.command must not contain double quotes (OpenBot escapes them, ADR-0004)"
        )
    timeout = table.get("timeout", DEFAULT_HOOK_TIMEOUT)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ConfigError(f"{where}.timeout must be a positive integer (seconds)")
    matcher = table.get("matcher", "")
    if not isinstance(matcher, str):
        raise ConfigError(f"{where}.matcher must be a string")
    return PackHook(event=event, command=command, timeout=timeout, matcher=matcher)


def load_pack(root: Path, name: str) -> Pack:
    """Read harness/packs/<name>/pack.toml under `root`; every pack gate must be `stack`."""
    if name not in SUPPORTED_PACKS:
        raise ConfigError(
            f"unsupported pack `{name}` (supported: {', '.join(sorted(SUPPORTED_PACKS))})"
        )
    pack_dir = root / PACKS_RELATIVE / name
    manifest = pack_dir / PACK_FILE
    where = f"harness/packs/{name}/{PACK_FILE}"
    if not manifest.is_file():
        raise ConfigError(
            f"{where} does not exist; the pack `{name}` is enabled in harness.toml "
            "but not installed (run `python scripts/harness/cli.py init --packs "
            f"{name}`)"
        )
    data = _read(manifest)
    _check_keys(data, PACK_TOP_KEYS, where)
    meta = _table(data.get("pack", {}), f"{where} [pack]")
    _check_keys(meta, PACK_META_KEYS, f"{where} [pack]")
    declared = _str(meta.get("name"), f"{where} [pack].name")
    if declared != name:
        raise ConfigError(f"{where}: [pack].name `{declared}` must equal the folder `{name}`")
    description = _str(meta.get("description"), f"{where} [pack].description")
    rules = _str_list(meta.get("rules", []), f"{where} [pack].rules", allow_empty=True)
    for rule in rules:
        rule_path = (pack_dir / rule).resolve()
        try:
            rule_path.relative_to(pack_dir.resolve())
        except ValueError as exc:
            raise ConfigError(f"{where}: rule `{rule}` escapes the pack folder") from exc
        if not rule_path.is_file():
            raise ConfigError(f"{where}: rule `{rule}` does not exist")
    gates_cfg = parse({"gates": data.get("gates", [])})
    for gate in gates_cfg.gates:
        if gate.group != "stack":
            raise ConfigError(f'{where}: gate `{gate.name}` must use group = "stack"')
    raw_hooks = data.get("hooks", [])
    if not isinstance(raw_hooks, list):
        raise ConfigError(f"{where}: hooks must be an array of tables ([[hooks]])")
    hooks = tuple(
        _parse_pack_hook(raw, f"{where} hooks[{index}]")
        for index, raw in enumerate(cast(list[object], raw_hooks))
    )
    return Pack(
        name=name,
        description=description,
        root=pack_dir,
        rules=rules,
        gates=gates_cfg.gates,
        hooks=hooks,
    )


def merge_packs(cfg: HarnessConfig, packs: tuple[Pack, ...]) -> HarnessConfig:
    """Insert enabled pack gates after the core gates; names must stay unique."""
    if not packs:
        return cfg
    core_count = sum(1 for gate in cfg.gates if gate.group == "core")
    core, project = cfg.gates[:core_count], cfg.gates[core_count:]
    seen = {gate.name: "harness/core.toml or harness.toml" for gate in cfg.gates}
    pack_gates: list[Gate] = []
    for pack in packs:
        for gate in pack.gates:
            if gate.name in seen:
                raise ConfigError(
                    f"pack `{pack.name}`: gate `{gate.name}` already defined in {seen[gate.name]}"
                )
            seen[gate.name] = f"pack `{pack.name}`"
            pack_gates.append(gate)
    return replace(cfg, gates=core + tuple(pack_gates) + project)


def load(path: Path | None = None) -> HarnessConfig:
    """Load harness.toml merged over harness/core.toml and the enabled packs next to it."""
    target = CONFIG_PATH if path is None else path
    if not target.is_file():
        raise ConfigError(f"{target.as_posix()} does not exist")
    core_path = target.parent / CORE_RELATIVE
    if not core_path.is_file():
        raise ConfigError(
            f"{core_path.as_posix()} does not exist; it holds the core gates and the controls "
            "baseline (ADR-0011). Restore it from the harness."
        )
    core_data = _read(core_path)
    for key in core_data:
        if key not in CORE_KEYS:
            raise ConfigError(f"harness/core.toml: unknown key `{key}` (allowed: controls, gates)")
    merged = merge(parse(core_data), parse(_read(target)))
    packs = tuple(load_pack(target.parent, name) for name in merged.packs)
    return merge_packs(merged, packs)
