"""Normalize OpenBot hook payloads (2.0, CLI, IDE) into a single Event (stdlib only).

For `pre` events the parser fails closed: unreadable JSON, missing tool name, or a known
write/read/shell tool missing its target raises PayloadError so the dispatcher denies the call.
Unknown/MCP tools are classified only when evidence exists (name hint plus path or command).
`post` tolerates payloads without `toolCall` (observed in OpenBot IDE).
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast

AGENTS = ("antigravity",)
EVENTS = ("pre", "post", "pre-invocation", "post-invocation", "stop", "session-start")

KNOWN_KINDS: dict[str, str] = {
    "write_to_file": "write",
    "write_file": "write",
    "replace_file_content": "write",
    "multi_replace_file_content": "write",
    "edit_file": "write",
    "view_file": "read",
    "view_file_outline": "read",
    "view_code_item": "read",
    "list_dir": "read",
    "read_file": "read",
    "read_resource": "read",
    "run_command": "shell",
    "send_command_input": "shell",
    "grep_search": "search",
    "find_by_name": "search",
    "list_resources": "search",
    "invoke_subagent": "subagent",
    "swarm": "subagent",
    "Agent": "subagent",
    "Task": "subagent",
}
SHELL_HINT = re.compile(r"bash|shell|pwsh|powershell|command|exec|terminal", re.IGNORECASE)
WRITE_HINT = re.compile(r"write|replace|append|delete|edit|patch|move|rename|relocate", re.I)
READ_HINT = re.compile(r"read|view|open|list_dir", re.IGNORECASE)

PATH_KEYS = (
    "TargetFile",
    "AbsolutePath",
    "AbsolutePaths",
    "DirectoryPath",
    "File",
    "Path",
    "Uri",
    "targetFile",
    "filePath",
    "file_path",
    "path",
    "paths",
    "sourcePath",
    "destinationPath",
)
CONTENT_KEYS = frozenset(
    {
        "CodeContent",
        "ReplacementContent",
        "Content",
        "Replacement",
        "content",
        "text",
        "new_str",
        "newStr",
        "new_string",
    }
)
EXCLUDED_DIFF_KEYS = frozenset({"TargetContent", "Target", "old_string", "oldStr", "old_str"})
SEARCH_KEYS = (
    "SearchPath",
    "SearchDirectory",
    "DirectoryPath",
    "Includes",
    "path",
    "glob",
    "includePattern",
)
SEARCH_PATTERN_KEYS = {"find_by_name": "Pattern", "grep_search": "Query"}
COMMAND_KEYS = ("CommandLine", "command", "cmd", "Input")


class PayloadError(ValueError):
    """The hook payload cannot be understood safely."""


@dataclass(frozen=True, slots=True)
class Event:
    agent: str
    event: str
    tool: str = ""
    kind: str = "other"  # write | read | shell | search | subagent | other
    paths: tuple[str, ...] = ()
    content: str = ""
    command: str = ""
    session_id: str = ""
    continuation_active: bool = False
    termination_reason: str = ""
    cwd: str = ""
    include_ignored: bool = False
    subagent_type: str = ""
    model: str = ""
    action: str = ""


def _obj(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _paths(args: dict[str, object]) -> tuple[str, ...]:
    found: list[str] = []
    for key in PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            found.append(value)
        elif isinstance(value, list):
            found.extend(v for v in cast(list[object], value) if isinstance(v, str) and v)
    return tuple(dict.fromkeys(found))


def _contents(value: object) -> Iterator[str]:
    """Collect newly written strings at any depth, ignoring pre-edit TargetContent text."""
    if isinstance(value, dict):
        for key, item in cast(dict[str, object], value).items():
            if key in EXCLUDED_DIFF_KEYS:
                continue
            if key in CONTENT_KEYS and isinstance(item, str):
                yield item
            else:
                yield from _contents(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _contents(item)


def _all_strings(value: object) -> Iterator[str]:
    """Every string leaf of an unknown tool's arguments, so guards can scan it for secrets.

    Unlike `_contents`, no key is skipped: `TargetContent`/`old_string` only mean "pre-edit text"
    for the known write tools, while an unknown tool may send any of its arguments elsewhere.
    """
    if isinstance(value, str):
        if value:
            yield value
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _all_strings(item)


def _command(args: dict[str, object]) -> str:
    for key in COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            return shlex.join(v for v in cast(list[object], value) if isinstance(v, str))
    return ""


def _search_targets(tool: str, args: dict[str, object]) -> tuple[str, ...]:
    pattern_key = SEARCH_PATTERN_KEYS.get(tool, "")
    keys = (*SEARCH_KEYS, pattern_key) if pattern_key else SEARCH_KEYS
    found: list[str] = []
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value:
            found.append(value)
        elif isinstance(value, list):
            found.extend(v for v in cast(list[object], value) if isinstance(v, str) and v)
    return tuple(dict.fromkeys(found))


def _classify(tool: str, paths: tuple[str, ...], command: str) -> str:
    if tool in KNOWN_KINDS:
        return KNOWN_KINDS[tool]
    if command and SHELL_HINT.search(tool):
        return "shell"
    if paths and WRITE_HINT.search(tool):
        return "write"
    if paths and READ_HINT.search(tool):
        return "read"
    return "other"


def _first_workspace(data: dict[str, object]) -> str:
    workspaces = data.get("workspacePaths")
    if isinstance(workspaces, list) and workspaces:
        return _str(cast(list[object], workspaces)[0])
    return ""


def parse(agent: str, event: str, raw: str) -> Event:
    if agent not in AGENTS:
        raise PayloadError(f"unknown agent `{agent}` (expected one of {', '.join(AGENTS)})")
    if event not in EVENTS:
        raise PayloadError(f"unknown event `{event}` (expected one of {', '.join(EVENTS)})")
    try:
        loaded: object = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise PayloadError(f"payload is not valid JSON ({exc.msg})") from exc
    except RecursionError as exc:
        raise PayloadError("payload is nested too deeply to inspect") from exc
    if not isinstance(loaded, dict):
        raise PayloadError("payload is not a JSON object")

    data = cast(dict[str, object], loaded)
    call = _obj(data.get("toolCall"))
    tool = _str(call.get("name"))
    args = _obj(call.get("args"))
    session = _str(data.get("conversationId")) or _str(data.get("session_id"))
    cwd = _str(data.get("cwd")) or _str(args.get("Cwd")) or _first_workspace(data)
    continuation_active = data.get("continuationActive") is True
    termination_reason = _str(data.get("terminationReason"))

    paths = _paths(args)
    content = "\n".join(_contents(args))
    command = _command(args)
    kind = _classify(tool, paths, command)
    include_ignored = False
    subagent_type = ""
    model = ""
    action = ""

    if kind == "search":
        paths = _search_targets(tool, args)
        command = ""
        include_ignored = args.get("includeIgnoredFiles") in (True, "yes", "true")

    if tool == "send_command_input" and not command and args.get("Terminate") is True:
        kind = "other"

    if kind == "subagent":
        content = "\n".join(_all_strings(args))
        subagent_type = _str(args.get("subagent_type")) or _str(args.get("TypeName"))
        model = _str(args.get("model")) or _str(args.get("Model"))
        action = _str(args.get("action")) or _str(args.get("Action"))

    if kind == "other" and tool not in KNOWN_KINDS:
        # Unknown and MCP tools: inspect every argument string (messages, issue bodies, ...).
        content = "\n".join(_all_strings(args))

    if event == "pre":
        if not tool:
            raise PayloadError("pre-tool payload has no tool name")
        if kind in ("write", "read") and not paths:
            raise PayloadError(f"{kind} tool `{tool}` without a target path")
        if kind == "shell" and not command:
            raise PayloadError(f"shell tool `{tool}` without a command")
        if kind == "subagent":
            if tool == "swarm" and not action:
                raise PayloadError(f"subagent tool `{tool}` without an action")
            if tool != "swarm" and not subagent_type:
                raise PayloadError(f"subagent tool `{tool}` without a subagent type")

    return Event(
        agent=agent,
        event=event,
        tool=tool,
        kind=kind,
        paths=paths,
        content=content,
        command=command,
        session_id=session,
        continuation_active=continuation_active,
        termination_reason=termination_reason,
        cwd=cwd,
        include_ignored=include_ignored,
        subagent_type=subagent_type,
        model=model,
        action=action,
    )
