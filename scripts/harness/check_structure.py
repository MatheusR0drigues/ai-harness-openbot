"""Architecture-fitness gate for the OpenBot hookless harness layout (stdlib only).

Checks the guidance and wiring that OpenBot reads:
- AGENTS.md (and harness/templates/AGENTS.md when present): exists, <= 200 lines, has the PT-BR
  sections of the template (accented or unaccented spellings).
- .agents/rules/*.md (optional): flat YAML front matter, valid trigger, < 24000 bytes.
- .agents/skills/<name>/SKILL.md (optional): name = folder, lowercase-hyphen, description length.
- Hookless mode (`not HOOKS_FILE`): local hooks file is not required.
- Every repository path quoted in backticks in AGENTS.md, README.md, .agents/ and docs/*.md
  exists.
- harness/packs/*/pack.toml load with `config.load_pack`.
- plugin/ (only when plugin/plugin.json exists): manifest, forbidden files, rules, skills,
  OpenBot subagents, shared scripts identical to scripts/harness/.
- No private-domain or other-IDE leaks in plugin/ and harness/templates/.

Usage: python scripts/harness/check_structure.py
Exit code: 0 when valid, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import cast

import config
import dialect

REPO_ROOT = config.REPO_ROOT
AGENTS_MAX_LINES = 200
AGENTS_TEMPLATE = "harness/templates/AGENTS.md"
REQUIRED_SECTIONS = (
    "## Projeto",
    "## Stack",
    "## Comandos",
    "## Topologia do Repositório",
    "## Convenções Críticas",
    "## Comportamento do Agente",
    "## Fluxo de Trabalho",
    "## Critério de Pronto",
    "## Mapa de Conhecimento",
)
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX = 64
DESCRIPTION_MIN, DESCRIPTION_MAX = 30, 1024
RULE_TRIGGERS = ("always_on", "model_decision", "glob", "manual")
RULE_MAX_BYTES = 24_000  # OpenBot truncates rule files at 24 KB: stay strictly below
PATH_REF = re.compile(
    r"`((?:\.agents|scripts|tests|docs|harness|workflows|plugin|specs|contracts|schemas)/[^`\s<>*{}]*)`"
)
MD_LINK_REF = re.compile(r"\]\(([^)\s]+)\)")

HOOKS_FILE = dialect.HOOKS_REL
CLI = "scripts/harness/cli.py"
AGENT = "openbot"
HOOK_EVENTS = dialect.RENDERED_EVENTS  # hook event -> harness CLI event, in render order
TOOL_EVENTS = dialect.TOOL_EVENTS
HOOK_CALL = re.compile(r"\bhook\s+([\w-]+)\s+--agent\s+([\w-]+)")
HARNESS_COMMAND = re.compile(
    r"^python3?\s+\.\./scripts/harness/cli\.py\s+hook\s+[\w-]+\s+--agent\s+antigravity$"
)
DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")

PLUGIN = "plugin"
PLUGIN_NAME = "ai-harness"
PLUGIN_FIELDS = ("displayName", "version", "description")
PLUGIN_ROOT_FORBIDDEN = ("hooks.json",)
PLUGIN_ANYWHERE_FORBIDDEN = ("mcp_config.json",)
OTHER_IDE_DIRS = frozenset({".claude", ".kiro", ".codex"})
RESERVED_AGENT_NAMES = frozenset({"self", "browser", "research", "deepagent", "review-agent"})
AGENT_TOOLS: dict[str, frozenset[str]] = {
    "researcher": frozenset({"read_file"}),
    "planner": frozenset({"read_file", "search_web"}),
    "implementer": frozenset(
        {"read_file", "edit_file", "write_file", "run_command", "manage_task"}
    ),
    "code-reviewer": frozenset({"read_file", "run_command", "manage_task"}),
    "security-auditor": frozenset({"read_file", "run_command", "manage_task"}),
}
ANY_AGENT_TOOLS = frozenset(tool for tools in AGENT_TOOLS.values() for tool in tools)
WRITE_OR_SHELL_TOOLS = frozenset(
    {
        "edit_file",
        "write_file",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
        "run_command",
        "send_command_input",
    }
)
AUDITOR_AGENTS = frozenset({"code-reviewer", "security-auditor"})
VERDICT_TERMS = ("PASS", "FAIL", "blocker", "major", "minor")
SHARED_SCRIPTS = ("check_secrets.py", "validate_spec.py")
LEAK_TERMS = re.compile(r"(?i)\bAP-00[1-6]\b|\.claude\b|\.kiro\b|\.codex\b|\{\{")
PRIVATE_TOKEN_RE = re.compile(r"src/[a-z0-9_-]+/|[a-z0-9]+(?:-[a-z0-9]+)*")
# SHA-256 digests of lowercase private project/client identifiers and internal paths (ADR-0026).
PRIVATE_TOKEN_HASHES = frozenset(
    {
        "24f5c2c2af437a1175c4ff3baff47b06fbc9d95277753d833b1be71f2faf07fd",
        "314718a1579424f5c2d38c27c21f03c2c0028e9f0cf62bd4e503c1ae3c36ac1e",
        "b66f392490c54d546a69585e711e6baf85468d03a9897337a18e2f165124f025",
        "ce815334aa5b6865a49df82651b44fd9e0a660290619bc73b859a68cfced455a",
        "d3a50fe9cd63963b6e4c2637c83d7af0f4b9f16b15c6bc050302d95fea4b2ed9",
        "d43d73447fca72aabcf91917c5f935621d8b903396b42551e8705e8753d90ea0",
    }
)
HINT = (
    "Fix the files listed above. Keep AGENTS.md a short map (detail goes to rules or skills), "
    "keep every rule below 24000 bytes with valid front matter, and keep .agents/ and plugin/ "
    "free of private-domain and other-IDE content. Never edit this gate to make it pass."
)


def parse_front_matter(text: str) -> dict[str, str] | None:
    """Flat `key: value` YAML front matter; None when the file does not start with one."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("\"'")
    return meta


