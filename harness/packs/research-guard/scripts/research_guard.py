"""OpenBot PreToolUse guard: agents research only in docs/ and in the URLs of docs/links.txt.

Reads the hook payload (JSON) from stdin, shaped like
  {"toolCall": {"name": "search_web", "args": {...}}, "conversationId": "...",
   "workspacePaths": ["<repo>"]}
and decides:
- web search tools (search_web, ...)          -> deny (a search engine is never in the list)
- URL readers (read_url_content, browser ...)  -> only URLs under an entry of docs/links.txt
- shell tools (run_command, ...)               -> every http(s) URL literal must be listed;
                                                  download programs need a full listed URL
- writes to docs/links.txt                     -> ask the human (adding a site needs approval)
- anything else                                -> no output

Output contract: when the call may proceed, exit 0 with EMPTY stdout. Otherwise print one JSON
line `{"decision": "deny" | "ask", "reason": "..."}` and exit 0. It fails closed: a payload
that cannot be understood is denied. The allowlist is docs/links.txt under the repository root
(the first workspace path, else the closest folder above the cwd holding harness.toml or .git).
Stdlib only: it must run even when the project's dependencies are broken.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

LINKS_REL = "docs/links.txt"
ROOT_MARKERS = ("harness.toml", ".git")
SCRIPT_ROOT = Path(__file__).resolve().parents[4]  # <root>/harness/packs/research-guard/scripts

SEARCH_TOOLS = re.compile(r"search_web|web_?search|google_?search|bing", re.IGNORECASE)
FETCH_TOOLS = re.compile(r"read_url|url_content|fetch|brows|http_get|open_url", re.IGNORECASE)
SHELL_TOOLS = frozenset({"run_command", "send_command_input"})
SHELL_HINT = re.compile(r"bash|shell|pwsh|powershell|terminal|execute", re.IGNORECASE)
WRITE_TOOLS = frozenset(
    {
        "write_to_file",
        "write_file",
        "replace_file_content",
        "multi_replace_file_content",
        "edit_file",
    }
)
WRITE_HINT = re.compile(r"write|replace|append|delete|edit|patch|move|rename|relocate", re.I)
PATH_KEYS = (
    "TargetFile",
    "AbsolutePath",
    "AbsolutePaths",
    "File",
    "targetFile",
    "filePath",
    "file_path",
    "path",
    "paths",
    "sourcePath",
    "destinationPath",
)
URL = re.compile(r"https?://[^\s\"'<>`|;)]+", re.IGNORECASE)
DOMAIN = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?$", re.IGNORECASE)
DOWNLOADER = re.compile(
    r"(?:^|[\s;|&(`'\"])"
    r"(?:curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod|start-bitstransfer)"
    r"(?:\.exe)?(?=$|[\s;|&)`'\"])",
    re.IGNORECASE,
)

HOW_TO_ASK = (
    "Research is limited to docs/ (use grep_search) and the sites listed in docs/links.txt. If "
    "you really need this site, STOP and ask the human in chat: give the URL and why it is "
    "needed. Only after an explicit yes may you add it to docs/links.txt (the human confirms "
    "that edit again). If the answer is no, continue without that source."
)
ASK_REASON = (
    "The agent wants to change docs/links.txt (the list of sites approved for research). "
    "Approve only if you agreed in chat to add this site."
)


@dataclass(frozen=True, slots=True)
class Entry:
    host: str
    path: str  # "" = whole host; otherwise a path prefix without trailing slash


@dataclass(frozen=True, slots=True)
class Decision:
    action: str  # "deny" | "ask"
    reason: str

    def render(self) -> str:
        return json.dumps({"decision": self.action, "reason": self.reason})


def _split(url: str) -> tuple[str, str]:
    try:
        parts = urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower().removeprefix("www.")
    except ValueError:
        return "", ""
    return host, parts.path.rstrip("/")


def parse_links(text: str) -> list[Entry]:
    """Entries are separated by newlines, spaces, ';' or ','; lines starting with # are skipped."""
    entries: list[Entry] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for raw in re.split(r"[\s;,]+", line):
            token = raw.strip()
            if token.lower().startswith(("http://", "https://")) or DOMAIN.match(token):
                host, path = _split(token)
                if host:
                    entries.append(Entry(host, path))
    return entries


def load_allowlist(root: Path) -> list[Entry]:
    path = root / LINKS_REL
    if not path.is_file():
        return []
    return parse_links(path.read_text(encoding="utf-8-sig", errors="replace"))


def is_listed(url: str, allowlist: Sequence[Entry]) -> bool:
    host, path = _split(url)
    if not host:
        return False
    for entry in allowlist:
        if host != entry.host:
            continue
        if not entry.path or path == entry.path or path.startswith(entry.path + "/"):
            return True
    return False


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in cast(dict[str, object], value).values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _strings(item)


def _urls(args: dict[str, object]) -> list[str]:
    """http(s) literals anywhere in the arguments, plus scheme-less values of `*url*` keys."""
    found = [match.rstrip(".,") for text in _strings(args) for match in URL.findall(text)]
    for key, value in args.items():
        if "url" not in key.lower():
            continue
        for text in _strings(value):
            candidate = text.strip()
            if candidate and "://" not in candidate and DOMAIN.match(candidate):
                found.append(f"https://{candidate}")
    return list(dict.fromkeys(found))