def body_of(text: str) -> str:
    """Everything after the closing `---` of the front matter (the whole text without one)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


YAML_INDICATORS = tuple("-?:,[]{}#&*!|>'\"%@`")


def yaml_problems(text: str) -> list[str]:
    """Front-matter values that a real YAML parser would reject or misread.

    OpenBot parses front matter with a full YAML parser; an unquoted value containing `: `
    or starting with an indicator character makes the whole block invalid, and the skill, rule
    or subagent silently disappears.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    problems: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t", "-", "#")):
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        if not value or value[0] in "\"'[{" or value in ("|", ">"):
            continue
        if (
            ": " in value
            or value.endswith(":")
            or " #" in value
            or value.startswith(YAML_INDICATORS)
        ):
            problems.append(
                f"`{key}` must be quoted (its value contains `: `, ` #` or a leading "
                "YAML indicator)"
            )
    return problems


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def fold_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _check_agents_file(paths: Sequence[Path], root: Path) -> list[str]:
    """Line limit for each file of the guidance set; required sections in their union.

    `paths[0]` is the guidance file itself, the one named by missing-section errors.
    """
    errors: list[str] = []
    folded: list[str] = []
    for path in paths:
        where = rel(path, root)
        lines = read(path).splitlines()
        if len(lines) > AGENTS_MAX_LINES:
            errors.append(
                f"{where}: {len(lines)} lines; the limit is {AGENTS_MAX_LINES}. "
                "Move detail into .agents/rules, plugin rules or skills."
            )
        folded += [fold_accents(line) for line in lines]
    where = rel(paths[0], root)
    errors.extend(
        f"{where}: missing section `{section}`"
        for section in REQUIRED_SECTIONS
        if not any(line.startswith(fold_accents(section)) for line in folded)
    )
    return errors


def _check_guidance(path: Path, root: Path) -> list[str]:
    paths, errors = dialect.guidance_set(path, root)
    return [*errors, *_check_agents_file(paths, root)]


def check_agents_md(root: Path) -> list[str]:
    path = root / "AGENTS.md"
    if not path.is_file():
        return ["AGENTS.md: file is missing"]
    return _check_guidance(path, root)


def check_agents_template(root: Path) -> list[str]:
    """The AGENTS.md template projected into new repositories obeys the same contract."""
    path = root / AGENTS_TEMPLATE
    return _check_guidance(path, root) if path.is_file() else []


def check_rule_file(path: Path, root: Path) -> list[str]:
    where = rel(path, root)
    data = path.read_bytes()
    errors: list[str] = []
    if len(data) >= RULE_MAX_BYTES:
        errors.append(f"{where}: {len(data)} bytes; a rule must stay below {RULE_MAX_BYTES} bytes")
    text = data.decode("utf-8-sig", errors="replace")
    meta = parse_front_matter(text)
    if meta is None:
        errors.append(f"{where}: must start with a `---` front-matter block")
        return errors
    errors.extend(f"{where}: invalid YAML: {p}" for p in yaml_problems(text))
    trigger = meta.get("trigger", "")
    if trigger not in RULE_TRIGGERS:
        errors.append(f"{where}: trigger must be one of {', '.join(RULE_TRIGGERS)}")
    if trigger == "model_decision" and not meta.get("description"):
        errors.append(f"{where}: trigger model_decision needs a `description`")
    if trigger == "glob" and not meta.get("globs"):
        errors.append(f"{where}: trigger glob needs `globs` (comma-separated patterns)")
    return errors


def check_rules(root: Path) -> list[str]:
    return [
        error
        for path in sorted((root / ".agents" / "rules").glob("*.md"))
        for error in check_rule_file(path, root)
    ]


def check_skill_folder(folder: Path, root: Path) -> list[str]:
    skill = folder / "SKILL.md"
    where = rel(skill, root)
    if not skill.is_file():
        return [f"{rel(folder, root)}: SKILL.md is missing"]
    text = read(skill)
    meta = parse_front_matter(text)
    if meta is None:
        return [f"{where}: must start with a `---` front-matter block"]
    errors = [f"{where}: invalid YAML: {p}" for p in yaml_problems(text)]
    name = meta.get("name", "")
    if name != folder.name:
        errors.append(f"{where}: name `{name}` must equal the folder name `{folder.name}`")
    if not SKILL_NAME.match(folder.name) or len(folder.name) > SKILL_NAME_MAX:
        errors.append(f"{where}: name must be lowercase letters, digits and hyphens (max 64)")
    description = meta.get("description", "")
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        errors.append(
            f"{where}: description must be {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters "
            "and say what the skill does and when to use it"
        )
    return errors