def _paths(args: dict[str, object]) -> list[str]:
    found: list[str] = []
    for key in PATH_KEYS:
        found.extend(_strings(args.get(key)))
    return found


def _is_links_file(path: str) -> bool:
    normalized = path.replace("\\", "/").strip().lower()
    return normalized == LINKS_REL or normalized.endswith("/" + LINKS_REL)


def _denied(urls: Sequence[str], allowlist: Sequence[Entry]) -> list[str]:
    return [url for url in urls if not is_listed(url, allowlist)]


def _no_list_note(allowlist: Sequence[Entry]) -> str:
    return "" if allowlist else " (docs/links.txt is missing or empty)"


def decide(tool: str, args: dict[str, object], allowlist: Sequence[Entry]) -> Decision | None:
    """None when the call may proceed; otherwise a deny or ask decision."""
    if SEARCH_TOOLS.search(tool):
        return Decision("deny", f"BLOCKED web search ({tool}). {HOW_TO_ASK}")
    if FETCH_TOOLS.search(tool):
        urls = _urls(args)
        if not urls:
            return Decision("deny", f"BLOCKED {tool}: no URL found in the call. {HOW_TO_ASK}")
        denied = _denied(urls, allowlist)
        if denied:
            return Decision(
                "deny",
                f"BLOCKED {tool}: {', '.join(denied)} is not listed in docs/links.txt"
                f"{_no_list_note(allowlist)}. {HOW_TO_ASK}",
            )
        return None
    if tool in SHELL_TOOLS or SHELL_HINT.search(tool):
        command = " ".join(_strings(args))
        urls = _urls(args)
        denied = _denied(urls, allowlist)
        if LINKS_REL in command.replace("\\", "/").lower():
            extra = f" The command also reaches {', '.join(denied)}." if denied else ""
            return Decision("ask", ASK_REASON + extra)
        if denied:
            return Decision(
                "deny",
                f"BLOCKED shell command reaching {', '.join(denied)} (not listed in "
                f"docs/links.txt{_no_list_note(allowlist)}). {HOW_TO_ASK}",
            )
        if DOWNLOADER.search(command) and not urls:
            return Decision(
                "deny",
                "BLOCKED download command without a full http(s) URL listed in "
                f"docs/links.txt. {HOW_TO_ASK}",
            )
        return None
    if (tool in WRITE_TOOLS or WRITE_HINT.search(tool)) and any(
        _is_links_file(path) for path in _paths(args)
    ):
        return Decision("ask", ASK_REASON)
    return None


def find_root(start: Path | None = None) -> Path:
    """Closest folder at or above `start` (default: cwd) with harness.toml or .git."""
    origin = (Path.cwd() if start is None else start).resolve()
    for candidate in (origin, *origin.parents):
        if any((candidate / marker).exists() for marker in ROOT_MARKERS):
            return candidate
    return SCRIPT_ROOT


def _workspace(data: dict[str, object]) -> Path | None:
    workspaces = data.get("workspacePaths")
    if not isinstance(workspaces, list) or not workspaces:
        return None
    first = cast(list[object], workspaces)[0]
    if not isinstance(first, str) or not first:
        return None
    path = Path(first)
    return path if path.is_dir() else None


def _unreadable(problem: str) -> Decision:
    return Decision("deny", f"BLOCKED: {problem}. {HOW_TO_ASK}")


def evaluate(raw: str, root: Path | None = None) -> Decision | None:
    """Parse the payload and decide; any payload that cannot be understood is denied."""
    try:
        loaded: object = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        return _unreadable("research guard could not read the hook payload")
    if not isinstance(loaded, dict):
        return _unreadable("unexpected hook payload")
    data = cast(dict[str, object], loaded)
    raw_call = data.get("toolCall")
    if not isinstance(raw_call, dict):
        return _unreadable("hook payload without toolCall")
    call = cast(dict[str, object], raw_call)
    name = call.get("name")
    if not isinstance(name, str) or not name:
        return _unreadable("hook payload without toolCall.name")
    raw_args = call.get("args", {})
    if not isinstance(raw_args, dict):
        return _unreadable(f"unreadable arguments for {name}")
    args = cast(dict[str, object], raw_args)
    repo = root or _workspace(data) or find_root()
    return decide(name, args, load_allowlist(repo))


def _read_stdin() -> str:
    stream = sys.stdin
    if stream is None:
        return ""
    return stream.buffer.read().decode("utf-8-sig", errors="replace")


def main(
    argv: Sequence[str] | None = None,
    root: Path | None = None,
    *,
    stdin: str | None = None,
) -> int:
    """Hook entry point; `argv` is accepted for interface parity and ignored."""
    del argv
    try:
        raw = _read_stdin() if stdin is None else stdin
        decision = evaluate(raw, root)
    except Exception as exc:  # fail closed: any unexpected error denies the call
        decision = Decision("deny", f"BLOCKED: research guard failed ({type(exc).__name__}).")
    if decision is not None:
        print(decision.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