def _folders(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def check_skills(root: Path) -> list[str]:
    return [
        error
        for folder in _folders(root / ".agents" / "skills")
        for error in check_skill_folder(folder, root)
    ]


def _local_markdown_refs(text: str) -> set[str]:
    """Local file targets of markdown links `[label](target)` (URLs and placeholders excluded)."""
    refs: set[str] = set()
    for raw in MD_LINK_REF.findall(text):
        target = raw.split("#", 1)[0].rstrip(".,:;")
        if (
            not target
            or "://" in target
            or target.startswith(("mailto:", "tel:", "/"))
            or DRIVE_PATH.match(target)
            or any(char in target for char in "<>*{}")
        ):
            continue
        refs.add(target)
    return refs


def guidance_files(root: Path) -> Iterator[Path]:
    for name in ("AGENTS.md", "README.md"):
        if (root / name).is_file():
            yield root / name
    yield from sorted((root / ".agents" / "rules").glob("*.md"))
    if not (root / PLUGIN / "plugin.json").is_file():
        yield from sorted((root / ".agents" / "skills").glob("*/**/*.md"))
    yield from sorted((root / "docs").glob("*.md"))
    yield from sorted((root / "docs" / "context").glob("*.md"))


def check_references(root: Path) -> list[str]:
    errors: list[str] = []
    for path in guidance_files(root):
        text = read(path)
        refs = {ref.split("::")[0].rstrip(".,:;") for ref in PATH_REF.findall(text)}
        missing_backticks = {r for r in refs if not (root / r).exists()}
        missing_links = {
            r
            for r in _local_markdown_refs(text)
            if not (path.parent / r).exists() and not (root / r).exists()
        }
        missing = sorted(missing_backticks | missing_links)
        if missing:
            errors.append(f"{rel(path, root)}: references missing paths: {', '.join(missing)}")
    return errors


def hook_commands(doc: dict[str, object]) -> list[str]:
    """Every command of every handler entry of the hooks document, in document order."""
    entries, _ = dialect.walk(doc)
    return [command for entry in entries for command in entry.commands]


_commands = hook_commands  # former name, kept for tests/harness/test_check_hooks.py


def matchers(data: object, event: str) -> list[str]:
    """Matcher of every entry wired to `event` in the `{group: {Event: [...]}}` hooks shape."""
    found: list[str] = []
    table = cast(dict[str, object], data) if isinstance(data, dict) else {}
    for group in table.values():
        entries = cast(dict[str, object], group).get(event) if isinstance(group, dict) else None
        if isinstance(entries, list):
            for raw in cast(list[object], entries):
                entry = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
                found.append(str(entry.get("matcher", "")))
    return found


def _load_json(path: Path, root: Path, errors: list[str]) -> object | None:
    try:
        return json.loads(read(path))
    except json.JSONDecodeError as exc:
        errors.append(f"{rel(path, root)}: not valid JSON ({exc.msg})")
        return None


def _path_tokens(command: str) -> list[str]:
    """Tokens that name a relative filesystem path (URLs, flags and absolute paths excluded)."""
    tokens: list[str] = []
    for raw in command.split():
        token = raw.strip("\"'")
        if "/" not in token and "\\" not in token:
            continue
        if token.startswith(("-", "/", "~", "$", "%")) or "://" in token or DRIVE_PATH.match(token):
            continue
        tokens.append(token)
    return tokens


def _check_command(command: str, label: str, root: Path) -> list[str]:
    """Rules every hook command obeys, harness CLI or pack script (ADR-0004, CWD = .agents/)."""
    errors: list[str] = []
    if '"' in command:
        errors.append(
            f"{label}: commands must contain no double quotes (OpenBot escapes them before "
            f"cmd.exe runs the hook); use `python ../{CLI} hook <event> --agent {AGENT}`"
        )
    for token in _path_tokens(command):
        normalized = token.replace("\\", "/")
        if not normalized.startswith("../"):
            errors.append(
                f"{label}: path `{token}` is relative to the repository root, but OpenBot "
                f"runs hooks from .agents/; use `../{normalized}`"
            )
        elif normalized.endswith(".py") and not (root / ".agents" / normalized).resolve().is_file():
            errors.append(f"{label}: `{token}` does not exist (resolved from .agents/)")
    return errors


def _check_harness_call(
    command: str, event: str, matcher: str | None, label: str
) -> tuple[str | None, list[str]]:
    """Validate one harness CLI call; return the harness event it wires (None if invalid)."""
    errors: list[str] = []
    call = HOOK_CALL.search(command)
    if call is None:
        return None, [
            f"{label}: harness call must be `python ../{CLI} hook <event> --agent {AGENT}`"
        ]
    cli_event, agent = call.groups()
    expected = HOOK_EVENTS.get(event)
    if expected is None:
        return None, [
            f"{label}: {event} does not call the harness (harness events: {', '.join(HOOK_EVENTS)})"
        ]
    if agent != AGENT:
        errors.append(f"{label}: command uses --agent {agent}; expected --agent {AGENT}")
    if cli_event != expected:
        errors.append(f"{label}: {event} must call `hook {expected}`, not `hook {cli_event}`")
    if event in TOOL_EVENTS and matcher != "":
        errors.append(
            f'{label}: {event} entries calling the harness must use "matcher": "" so every tool '
            "(including MCP tools) passes through the guards"
        )
    return (cli_event if not errors else None), errors


def _check_entry(entry: dialect.HookEntry, root: Path) -> tuple[list[str], int]:
    """Errors of one handler entry and how many valid harness CLI calls it holds.

    Every command that calls the CLI obeys the harness rules, kit entry or not (D17); the
    quoting and path rules of `_check_command` reach third-party entries only when the dialect
    says so.
    """
    if entry.owner == "kit":
        errors = [] if entry.commands else [f"{entry.label}: declares no `command`"]
    else:
        errors = dialect.third_party_errors(entry)
    event = entry.event
    entry_label = entry.label
    calls = 0
    for command in entry.commands:
        calls_cli = CLI in command.replace("\\", "/")
        command_errors: list[str] = []
        if calls_cli or entry.owner == "kit" or dialect.QUOTES_RULE_APPLIES_TO_THIRD_PARTY:
            command_errors += _check_command(command, entry_label, root)
        if calls_cli:
            harness_event, call_errors = _check_harness_call(
                command, event, entry.matcher, entry_label
            )
            command_errors += call_errors
            if not command_errors and not HARNESS_COMMAND.match(command.strip()):
                command_errors.append(
                    f"{entry_label}: harness call must be exactly "
                    f"`python ../{CLI} hook {HOOK_EVENTS[event]} --agent {AGENT}`"
                )
            if harness_event is not None and not command_errors:
                calls += 1
        errors += command_errors
    return errors, calls


def check_hooks(root: Path) -> list[str]:
    if not HOOKS_FILE:
        if not (root / PLUGIN / "plugin.json").is_file():
            ci_gate = root / ".github" / "workflows" / "harness-verify.yml"
            if ci_gate.is_file():
                wf_text = read(ci_gate)
                ci_errors: list[str] = []
                if not wf_text.strip():
                    ci_errors.append(".github/workflows/harness-verify.yml: file is empty")
                for required_ref in (
                    "scripts/harness/check_tamper.py",
                    "scripts/harness/verify.py",
                ):
                    if required_ref not in wf_text:
                        ci_errors.append(
                            ".github/workflows/harness-verify.yml: missing reference "
                            f"`{required_ref}`"
                        )
                return ci_errors
        return []
    path = root / HOOKS_FILE
    if not path.is_file():
        return [f"{HOOKS_FILE}: file is missing (project it with `python {CLI} init`)"]
    try:
        doc = dialect.load(path.read_bytes())
    except dialect.HooksFileError as exc:
        return [str(exc)]
    errors = dialect.top_level_errors(doc)
    wired: Counter[str] = Counter()
    # One walk per top-level key keeps the errors of each key in document order: the entry
    # errors of a key, then its shape errors, before the next key.
    for name, value in doc.items():
        entries, shape_errors = dialect.walk({name: value})
        for entry in entries:
            entry_errors, calls = _check_entry(entry, root)
            errors += entry_errors
            wired[entry.event] += calls
        errors += shape_errors
    # D16: count valid harness CLI calls per rendered event; pack commands never count.
    errors.extend(
        f"{HOOKS_FILE}: {event} has {wired[event]} harness entries; keep exactly one"
        for event in HOOK_EVENTS
        if wired[event] > 1
    )
    missing = [f"{event} (hook {cli})" for event, cli in HOOK_EVENTS.items() if not wired[event]]
    if missing:
        errors.append(f"{HOOKS_FILE}: missing harness events: {', '.join(missing)}")
    return errors


def check_packs(root: Path) -> list[str]:
    """Each installed harness/packs/<name>/pack.toml loads with the config schema."""
    packs_dir = root / config.PACKS_RELATIVE
    if not packs_dir.is_dir():
        return []
    errors: list[str] = []
    for manifest in sorted(packs_dir.glob(f"*/{config.PACK_FILE}")):
        try:
            config.load_pack(root, manifest.parent.name)
        except config.ConfigError as exc:
            errors.append(f"{rel(manifest, root)}: {exc}")
    return errors


def _check_plugin_manifest(plugin: Path, root: Path) -> list[str]:
    manifest = plugin / "plugin.json"
    where = rel(manifest, root)
    errors: list[str] = []
    data = _load_json(manifest, root, errors)
    if data is None:
        return errors
    if not isinstance(data, dict):
        return [f"{where}: must be a JSON object"]
    table = cast(dict[str, object], data)
    if table.get("name") != PLUGIN_NAME:
        errors.append(f'{where}: "name" must be "{PLUGIN_NAME}"')
    for field in PLUGIN_FIELDS:
        value = table.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f'{where}: "{field}" must be a non-empty string')
    return errors


def _check_plugin_forbidden(plugin: Path, root: Path) -> list[str]:
    errors = [
        f"{PLUGIN}/{name}: forbidden in the global plugin"
        for name in PLUGIN_ROOT_FORBIDDEN
        if (plugin / name).exists()
    ]
    for dirpath, dirnames, filenames in os.walk(plugin):
        base = Path(dirpath)
        for name in sorted([*dirnames, *filenames]):
            where = rel(base / name, root)
            if name in OTHER_IDE_DIRS:
                errors.append(f"{where}: other-IDE content is out of scope for the plugin")
            elif name in PLUGIN_ANYWHERE_FORBIDDEN:
                errors.append(
                    f"{where}: MCP servers are configured manually by the user, never shipped "
                    "by the plugin"
                )
        dirnames[:] = [d for d in dirnames if d not in OTHER_IDE_DIRS]
    return errors


def _check_plugin_rules(plugin: Path, root: Path) -> list[str]:
    rules = plugin / "rules"
    agents = rules / "AGENTS.md"
    errors: list[str] = []
    if not agents.is_file():
        errors.append(f"{rel(agents, root)}: file is missing")
    else:
        text = read(agents)
        where = rel(agents, root)
        if parse_front_matter(text) is not None or text.lstrip().startswith("---"):
            errors.append(f"{where}: must not have YAML front matter (standalone rule)")
        line_count = len(text.splitlines())
        if line_count > AGENTS_MAX_LINES:
            errors.append(f"{where}: {line_count} lines; the limit is {AGENTS_MAX_LINES}")
    for path in sorted(rules.glob("*.md")):
        if path.name != "AGENTS.md":
            errors += check_rule_file(path, root)
    return errors


def _relative_refs(text: str) -> set[str]:
    """`../` targets of markdown links and of backtick spans that start with `../`.

    Only spans that begin with the path count: a quoted command such as
    `python ../scripts/harness/cli.py ...` is relative to another directory (.agents/).
    Placeholders (`<`, `>`, `*`, `{`, `}`) are ignored.
    """
    candidates: list[str] = re.findall(r"\]\((\.\./[^)\s]+)\)", text)
    candidates += [span.split()[0] for span in re.findall(r"`(\.\./[^`\n]*)`", text)]
    refs: set[str] = set()
    for candidate in candidates:
        target = candidate.split("#", 1)[0].rstrip(".,:;")
        if target and not any(char in target for char in "<>*{}"):
            refs.add(target)
    return refs


def _check_plugin_skills(plugin: Path, root: Path) -> list[str]:
    skills = plugin / "skills"
    errors: list[str] = []
    resolved_plugin = plugin.resolve()
    for folder in _folders(skills):
        errors += check_skill_folder(folder, root)
        skill = folder / "SKILL.md"
        if not skill.is_file():
            continue
        for ref in sorted(_relative_refs(read(skill))):
            target = (folder / ref).resolve()
            if not target.is_relative_to(resolved_plugin):
                errors.append(
                    f"{rel(skill, root)}: `{ref}` escapes plugin/ and breaks once the plugin is "
                    "installed globally"
                )
            elif not target.exists():
                errors.append(f"{rel(skill, root)}: `{ref}` does not exist")
    if skills.is_dir():
        errors.extend(
            f"{rel(path, root)}: scripts live once in plugin/scripts/, never inside a skill"
            for path in sorted(skills.rglob("*.py"))
        )
    return errors


def parse_inline_list(value: str) -> list[str] | None:
    """Items of an inline YAML list `[a, b]`; None when `value` is not an inline list."""
    stripped = value.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return None
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    items = [item.strip().strip("\"'") for item in inner.split(",")]
    return None if any(not item for item in items) else items


def _check_agent_tools(name: str, value: str, where: str) -> list[str]:
    tools = parse_inline_list(value)
    if not tools:
        return [f"{where}: `tools` must be a non-empty inline YAML list such as `[read_file]`"]
    errors: list[str] = []
    allowed = AGENT_TOOLS.get(name, ANY_AGENT_TOOLS)
    disallowed = [tool for tool in tools if tool not in allowed]
    if name == "researcher":
        writes = [tool for tool in tools if tool in WRITE_OR_SHELL_TOOLS]
        if writes:
            errors.append(
                f"{where}: researcher must stay read-only; remove write/shell tools "
                f"{', '.join(writes)}"
            )
        disallowed = [tool for tool in disallowed if tool not in writes]
    if disallowed:
        errors.append(
            f"{where}: tools {', '.join(disallowed)} are not allowed for `{name}` "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    return errors


def _check_plugin_agent(path: Path, root: Path) -> list[str]:
    where = rel(path, root)
    text = read(path)
    meta = parse_front_matter(text)
    if meta is None:
        return [f"{where}: must start with a `---` front-matter block"]
    errors = [f"{where}: invalid YAML: {p}" for p in yaml_problems(text)]
    name = meta.get("name", "")
    if name != path.stem:
        errors.append(f"{where}: name `{name}` must equal the file name `{path.stem}`")
    if name in RESERVED_AGENT_NAMES or path.stem in RESERVED_AGENT_NAMES:
        errors.append(f"{where}: name `{name}` collides with a built-in OpenBot agent")
    description = meta.get("description", "")
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        errors.append(
            f"{where}: description must be {DESCRIPTION_MIN}-{DESCRIPTION_MAX} characters"
        )
    if "subagent" in meta:
        errors.append(f"{where}: subagent field is forbidden in OpenBot")
    if "mainAgent" in meta:
        errors.append(f"{where}: mainAgent field is forbidden in OpenBot")
    model = meta.get("model", "")
    if model not in ("flash", "pro", "inherit"):
        errors.append(f"{where}: model `{model}` must be flash, pro or inherit")
    workspace = meta.get("workspace", "")
    if workspace not in ("share", "inherit"):
        errors.append(f"{where}: workspace `{workspace}` must be share or inherit")
    errors += _check_agent_tools(name, meta.get("tools", ""), where)
    body = body_of(text)
    if name in AUDITOR_AGENTS:
        missing = [term for term in VERDICT_TERMS if term not in body]
        if missing:
            errors.append(
                f"{where}: auditor prompt must use the verdict vocabulary PASS | FAIL and "
                f"[blocker | major | minor]; missing {', '.join(missing)}"
            )
    return errors


def _check_plugin_agents(plugin: Path, root: Path) -> list[str]:
    return [
        error
        for path in sorted((plugin / "agents").glob("*.md"))
        for error in _check_plugin_agent(path, root)
    ]


def check_agents(root: Path) -> list[str]:
    agents_dir = root / ".agents" / "agents"
    if not agents_dir.is_dir():
        return []
    return [
        error
        for path in sorted(agents_dir.glob("*.md"))
        for error in _check_plugin_agent(path, root)
    ]


def _check_plugin_scripts(plugin: Path, root: Path) -> list[str]:
    scripts = plugin / "scripts"
    if not scripts.is_dir():
        return []
    errors: list[str] = []
    for name in SHARED_SCRIPTS:
        copy = scripts / name
        canonical = root / "scripts" / "harness" / name
        if not copy.is_file():
            errors.append(f"{rel(copy, root)}: file is missing")
        elif not canonical.is_file():
            errors.append(f"scripts/harness/{name}: canonical copy is missing")
        elif copy.read_bytes() != canonical.read_bytes():
            errors.append(
                f"{rel(copy, root)}: differs from scripts/harness/{name}; copy the canonical file "
                "byte for byte"
            )
    return errors


def check_plugin(root: Path) -> list[str]:
    plugin = root / PLUGIN
    if not (plugin / "plugin.json").is_file():
        return []
    return [
        *_check_plugin_manifest(plugin, root),
        *_check_plugin_forbidden(plugin, root),
        *_check_plugin_rules(plugin, root),
        *_check_plugin_skills(plugin, root),
        *_check_plugin_agents(plugin, root),
        *_check_plugin_scripts(plugin, root),
    ]


def leak_files(root: Path) -> list[Path]:
    plugin = root / PLUGIN
    found: list[Path] = []
    if plugin.is_dir():
        found += sorted(
            p for p in plugin.rglob("*") if p.suffix in (".md", ".json") and p.is_file()
        )
    templates = root / "harness" / "templates"
    if templates.is_dir():
        found += sorted(p for p in templates.iterdir() if p.is_file())
    packs = root / "harness" / "packs"
    if packs.is_dir():
        found += sorted(p for p in packs.rglob("*") if p.suffix in (".md", ".toml") and p.is_file())
    return found


def _sha256_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_line_leaks(line: str) -> list[str]:
    found = {match[0].lower() for match in LEAK_TERMS.finditer(line)}
    for match in PRIVATE_TOKEN_RE.finditer(line.lower()):
        token = match[0]
        if _sha256_token(token) in PRIVATE_TOKEN_HASHES:
            found.add(token)
    return sorted(found)


def check_leaks(root: Path) -> list[str]:
    errors: list[str] = []
    for path in leak_files(root):
        for number, line in enumerate(read(path).splitlines(), start=1):
            terms = find_line_leaks(line)
            if terms:
                errors.append(
                    f"{rel(path, root)}:{number}: private-domain, other-IDE or unresolved "
                    f"placeholder reference: {', '.join(terms)}"
                )
    return errors


def local_agent_collisions(root: Path) -> list[str]:
    agents_dir = root / ".agents" / "agents"
    if not agents_dir.is_dir():
        return []
    errors: list[str] = []
    global_map = {name.lower(): name for name in config.GLOBAL_AGENT_NAMES}
    reserved_map = {name.lower(): name for name in RESERVED_AGENT_NAMES}
    overrides = {name.lower() for name in config.agent_overrides(root)}

    for path in sorted(agents_dir.glob("*.md")):
        where = rel(path, root)
        text = read(path)
        meta = parse_front_matter(text)

        candidates: list[str] = [path.stem]
        if meta:
            fm_name = next((v for k, v in meta.items() if k.lower() == "name"), "").strip()
            if fm_name and fm_name != path.stem:
                candidates.append(fm_name)

        reported_for_file: set[str] = set()
        for cand in candidates:
            cand_lower = cand.lower()
            if cand_lower in reported_for_file:
                continue
            if cand_lower in reserved_map:
                reported_for_file.add(cand_lower)
                errors.append(
                    f"{where}: local agent `{cand}` collides with reserved agent "
                    f"`{reserved_map[cand_lower]}`"
                )
            elif cand_lower in global_map:
                plugin_mirror = root / PLUGIN / "agents" / path.name
                is_mirror = (
                    cand_lower == path.stem.lower()
                    and plugin_mirror.is_file()
                    and path.read_bytes() == plugin_mirror.read_bytes()
                )
                if not is_mirror and cand_lower not in overrides:
                    reported_for_file.add(cand_lower)
                    errors.append(
                        f"{where}: local agent `{cand}` collides with global agent "
                        f"`{global_map[cand_lower]}` (declare in [agents].allow_override to allow)"
                    )
    return errors


def check_local_agents(root: Path) -> list[str]:
    return local_agent_collisions(root)


CHECKS: tuple[Callable[[Path], list[str]], ...] = (
    check_agents_md,
    check_agents_template,
    check_rules,
    check_skills,
    check_agents,
    check_references,
    check_hooks,
    check_packs,
    check_plugin,
    check_leaks,
    check_local_agents,
)


def check_all(root: Path) -> list[str]:
    return [error for check in CHECKS for error in check(root)]


def main(argv: Sequence[str] | None = None, root: Path = REPO_ROOT) -> int:
    _ = sys.argv[1:] if argv is None else argv
    errors = check_all(root)
    if not errors:
        print("STRUCTURE VALID")
        return 0
    print(f"STRUCTURE INVALID: {len(errors)} problem(s)")
    for error in errors:
        print(f"  {error}")
    print("--- fix hint ---")
    print(HINT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
