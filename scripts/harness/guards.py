"""PreToolUse security and safety guards (stdlib only).

All eight core guards operate solely on normalized `Event` values from `payload.py`
(order of `ALL`, equal to `harness/core.toml [controls] required_guards`):
  1. secret_in_write   block literal secrets or unignored credential files on writes
  2. sensitive_file    block reading/searching sensitive files or ignored paths
  3. privileged_config block agent writes to hooks, core.toml, MCP configs, or ~/.gemini/config/
  4. dangerous_shell   block destructive git, rm, PowerShell, or cmd commands
  5. data_egress       block outbound file uploads, pipes to network clients, scp/rsync uploads
  6. exfil_url         block auto-loading URLs or curl commands carrying encoded payloads
  7. subagent_routing  enforce light model routing and prevent heavy model subagent runaway
  8. harness_integrity protect harness scripts, validate Python syntax, snapshot incremental edits

`harness_integrity` MUST remain last in `ALL` so blocked calls never create recovery snapshots.
`privileged_config` also keeps blocking hook files of other agents (`.claude/settings*.json`,
`.codex/hooks.json`, `.kiro/hooks/*.json`) as defense in depth when they exist on the machine.
"""

from __future__ import annotations

import ast
import fnmatch
import os
import posixpath
import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import check_secrets
import check_untrusted
import cli
import config
from payload import Event

REPO_ROOT = config.REPO_ROOT
FULL_WRITE_TOOLS = frozenset({"write_to_file", "write_file"})

_RUNNER_SHELLS = frozenset({"sh", "bash", "bash.exe", "zsh", "dash", "ksh"})
_RUNNER_PWSH = frozenset({"pwsh", "pwsh.exe", "powershell", "powershell.exe"})
_EVAL_VERBS = frozenset({"eval", "iex", "invoke-expression"})
_START_PROCESS_VERBS = frozenset({"start-process", "saps", "start"})
_START_PROCESS_VALUE_FLAGS = frozenset(
    {
        "-workingdirectory",
        "-verb",
        "-windowstyle",
        "-redirectstandardoutput",
        "-redirectstandarderror",
        "-redirectstandardinput",
        "-credential",
    }
)
_START_PROCESS_SWITCH_FLAGS = frozenset(
    {
        "-wait",
        "-nonewwindow",
        "-passthru",
        "-usenewenvironment",
        "-loaduserprofile",
        "-whatif",
        "-confirm",
    }
)
_PWSH_VALUE_EXACT = frozenset({"-ep", "-w", "-wd", "-of", "-if"})
# Unique prefixes (>= min_len) of PowerShell host parameters that consume the next argument.
_PWSH_VALUE_PREFIXES: tuple[tuple[int, str], ...] = (
    (3, "-executionpolicy"),
    (3, "-windowstyle"),
    (3, "-workingdirectory"),
    (3, "-outputformat"),
    (3, "-inputformat"),
    (5, "-configurationname"),
    (2, "-version"),
    (3, "-custompipename"),
    (3, "-settingsfile"),
)
# `-Method:Post`; the name part has no dot or slash, so URLs and paths are never split.
_PWSH_COLON_PARAM_RE = re.compile(r"^(-[A-Za-z][A-Za-z0-9]*):(.+)$")
_REDIR_TOKEN_RE = re.compile(r"^(?:&|\d+|\*)?(>>|>\||<>|<<<|>|<)(.*)$")
_FD_DUP_RE = re.compile(r"^&(?:\d+|-)$")
_WIN_SWITCH_RE = re.compile(r"^/-?[A-Za-z]{1,16}(?::.*)?$")
_WIN_CMD_FILE_VERBS = frozenset(
    {"copy", "move", "xcopy", "del", "erase", "rd", "rmdir", "ren", "rename", "robocopy"}
)
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
_FIND_NAME_OPTS = frozenset({"-name", "-iname", "-path", "-ipath", "-wholename"})
_PRIVILEGED_BASENAMES = (
    "hooks.json",
    "core.toml",
    "baseline.json",
    ".mcp.json",
    "mcp.json",
    "mcp_config.json",
)
_QUOTED_TEXT_RE = re.compile(r"[\"']([^\"']+)[\"']")
_RUNNER_CMD = frozenset({"cmd", "cmd.exe"})
_WRAPPER_PREFIXES = frozenset({"timeout", "sudo", "env", "xargs", "nohup", "nice", "command"})
_WRAPPER_VALUE_OPTS: dict[str, frozenset[str]] = {
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "sudo": frozenset(
        {
            "-u",
            "--user",
            "-g",
            "--group",
            "-h",
            "--host",
            "-p",
            "--prompt",
            "-r",
            "--role",
            "-t",
            "--type",
            "-U",
            "--other-user",
            "-C",
            "--close-from",
            "-T",
            "--command-timeout",
        }
    ),
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "--argv0"}),
    "xargs": frozenset(
        {
            "-n",
            "--max-args",
            "-P",
            "--max-procs",
            "-L",
            "--max-lines",
            "-I",
            "--replace",
            "-d",
            "--delimiter",
            "-E",
            "--eof",
            "-a",
            "--arg-file",
            "-s",
            "--max-chars",
        }
    ),
    "nice": frozenset({"-n", "--adjustment"}),
}
_TIMEOUT_DURATION_RE = re.compile(r"^\d+(?:\.\d+)?[smhdSMHD]?$")
_READ_ONLY_CMDS = frozenset(
    {
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "get-content",
        "gc",
        "type",
        "ls",
        "dir",
        "find",
        "rg",
        "grep",
        "ag",
        "ack",
        "pytest",
        "ruff",
        "pyright",
        "echo",
        "printf",
        "write-output",
    }
)
_SEARCH_CMDS = frozenset({"rg", "grep", "ag", "ack", "egrep", "fgrep"})
_PROSE_CMDS = frozenset({"echo", "printf", "write-output", "write-host"})
_NETWORK_UPLOAD_CMDS = frozenset({"nc", "ncat", "netcat", "socat", "telnet"})
_PWSH_WEB_CMDS = frozenset({"invoke-webrequest", "invoke-restmethod", "iwr", "irm"})
_PWSH_UPLOAD_PARAMS = ("-infile", "-body", "-form")
# Commands that only read their file arguments; for them only output redirections can write.
_READ_ONLY_INSPECTORS = frozenset({"jq", "wc", "select-string", "sls", "findstr", "diff", "fc"})
_GIT_READ_SUBCOMMANDS = frozenset(
    {"diff", "log", "show", "status", "blame", "grep", "ls-files", "cat-file", "rev-parse"}
)
_REMOVE_OR_MOVE_VERBS = frozenset(
    {
        "rm",
        "mv",
        "del",
        "erase",
        "ren",
        "rename",
        "rd",
        "rmdir",
        "unlink",
        "remove-item",
        "ri",
        "move-item",
        "mi",
        "rename-item",
        "rni",
    }
)
_MOVE_OR_COPY_VERBS = frozenset(
    {"mv", "move-item", "mi", "cp", "copy", "copy-item", "cpi", "xcopy", "robocopy"}
)
_PWSH_ITEM_VERBS = frozenset(
    {"remove-item", "ri", "move-item", "mi", "copy-item", "cpi", "rename-item", "rni"}
)
_WINDOWS_SYNTAX_WRAPPERS = (
    _RUNNER_CMD | _RUNNER_PWSH | _START_PROCESS_VERBS | frozenset({"iex", "invoke-expression"})
)
_WINDOWS_SYNTAX_VERBS = (
    _WINDOWS_SYNTAX_WRAPPERS
    | _WIN_CMD_FILE_VERBS
    | _PWSH_ITEM_VERBS
    | _PWSH_WEB_CMDS
    | frozenset(
        {
            "type",
            "dir",
            "findstr",
            "fc",
            "get-content",
            "gc",
            "set-content",
            "sc",
            "add-content",
            "ac",
            "clear-content",
            "clc",
            "out-file",
            "select-string",
            "sls",
            "write-output",
            "write-host",
            "invoke-command",
            "icm",
        }
    )
)
# Folders whose removal or replacement disables the harness: the repository root, the hook
# folder, the baseline folder and the runtime folders (see `_protected_parent`).
_PRIVILEGED_PARENTS = (".", ".agents", "harness")
_PROTECTED_PARENTS = ("scripts", "scripts/harness")
# curl short options are case-sensitive (-F form vs -f fail, -T upload vs -t telnet, -d data vs
# -D dump-header), so they are compared exactly; long options are compared case-insensitively.
_CURL_UPLOAD_SHORT_FLAGS = frozenset({"-d", "-F", "-T"})
_CURL_UPLOAD_FLAGS = frozenset(
    {
        "--data",
        "--data-raw",
        "--data-binary",
        "--data-urlencode",
        "--data-ascii",
        "--json",
        "--form",
        "--form-string",
        "--upload-file",
    }
)
_CURL_UPLOAD_PREFIXES = ("-d", "-F", "-T", "--data=", "--data-binary=", "--upload-file=", "--form=")

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", re.IGNORECASE)
_HTML_AUTO_URL_RE = re.compile(
    r"<(?:img|iframe|script|link|source|audio|video|object|embed)\b[^>]*?\b"
    r"(?:src|href|data)\s*=\s*[\"'](https?://[^\"'\s>]+)[\"']",
    re.IGNORECASE,
)
_ANY_HTTP_URL_RE = re.compile(r"https?://[^\s\"'<>`]+", re.IGNORECASE)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[/\\]")
_GIT_GLOBAL_VALUE_OPTS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
_INLINE_SHELL_MUTATION_RE = re.compile(
    r"\b(?:unlink|rmdir|rmtree|removedirs|write_text|write_bytes|replace|rename|renames|remove"
    r"|move|copy|copy2|copyfile|copytree|truncate|symlink|link|chmod)\b"
    r"|open\s*\([^)]*[\"'][rbt]*[wax+]",
    re.IGNORECASE,
)
_MUTATING_FILE_VERBS = frozenset(
    {
        "rm",
        "mv",
        "cp",
        "del",
        "erase",
        "ren",
        "rename",
        "remove-item",
        "ri",
        "move-item",
        "mi",
        "copy-item",
        "cpi",
        "set-content",
        "sc",
        "add-content",
        "ac",
        "clear-content",
        "clc",
        "out-file",
        "truncate",
        "unlink",
        "chmod",
        "chown",
        "tee",
        "sed",
        "perl",
    }
)


@dataclass(frozen=True, slots=True)
class _Segment:
    tokens: tuple[str, ...]
    raw_tokens: tuple[str, ...]
    redirections: tuple[str, ...]
    piped_in: bool
    piped_out: bool


def _strip_win32_device_prefix(posix_path: str) -> str:
    """Strip Win32 device/extended-length prefixes (`\\\\?\\`, `\\\\.\\`, `\\\\?\\UNC\\`)."""
    lowered = posix_path.lower()
    if lowered.startswith(("//?/unc/", "//./unc/")):
        return "//" + posix_path[8:]
    if posix_path.startswith(("//?/", "//./")):
        return posix_path[4:]
    return posix_path


def _norm_win_segment(segment: str) -> str:
    if segment in ("", ".", "..") or (len(segment) == 2 and segment[1] == ":"):
        return segment
    if len(segment) >= 2 and segment[0].isalpha() and segment[1] == ":":
        drive, rest = segment[:2], segment[2:]
    else:
        drive, rest = "", segment
    base = rest.split(":", 1)[0] if ":" in rest else rest
    cleaned = base.rstrip(". ") or base
    return f"{drive}{cleaned}"


def _norm_win_segments(posix_path: str) -> str:
    """On Windows, strip trailing dots/spaces and NTFS `:stream` suffixes per segment."""
    if not posix_path or os.name != "nt":
        return posix_path
    has_drive_root = len(posix_path) >= 3 and posix_path[0].isalpha() and posix_path[1:3] == ":/"
    parts = [_norm_win_segment(p) for p in posix_path.split("/")]
    norm = posixpath.normpath("/".join(parts))
    if has_drive_root and len(norm) == 2 and norm[0].isalpha() and norm[1] == ":":
        return f"{norm}/"
    return norm


def _normalize_input_path(path: str) -> str:
    """Return normalized POSIX-slashed path without Win32 device prefixes or NTFS/dot quirks."""
    return _norm_win_segments(_strip_win32_device_prefix(path.replace("\\", "/")))


def _resolve_git_dir(git_marker: Path, wt_root: Path) -> Path | None:
    try:
        lines = git_marker.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not lines:
        return None
    first_line = lines[0].strip()
    if not first_line.startswith("gitdir:"):
        return None
    raw_gitdir = first_line[len("gitdir:") :].strip()
    if not raw_gitdir:
        return None
    gitdir = Path(raw_gitdir)
    if not gitdir.is_absolute():
        gitdir = wt_root / gitdir
    try:
        return gitdir.resolve()
    except OSError:
        return None


def _linked_worktree_root(resolved_candidate: Path, resolved_root: Path) -> Path | None:
    """Return the worktree root if `resolved_candidate` is inside a worktree of `resolved_root`."""
    try:
        worktrees_dir = (resolved_root / ".git" / "worktrees").resolve()
    except OSError:
        return None
    for ancestor in (resolved_candidate, *resolved_candidate.parents):
        git_marker = ancestor / ".git"
        try:
            if git_marker.is_dir():
                return None
            if not git_marker.is_file():
                continue
        except OSError:
            return None
        resolved_gitdir = _resolve_git_dir(git_marker, ancestor)
        if resolved_gitdir is None:
            return None
        if resolved_gitdir != worktrees_dir and resolved_gitdir.is_relative_to(worktrees_dir):
            return ancestor
        return None
    return None


def repo_relative(path: str, cwd: str, root: Path = REPO_ROOT) -> str | None:
    """Return POSIX path relative to `root` (or linked worktree), or None if outside."""
    if not path:
        return None
    normalized = _normalize_input_path(path)
    candidate = Path(normalized)
    if not candidate.is_absolute():
        base = _normalize_input_path(cwd) if cwd else ""
        candidate = Path(base or root) / candidate
    try:
        resolved_candidate = candidate.resolve()
        resolved_root = root.resolve()
    except OSError:
        return None
    try:
        rel = resolved_candidate.relative_to(resolved_root).as_posix()
        return _norm_win_segments(rel)
    except ValueError:
        wt_root = _linked_worktree_root(resolved_candidate, resolved_root)
        if wt_root is None:
            return None
        try:
            rel = resolved_candidate.relative_to(wt_root.resolve()).as_posix()
        except (OSError, ValueError):
            return None
        return _norm_win_segments(rel)


def _norm_case(value: str) -> str:
    return value.lower() if os.name == "nt" else value


def _has_short_flag(token: str, letter: str) -> bool:
    """True for single-dash flag clusters containing `letter` (`-f`, `-rf`, `-uf`)."""
    return token.startswith("-") and not token.startswith("--") and letter in token[1:]


def _split_top_level(command: str, *, windows_syntax: bool = False) -> list[tuple[str, bool, bool]]:
    """Split shell command into (segment_text, piped_in, piped_out) respecting quotes."""
    posix_mode = os.name != "nt" and not windows_syntax
    segments: list[tuple[str, bool, bool]] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    prev_piped = False
    i = 0
    length = len(command)

    def _flush(piped_out: bool) -> None:
        nonlocal prev_piped
        text = "".join(buf).strip()
        buf.clear()
        if text:
            segments.append((text, prev_piped, piped_out))
        prev_piped = piped_out

    while i < length:
        ch = command[i]
        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and not in_single and posix_mode:
            buf.append(ch)
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "\n" or ch == ";":
                _flush(False)
                i += 1
                continue
            if command.startswith(("&&", "||"), i):
                _flush(False)
                i += 2
                continue
            if ch == "|":
                if buf and buf[-1] == ">":
                    buf.append(ch)
                else:
                    _flush(True)
                i += 1
                continue
            if ch == "&":
                _flush(False)
                i += 1
                continue
        buf.append(ch)
        i += 1

    _flush(False)
    return segments


def _tokenize(segment: str, *, windows_syntax: bool = False) -> tuple[list[str], list[str]]:
    """Return (tokens, raw_tokens) surviving unbalanced quotes safely."""
    posix_mode = os.name != "nt" and not windows_syntax
    raw: list[str] = []
    clean: list[str] = []
    current_raw: list[str] = []
    current_clean: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    has_token = False

    def _finish() -> None:
        nonlocal has_token
        if has_token or current_raw:
            raw.append("".join(current_raw))
            clean.append("".join(current_clean))
            current_raw.clear()
            current_clean.clear()
            has_token = False

    for ch in segment:
        if escaped:
            current_raw.append(ch)
            current_clean.append(ch)
            escaped = False
            has_token = True
            continue
        if ch == "\\" and not in_single and posix_mode:
            current_raw.append(ch)
            escaped = True
            has_token = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            current_raw.append(ch)
            has_token = True
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            current_raw.append(ch)
            has_token = True
            continue
        if ch.isspace() and not in_single and not in_double:
            _finish()
            continue
        if (
            ch in (">", "<")
            and not in_single
            and not in_double
            and current_raw
            and not re.fullmatch(r"(?:\d+|\*|&|>|<)+", "".join(current_raw))
        ):
            _finish()
        current_raw.append(ch)
        current_clean.append(ch)
        has_token = True

    _finish()
    # On POSIX, shlex succeeds on clean quoting; fallback already handles unbalanced quotes
    if posix_mode:
        try:
            lexer = shlex.shlex(segment, posix=True, punctuation_chars=False)
            lexer.whitespace_split = True
            lexer.commenters = ""
            parsed = list(lexer)
            if len(parsed) == len(raw):
                return parsed, raw
        except ValueError:
            pass
    return clean, raw


def _extract_redirections(tokens: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate redirection targets (`<file`, `3> file`, `*> file`, `&> file`) from args."""
    args: list[str] = []
    redirs: list[str] = []
    expect_target = False
    for tok in tokens:
        if expect_target:
            if not _FD_DUP_RE.match(tok):
                redirs.append(tok)
            expect_target = False
            continue
        match = _REDIR_TOKEN_RE.match(tok)
        if match:
            target = match.group(2)
            if not target:
                expect_target = True
            elif not _FD_DUP_RE.match(target):
                redirs.append(target)
            continue
        args.append(tok)
    return tuple(args), tuple(redirs)


def _inline_subshells(segment: str, *, windows_syntax: bool = False) -> list[str]:
    """Extract commands embedded in backticks or $(...) outside single quotes."""
    posix_mode = os.name != "nt" and not windows_syntax
    found: list[str] = []
    in_single = False
    in_double = False
    i = 0
    length = len(segment)
    while i < length:
        ch = segment[i]
        if ch == "\\" and not in_single and posix_mode:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if not in_single:
            if ch == "`":
                end = segment.find("`", i + 1)
                if end != -1:
                    found.append(segment[i + 1 : end])
                    i = end + 1
                    continue
            if segment.startswith("$(", i):
                depth = 1
                j = i + 2
                while j < length and depth > 0:
                    if segment[j] == "(":
                        depth += 1
                    elif segment[j] == ")":
                        depth -= 1
                    j += 1
                if depth == 0:
                    found.append(segment[i + 2 : j - 1])
                    i = j
                    continue
        i += 1
    return found


def _strip_outer_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _unescape_posix_split_arg(raw_val: str) -> str:
    stripped = _strip_outer_quotes(raw_val)
    if stripped != raw_val:
        return stripped
    # POSIX outer shell unescapes `\ ` before passing argv to `env -S`, which splits on spaces.
    return raw_val.replace("\\ ", " ") if os.name != "nt" else raw_val


def _wrapper_opt_step(tok: str, value_opts: frozenset[str]) -> int:
    """Return token stride (`2` if option consumes the next token, else `1`), handling clusters."""
    if tok in value_opts:
        return 2
    if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2:
        short_vals = {opt[1] for opt in value_opts if len(opt) == 2 and opt.startswith("-")}
        for idx, ch in enumerate(tok[1:]):
            if ch in short_vals:
                return 2 if idx == len(tok) - 2 else 1
    return 1


def _scan_env_args(tokens: Sequence[str], *, allow_split_string: bool) -> tuple[int, str | None]:
    """Skip leading `env` options and `VAR=VAL` entries; optionally unwrap `-S`/`--split-string`."""
    value_opts = _WRAPPER_VALUE_OPTS["env"]
    pos = 0
    while pos < len(tokens):
        raw_tok = tokens[pos]
        tok = raw_tok.strip("\"'")
        if tok == "--":
            return pos + 1, None
        if allow_split_string:
            split_inner = _unwrap_env_split_string(raw_tok, tokens[pos + 1 :])
            if split_inner is not None:
                return pos, split_inner
        if tok.startswith("-"):
            pos += _wrapper_opt_step(tok, value_opts)
            continue
        if _ENV_ASSIGN_RE.match(tok):
            pos += 1
            continue
        break
    return pos, None


def _unwrap_env_split_string(raw_tok: str, tail: Sequence[str]) -> str | None:
    """Extract the inner command from `env -S ...` or `env --split-string=...`."""
    tok = _strip_outer_quotes(raw_tok)
    extracted: str | None = None
    rest_tail: Sequence[str] = tail
    if tok.startswith("--split-string="):
        extracted = _unescape_posix_split_arg(tok.partition("=")[2])
    elif tok == "--split-string":
        if not tail:
            return None
        extracted = _unescape_posix_split_arg(tail[0])
        rest_tail = tail[1:]
    elif tok.startswith("-") and not tok.startswith("--") and "S" in tok[1:]:
        before_s, _, rest_flag = tok[1:].partition("S")
        if set(before_s) <= {"i", "0", "v"}:
            if rest_flag.startswith("="):
                extracted = _unescape_posix_split_arg(rest_flag[1:])
            elif rest_flag:
                extracted = _unescape_posix_split_arg(rest_flag)
            elif tail:
                extracted = _unescape_posix_split_arg(tail[0])
                rest_tail = tail[1:]
            else:
                return None
    if extracted is None:
        return None
    tail_parts = [_unescape_posix_split_arg(p) for p in rest_tail]
    raw_inner = " ".join(part for part in (extracted, *tail_parts) if part)
    if not raw_inner:
        return None
    inner_clean, inner_raw = _tokenize(raw_inner, windows_syntax=True)
    start, _ = _scan_env_args(inner_clean, allow_split_string=False)
    return " ".join(inner_raw[start:]) or None


def _raw_tail_args(raw_tokens: Sequence[str], *, split_params: bool = True) -> list[str]:
    """Return raw post-verb tokens without redirections, leading env assigns, or grouping."""
    prep = _split_param_values(raw_tokens) if split_params else raw_tokens
    raw_args, _ = _extract_redirections(_ungroup(prep))
    raw_idx = 0
    while raw_idx < len(raw_args) and _ENV_ASSIGN_RE.match(raw_args[raw_idx]):
        raw_idx += 1
    return list(raw_args[raw_idx + 1 :])


def _unwrap_wrapper(seg: _Segment) -> str | None:
    """If `seg` executes an inner shell script or command via a wrapper, return the inner text."""
    args = seg.tokens
    idx = 0
    while idx < len(args) and _ENV_ASSIGN_RE.match(args[idx]):
        idx += 1
    if idx >= len(args):
        return None
    verb = Path(args[idx].replace("\\", "/")).name.lower()
    rest = list(args[idx + 1 :])

    if verb in _RUNNER_SHELLS:
        for pos, tok in enumerate(rest):
            if _has_short_flag(tok, "c") and pos + 1 < len(rest):
                return rest[pos + 1]
    if verb in _RUNNER_PWSH:
        return _pwsh_inner_command(rest)
    if verb in _RUNNER_CMD:
        for pos, tok in enumerate(rest):
            if tok.lower() in ("/c", "/k") and pos + 1 < len(rest):
                return " ".join(rest[pos + 1 :])
    if verb in _EVAL_VERBS and rest:
        if rest[0].lower() in ("-command", "-c"):
            rest = rest[1:]
        inner = " ".join(rest).strip()
        # PowerShell `iex (cmd)` runs the grouped pipeline first; inspect it as a command.
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        return inner or None
    if verb in _START_PROCESS_VERBS:
        return _start_process_command(_raw_tail_args(seg.raw_tokens, split_params=False))
    if verb in _WRAPPER_PREFIXES:
        raw_rest = _raw_tail_args(seg.raw_tokens)
        if verb == "env":
            pos, split_inner = _scan_env_args(raw_rest, allow_split_string=True)
            if split_inner is not None:
                return split_inner
            return " ".join(raw_rest[pos:]) if pos < len(raw_rest) else None
        value_opts = _WRAPPER_VALUE_OPTS.get(verb, frozenset())
        pos = 0
        while pos < len(raw_rest):
            tok = raw_rest[pos].strip("\"'")
            if tok == "--":
                pos += 1
                break
            if verb == "timeout" and _TIMEOUT_DURATION_RE.match(tok):
                pos += 1
                continue
            if tok.startswith("-"):
                pos += _wrapper_opt_step(tok, value_opts)
                continue
            break
        if pos < len(raw_rest):
            return " ".join(raw_rest[pos:])
    return None


def _is_pwsh_value_flag(tok: str) -> bool:
    return tok in _PWSH_VALUE_EXACT or any(
        len(tok) >= min_len and full.startswith(tok) for min_len, full in _PWSH_VALUE_PREFIXES
    )


def _pwsh_scan(rest: Sequence[str]) -> tuple[str | None, bool]:
    """Return `(inner_command, uses_encoded_command)` while respecting outer host flags only."""
    pos = 0
    while pos < len(rest):
        tok = rest[pos].lower()
        if tok == "-c" or (len(tok) >= 3 and "-command".startswith(tok)):
            return (" ".join(rest[pos + 1 :]) or None), False
        if tok == "-f" or (len(tok) >= 2 and "-file".startswith(tok)):
            return None, False  # remaining args belong to the script on disk
        if _is_pwsh_value_flag(tok):
            pos += 2
            continue
        if _is_encoded_flag(tok):
            return None, True
        if tok == "--":
            pos += 1
            return (" ".join(rest[pos:]) or None), False
        if tok.startswith("-"):
            pos += 1
            continue
        return (" ".join(rest[pos:]) or None), False
    return None, False


def _pwsh_inner_command(rest: Sequence[str]) -> str | None:
    """The command `pwsh`/`powershell` runs: `-Command x`, or the first positional argument."""
    inner, _ = _pwsh_scan(rest)
    return inner


def _quote_cmd_arg(arg: str) -> str:
    lowered = arg.lower()
    if (
        not arg
        or not any(ch.isspace() for ch in arg)
        or arg.startswith("-")
        or lowered.startswith(("/c ", "/k "))
    ):
        return arg
    if "'" not in arg:
        return f"'{arg}'"
    if '"' not in arg:
        return f'"{arg}"'
    escaped = arg.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def _split_win_arg(raw_tok: str, *, split_commas: bool) -> list[str]:
    """Strip quotes without consuming backslashes; optionally split unquoted commas."""
    items: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    saw_quote = False
    i = 0
    length = len(raw_tok)
    while i < length:
        ch = raw_tok[i]
        if quote is None:
            if ch in ("'", '"'):
                quote = ch
                saw_quote = True
            elif split_commas and ch == ",":
                part = "".join(buf)
                if part:
                    items.append(part)
                buf.clear()
            else:
                buf.append(ch)
        elif ch == quote:
            if i + 1 < length and raw_tok[i + 1] == quote:
                buf.append(ch)
                i += 2
                continue
            quote = None
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf)
    if split_commas:
        if tail:
            items.append(tail)
    elif tail or saw_quote:
        items.append(tail)
    return items


def _strip_paren_array_tok(tok: str, depth: int) -> tuple[str, int]:
    """Advance paren depth over one PowerShell array token, stopping before the outer `)`."""
    buf: list[str] = []
    quote: str | None = None
    for ch in tok:
        if quote is not None:
            if ch == quote:
                quote = None
            buf.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
            buf.append(ch)
        else:
            buf.append(ch)
    return "".join(buf), depth


def _consume_start_process_arg_list(rest: Sequence[str], start: int) -> tuple[list[str], int]:
    """Collect `-ArgumentList` or positional array items (`'-c','rm'` or `@('-c', 'rm')`)."""
    if start >= len(rest):
        return [], start
    first = rest[start]
    if first.startswith(("@(", "(")):
        items: list[str] = []
        depth = 1
        pos = start
        pending = first[2:] if first.startswith("@(") else first[1:]
        while pos < len(rest) and depth > 0:
            tok = pending if pos == start else rest[pos]
            cleaned, depth = _strip_paren_array_tok(tok, depth)
            if cleaned:
                items.extend(_split_win_arg(cleaned, split_commas=True))
            pos += 1
        return items, pos
    items = []
    pos = start
    while pos < len(rest):
        raw_item = rest[pos]
        items.extend(_split_win_arg(raw_item, split_commas=True))
        pos += 1
        if not raw_item.endswith(",") and not (pos < len(rest) and rest[pos].startswith(",")):
            break
    return items, pos


def _start_process_command(rest: Sequence[str]) -> str | None:
    """`Start-Process <file> -ArgumentList <args>` runs `<file> <args>`."""
    file_path = ""
    arg_items: list[str] = []
    positional: list[str] = []
    pos = 0
    while pos < len(rest):
        tok = rest[pos]
        colon_match = _PWSH_COLON_PARAM_RE.match(tok)
        if colon_match:
            param, inline_val = colon_match.groups()
            param_lower = param.lower()
            if param_lower in ("-filepath", "-file", "-path"):
                val_parts = _split_win_arg(inline_val, split_commas=False)
                file_path = val_parts[0] if val_parts else ""
                pos += 1
                continue
            if param_lower in ("-argumentlist", "-args", "-arguments", "-arg"):
                parsed_args, rel_pos = _consume_start_process_arg_list(
                    [inline_val, *rest[pos + 1 :]], 0
                )
                arg_items.extend(parsed_args)
                pos += rel_pos
                continue
            pos += 1
            continue
        tok_parts = _split_win_arg(tok, split_commas=False)
        tok_clean = tok_parts[0] if tok_parts else ""
        lowered = tok_clean.lower()
        val_parts = _split_win_arg(rest[pos + 1], split_commas=False) if pos + 1 < len(rest) else []
        value = val_parts[0] if val_parts else ""
        if lowered in ("-filepath", "-file", "-path"):
            file_path, pos = value, pos + 2
        elif lowered in ("-argumentlist", "-args", "-arguments", "-arg"):
            parsed_args, pos = _consume_start_process_arg_list(rest, pos + 1)
            arg_items.extend(parsed_args)
        elif lowered in _START_PROCESS_VALUE_FLAGS:
            pos += 2
        elif lowered in _START_PROCESS_SWITCH_FLAGS or (
            lowered.startswith("-") and not file_path and not positional
        ):
            pos += 1
        elif file_path or positional:
            parsed_args, pos = _consume_start_process_arg_list(rest, pos)
            positional.extend(parsed_args)
        else:
            positional.append(tok_clean)
            pos += 1
    if not file_path:
        file_path = positional[0] if positional else ""
        extra_positional = positional[1:]
    else:
        extra_positional = positional
    all_args = [*arg_items, *extra_positional]
    rendered_args = " ".join(_quote_cmd_arg(arg) for arg in all_args if arg)
    return f"{file_path} {rendered_args}".strip() or None


def _is_encoded_flag(tok: str) -> bool:
    """`-EncodedCommand` and the prefixes PowerShell accepts (`-e`, `-enc`, `-ec`, ...)."""
    lowered = tok.lower()
    return lowered == "-ec" or (len(lowered) >= 2 and "-encodedcommand".startswith(lowered))


def _segment_verb(raw_tokens: Sequence[str]) -> str:
    cleaned_tokens = [tok.strip("\"'") for tok in raw_tokens]
    ungrouped = _ungroup(cleaned_tokens)
    idx = 0
    while idx < len(ungrouped) and _ENV_ASSIGN_RE.match(ungrouped[idx]):
        idx += 1
    if idx >= len(ungrouped):
        return ""
    cleaned = ungrouped[idx].replace("\\", "/")
    return cleaned.rsplit("/", 1)[-1].lower()


_POSIX_ONLY_SHELLS = _RUNNER_SHELLS - {"bash.exe"}


def _starts_with_posix_shell(command: str) -> bool:
    _, raw_tokens = _tokenize(command, windows_syntax=True)
    return _segment_verb(raw_tokens) in _POSIX_ONLY_SHELLS


def _is_windows_verb(verb: str) -> bool:
    return verb in _WINDOWS_SYNTAX_VERBS or verb.endswith((".exe", ".bat", ".cmd", ".ps1"))


def _parse_commands(
    command: str, piped_in: bool = False, depth: int = 0, *, windows_syntax: bool = False
) -> list[_Segment]:
    if not command or depth > 5:
        return []
    result: list[_Segment] = []
    for seg_text, seg_piped_in, seg_piped_out in _split_top_level(
        command, windows_syntax=windows_syntax
    ):
        effective_piped_in = piped_in or seg_piped_in
        tokens, raw_tokens = _tokenize(seg_text, windows_syntax=windows_syntax)
        raw_verb = _segment_verb(raw_tokens)
        uses_windows_syntax = windows_syntax or _is_windows_verb(raw_verb)
        if not windows_syntax and os.name != "nt" and uses_windows_syntax:
            resplit = _split_top_level(seg_text, windows_syntax=True)
            if len(resplit) > 1:
                result.extend(
                    _parse_commands(
                        seg_text,
                        piped_in=effective_piped_in,
                        depth=depth + 1,
                        windows_syntax=True,
                    )
                )
                continue
            tokens, raw_tokens = _tokenize(seg_text, windows_syntax=True)
        clean_args, redirs = _extract_redirections(_ungroup(_split_param_values(tokens)))
        seg = _Segment(clean_args, tuple(raw_tokens), redirs, effective_piped_in, seg_piped_out)
        if seg.tokens or seg.redirections:
            result.append(seg)
        for inline in _inline_subshells(seg_text, windows_syntax=uses_windows_syntax):
            result.extend(
                _parse_commands(
                    inline, piped_in=False, depth=depth + 1, windows_syntax=uses_windows_syntax
                )
            )
        unwrapped = _unwrap_wrapper(seg)
        if unwrapped:
            child_windows = (
                uses_windows_syntax
                and (windows_syntax or raw_verb in _WINDOWS_SYNTAX_WRAPPERS)
                and not (os.name != "nt" and _starts_with_posix_shell(unwrapped))
            )
            result.extend(
                _parse_commands(
                    unwrapped,
                    piped_in=effective_piped_in,
                    depth=depth + 1,
                    windows_syntax=child_windows,
                )
            )
    return result


def _split_param_values(tokens: Sequence[str]) -> list[str]:
    """PowerShell `-Param:Value` becomes `-Param`, `Value` so every guard sees both parts."""
    result: list[str] = []
    for tok in tokens:
        match = _PWSH_COLON_PARAM_RE.match(tok)
        if match:
            result.extend((match.group(1), match.group(2)))
        else:
            result.append(tok)
    return result


def _ungroup(tokens: Sequence[str]) -> tuple[str, ...]:
    """Drop scriptblock/grouping delimiters so `& { rm -rf x }` is inspected as `rm -rf x`."""
    toks = list(tokens)
    if len(toks) >= 2 and toks[0] == "." and toks[1][:1] in ("{", "("):
        toks.pop(0)
    if toks and toks[0][:1] in ("{", "("):
        first = toks[0][1:]
        toks[0:1] = [first] if first else []
        if toks and toks[-1][-1:] in ("}", ")"):
            last = toks[-1][:-1]
            toks[-1:] = [last] if last else []
    if toks and "(" in toks[0]:
        # `iex(git reset --hard)`: an eval verb glued to its grouped argument.
        verb, _, rest = toks[0].partition("(")
        if verb.lower() in _EVAL_VERBS:
            toks[0:1] = [verb, "(" + rest]
    return tuple(toks)


def _command_verb(tokens: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    idx = 0
    while idx < len(tokens) and _ENV_ASSIGN_RE.match(tokens[idx]):
        idx += 1
    if idx >= len(tokens):
        return "", ()
    return Path(tokens[idx].replace("\\", "/")).name.lower(), tuple(tokens[idx + 1 :])


_SecretSettings = tuple[tuple[str, ...], tuple[check_secrets.PatternRule, ...], tuple[str, ...]]


def _safe_secret_settings(config_path: Path | None) -> _SecretSettings:
    """Project secret settings; an invalid harness.toml falls back to the builtin patterns."""
    try:
        return check_secrets.load_settings(config_path)
    except config.ConfigError:
        return (), (), ()


def secret_in_write(event: Event, config_path: Path | None = None) -> str | None:
    """Guard 1: block literal secrets on writes, subagents, and in unknown/MCP tool arguments.

    Writes also refuse unignored credential files. For `subagent` tools (invoke_subagent,
    swarm, Agent, Task) and `other` tools (MCP servers, messaging), `payload.parse` puts
    every argument string in `content`, so a secret cannot leave the session or be passed to
    a subagent.
    """
    if event.kind not in ("write", "other", "subagent"):
        return None
    exempt, extra, safe_values = _safe_secret_settings(config_path)
    target_rel = "write" if event.kind == "write" else event.tool or "tool-call"
    for path in event.paths if event.kind == "write" else ():
        name = Path(_normalize_input_path(path)).name
        rel = repo_relative(path, event.cwd, REPO_ROOT) or name
        if check_secrets.is_excluded(rel, name, exempt):
            continue
        target_rel = rel
        if check_secrets.is_sensitive_file(name):
            return f"refusing to write credential file `{name}` via agent tools."
    if not event.content:
        return None
    if (
        event.kind == "write"
        and event.paths
        and all(
            check_secrets.is_excluded(
                repo_relative(p, event.cwd, REPO_ROOT) or Path(_normalize_input_path(p)).name,
                Path(_normalize_input_path(p)).name,
                exempt,
            )
            for p in event.paths
        )
    ):
        return None
    findings = check_secrets.scan_text(event.content, target_rel, extra, safe_values)
    if not findings:
        return None
    summary = ", ".join(f"{f.rule}@L{f.line}" for f in findings[:4])
    return (
        f"content contains potential secret ({summary}); load it from env/ADC or mark a "
        f"proven false positive with `{check_secrets.ALLOW_MARKER}`."
    )


def _is_sensitive_name(token: str) -> bool:
    """Check whether `token` names a sensitive credential file or glob like `.env*`."""
    cleaned = token.strip().strip("\"'").replace("\\", "/")
    if not cleaned:
        return False
    name = cleaned.rsplit("/", 1)[-1]
    # `.ENV`, `.env.` and `.env::$DATA` all open the same NTFS file as `.env`.
    lowered = check_secrets.canonical_name(name)
    if not name or lowered in check_secrets.SENSITIVE_FILE_EXCEPTIONS:
        return False
    if lowered == ".env*" or lowered.startswith(".env.") or lowered == ".env":
        return True
    if any(ch in name for ch in ("(", ")", "{", "}", " ")):
        return False
    if name.startswith("."):
        return False
    return check_secrets.is_sensitive_file(name)


def _shell_sensitive_target(seg: _Segment, cwd: str) -> str | None:
    verb, args = _command_verb(seg.tokens)
    for redir in seg.redirections:
        if _is_sensitive_name(redir):
            return redir
    if not verb:
        return None
    if verb in _PROSE_CMDS:
        return None
    if verb in ("jq", "yq") or verb in _SEARCH_CMDS:
        # The first positional argument is a filter or pattern, not a file.
        candidates = [a for a in args if not a.startswith("-")][1:]
    else:
        candidates = list(args)

    skip_next = False
    for index, tok in enumerate(candidates):
        if skip_next:
            skip_next = False
            continue
        if verb == "git" and tok in ("-m", "--message", "-F"):
            skip_next = True
            continue
        if verb == "git" and tok.startswith("--message="):
            continue
        if verb in ("python", "python3", "py") and tok == "-c":
            if index + 1 < len(candidates):
                code = candidates[index + 1]
                for part in re.findall(r"[\"']([^\"']+)[\"']", code):
                    if _is_sensitive_name(part) and part.lower().startswith(".env"):
                        return part
            skip_next = True
            continue
        if tok.startswith("-") and "," not in tok:
            continue
        for piece in tok.split(","):
            piece = piece.strip()
            if _is_sensitive_name(piece):
                return piece
            cleaned = piece.strip("\"'").replace("\\", "/")
            if cleaned and check_secrets.is_sensitive_file(cleaned.rsplit("/", 1)[-1]):
                base = Path(cwd or REPO_ROOT)
                try:
                    if (base / cleaned).is_file():
                        return piece
                except OSError:
                    pass
    return None


def sensitive_file(event: Event) -> str | None:
    """Guard 2: block reads/searches on credential files or ignored files."""
    if event.include_ignored:
        return "search requested ignored files (`include_ignored=true`); ask the human first."
    if event.kind in ("read", "search"):
        for path in event.paths:
            for piece in path.split(","):
                if _is_sensitive_name(piece):
                    return (
                        f"access to sensitive file `{piece}` is blocked; inspect non-secret "
                        "config or `.env.example`."
                    )
    if event.kind == "shell" and event.command:
        for seg in _parse_commands(event.command):
            hit = _shell_sensitive_target(seg, event.cwd)
            if hit:
                return f"shell access to sensitive file `{hit}` is blocked."
    return None


def _check_git_danger(args: tuple[str, ...]) -> str | None:
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "-c" and i + 1 < len(args):
            if "hookspath" in args[i + 1].lower():
                return (
                    "`git -c core.hooksPath=...` bypasses repository hooks; run with active hooks."
                )
            i += 2
            continue
        if tok in _GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if tok.startswith("-"):
            if tok.startswith("-c") and "hookspath" in tok.lower():
                return "`git -c core.hooksPath=...` bypasses repository hooks."
            i += 1
            continue
        break
    if i >= len(args):
        return None
    sub = args[i]
    rest = args[i + 1 :]

    if sub == "push":
        for tok in rest:
            if tok in ("-f", "--force", "--force-with-lease", "--force-if-includes", "--mirror"):
                return (
                    "`git push` with force/mirror flags can overwrite remote history; "
                    "confirm with human."
                )
            if _has_short_flag(tok, "f"):
                return (
                    f"`git push {tok}` performs a force push; ask the human before rewriting "
                    "remote history."
                )
            if not tok.startswith("-") and tok.startswith(("+", ":")):
                return (
                    f"`git push` refspec `{tok}` rewrites/deletes remote refs; confirm with human."
                )
            if tok == "--delete" or _has_short_flag(tok, "d"):
                return "`git push --delete` deletes remote refs; confirm with the human first."
    elif sub == "reset":
        if "--hard" in rest:
            return "`git reset --hard` discards uncommitted work irreversibly."
    elif sub == "clean":
        has_force = any(t == "--force" or _has_short_flag(t, "f") for t in rest)
        has_dry_run = any(t == "--dry-run" or _has_short_flag(t, "n") for t in rest)
        if has_force and not has_dry_run:
            return (
                "`git clean` with force deletes untracked files irreversibly; run `-n` dry-run "
                "instead."
            )
    elif sub == "branch":
        has_delete = any(t == "--delete" or _has_short_flag(t, "d") for t in rest)
        has_capital_d = any(_has_short_flag(t, "D") for t in rest)
        has_force = has_capital_d or any(t == "--force" or _has_short_flag(t, "f") for t in rest)
        if has_force and (has_delete or has_capital_d):
            return (
                "`git branch -D` force-deletes unmerged branches; use lowercase `-d` or ask human."
            )
    elif sub == "commit":
        skip = False
        for tok in rest:
            if skip:
                skip = False
                continue
            if tok in ("-m", "-F", "-C", "-c", "--message", "--file"):
                skip = True
                continue
            if tok == "--no-verify" or _has_short_flag(tok, "n"):
                return "`git commit --no-verify` bypasses commit hooks."
    elif sub == "config":
        write_flags = {"--unset", "--unset-all", "--add", "--replace-all", "--global", "--system"}
        if any(t in write_flags for t in rest):
            return "modifying git config (`git config` write) requires explicit human approval."
        positional = [t for t in rest if not t.startswith("-")]
        if len(positional) >= 2:
            return (
                "modifying git config (`git config` assignment) requires explicit human approval."
            )
    return None


def dangerous_shell(event: Event) -> str | None:
    """Guard 4: block destructive shell, git, PowerShell, and cmd operations."""
    if event.kind != "shell" or not event.command:
        return None
    for seg in _parse_commands(event.command):
        verb, args = _command_verb(seg.tokens)
        if not verb:
            continue
        if verb in ("git", "git.exe"):
            git_reason = _check_git_danger(args)
            if git_reason:
                return git_reason
        if verb == "rm":
            has_rec = any(
                t == "--recursive" or _has_short_flag(t, "r") or _has_short_flag(t, "R")
                for t in args
            )
            has_force = any(t == "--force" or _has_short_flag(t, "f") for t in args)
            if has_rec and has_force:
                return "`rm -rf` deletes directory trees without confirmation."
        if verb in ("remove-item", "ri"):
            lowered = {t.lower() for t in args}
            has_rec = any(t in lowered for t in ("-recurse", "-r"))
            has_force = any(t in lowered for t in ("-force", "-fo"))
            if has_rec and has_force:
                return "`Remove-Item -Recurse -Force` deletes directory trees without confirmation."
        if verb in ("rd", "rmdir", "del", "erase"):
            lowered = {t.lower() for t in args}
            if "/s" in lowered and "/q" in lowered:
                return f"`{verb} /s /q` deletes directory trees silently."
        if verb in _RUNNER_PWSH and _pwsh_scan(args)[1]:
            return (
                f"`{verb} -EncodedCommand` hides the command from the guards and from review; "
                "run the plain command instead."
            )
    return None


def _is_remote_rsync_or_scp(arg: str) -> bool:
    if ":" not in arg or _DRIVE_LETTER_RE.match(arg):
        return False
    host, _, rest = arg.partition(":")
    if not host or host.startswith(("/", ".", "\\")):
        return False
    return bool(rest or "@" in host)


def data_egress(event: Event) -> str | None:
    """Guard 5: block outbound file uploads, piped network sends, and raw sockets."""
    if event.kind != "shell" or not event.command:
        return None
    for seg in _parse_commands(event.command):
        verb, args = _command_verb(seg.tokens)
        if not verb:
            continue
        if verb in _NETWORK_UPLOAD_CMDS:
            return (
                f"`{verb}` opens raw network channels; verify data handling or save to a local "
                "file instead."
            )
        if verb in ("curl", "curl.exe"):
            reason = _curl_upload(seg, args)
            if reason:
                return reason
        if verb in ("wget", "wget.exe") and (
            seg.piped_in
            or any(
                t.startswith(("--post-file", "--post-data", "--method=POST", "--method=PUT"))
                for t in args
            )
        ):
            return "`wget` upload/POST options are blocked; save or inspect a local file instead."
        # In Windows PowerShell `curl` and `wget` are aliases of Invoke-WebRequest.
        if verb in _PWSH_WEB_CMDS or verb in ("curl", "wget"):
            reason = _pwsh_web_upload(verb, args)
            if reason:
                return reason
        if verb in ("scp", "rsync"):
            positional = [t for t in args if not t.startswith("-")]
            if len(positional) >= 2 and _is_remote_rsync_or_scp(positional[-1]):
                return (
                    f"`{verb}` upload to remote target `{positional[-1]}` is blocked; keep "
                    "artifacts in a local file."
                )
    return None


def _curl_upload(seg: _Segment, args: tuple[str, ...]) -> str | None:
    if seg.piped_in:
        return "piping content into `curl` can exfiltrate data; write to a local file instead."
    for tok in args:
        if (
            tok in _CURL_UPLOAD_SHORT_FLAGS
            or tok.lower() in _CURL_UPLOAD_FLAGS
            or tok.startswith(_CURL_UPLOAD_PREFIXES)
        ):
            return "`curl` upload flags are blocked; inspect or save to a local file instead."
    for i, tok in enumerate(args):
        method = args[i + 1] if tok in ("-X", "--request") and i + 1 < len(args) else ""
        if method.upper() in ("POST", "PUT", "PATCH"):
            return f"`curl -X {method}` outbound write is blocked; use local files instead."
    return None


def _pwsh_param(tok: str, full: str, *, prefixes: bool) -> bool:
    """`tok` names the PowerShell parameter `full`; cmdlets also accept unique prefixes."""
    lowered = tok.lower()
    if lowered == full:
        return True
    return prefixes and len(lowered) >= 2 and full.startswith(lowered)


def _pwsh_web_upload(verb: str, args: tuple[str, ...]) -> str | None:
    # Real cmdlets accept `-Meth`/`-Bo`; the `curl`/`wget` names may be the native tools,
    # whose short flags (`-b` cookie, `-i` include) must not be read as PowerShell prefixes.
    prefixes = verb in _PWSH_WEB_CMDS
    lowered = [t.lower() for t in args]
    for tok in lowered:
        if any(_pwsh_param(tok, name, prefixes=prefixes) for name in _PWSH_UPLOAD_PARAMS):
            return (
                f"`{verb}` upload parameters (`-InFile`/`-Body`/`-Form`) are blocked; write a "
                "local file instead."
            )
    for i, tok in enumerate(lowered):
        is_method = _pwsh_param(tok, "-method", prefixes=prefixes)
        method = lowered[i + 1] if is_method and i + 1 < len(lowered) else ""
        if method in ("post", "put", "patch"):
            return f"`{verb} -Method {method}` is blocked; write a local file instead."
    return None


def _url_payload_finding(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc or "remote host"
    tail = f"{parsed.path}?{parsed.query}#{parsed.fragment}"
    if check_untrusted.has_encoded_payload(tail):
        return (
            f"auto-loading or network reference to `{host}` carries an encoded payload; "
            "save or inspect the content via a local file instead."
        )
    return None


def exfil_url(event: Event) -> str | None:
    """Guard 6: block remote markdown/HTML resource embeds or curl calls carrying encoded blobs."""
    if event.kind == "write" and event.content:
        for match in _MD_IMAGE_RE.finditer(event.content):
            reason = _url_payload_finding(match.group(1))
            if reason:
                return reason
        for match in _HTML_AUTO_URL_RE.finditer(event.content):
            reason = _url_payload_finding(match.group(1))
            if reason:
                return reason
    if event.kind == "shell" and event.command:
        for match in _ANY_HTTP_URL_RE.finditer(event.command):
            reason = _url_payload_finding(match.group(0))
            if reason:
                return reason
    return None


def _is_privileged_target(raw_path: str, cwd: str, root: Path) -> str | None:
    """Return 'hook' | 'MCP' | 'core' | 'baseline' | 'global' if privileged, else None."""
    cleaned = raw_path.strip().strip("\"'")
    if not cleaned:
        return None
    slashed = _strip_win32_device_prefix(cleaned.replace("\\", "/"))
    posix = _norm_win_segments(slashed)
    candidate = Path(posix)
    if not candidate.is_absolute():
        base = _normalize_input_path(cwd) if cwd else ""
        candidate = Path(base or root) / candidate
    try:
        resolved_posix = candidate.resolve().as_posix()
    except OSError:
        resolved_posix = posix

    home_config = _norm_case((Path.home() / ".gemini" / "config").resolve().as_posix())
    resolved_key = _norm_case(_norm_win_segments(resolved_posix))
    if resolved_key == home_config or resolved_key.startswith(home_config + "/"):
        return "global"
    if "/.gemini/config/" in posix or posix.endswith("/.gemini/config"):
        return "global"

    rel = repo_relative(posix, cwd, root)
    target = _norm_win_segments(rel or resolved_posix)
    lower = target.lower()

    if lower == ".github/workflows/harness-verify.yml" or lower.endswith(
        "/.github/workflows/harness-verify.yml"
    ):
        return "hook"
    if lower in (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json"):
        return "hook"
    if fnmatch.fnmatch(lower, ".kiro/hooks/*.json"):
        return "hook"
    if lower == "harness/core.toml" or lower.endswith("/harness/core.toml"):
        return "core"
    if lower == "harness/baseline.json" or lower.endswith("/harness/baseline.json"):
        return "baseline"
    name = lower.rsplit("/", 1)[-1]
    if name.endswith(".json") and "mcp" in name:  # .mcp.json, mcp_config.json, settings/mcp.json
        return "MCP"
    return None


def privileged_config(event: Event, root: Path = REPO_ROOT) -> str | None:
    """Guard 3: keep hooks, harness/core.toml, MCP configs and ~/.gemini/config/ human-owned."""
    if event.kind == "write":
        for path in event.paths:
            category = _is_privileged_target(path, event.cwd, root)
            if category:
                label = {
                    "hook": "hook configuration",
                    "MCP": "MCP server configuration",
                    "core": "harness baseline (`harness/core.toml`)",
                    "baseline": "harness tamper baseline (`harness/baseline.json`)",
                    "global": "global OpenBot configuration (`~/.gemini/config/`)",
                }[category]
                return (
                    f"modifying {label} (`{path}`) requires the human directly "
                    "(see `docs/adr/` security boundaries)."
                )
    if event.kind == "shell" and event.command:
        protected = _privileged_folders(root)
        for seg in _parse_commands(event.command):
            verb, args = _command_verb(seg.tokens)
            mutating_find = verb == "find" and any(a in _FIND_ACTIONS for a in args)
            targets = None if mutating_find else _write_targets(seg, verb, args, event.cwd, root)
            if targets is None:
                extra_git: tuple[str, ...] = ()
                if verb in ("git", "git.exe"):
                    _, git_rest, git_cwd = _git_command(args, event.cwd, root)
                    if git_cwd != (event.cwd or str(root)):
                        extra_git = tuple(
                            _resolve_under(t.strip("\"'"), git_cwd)
                            for t in git_rest
                            if not t.startswith("-")
                        )
                candidates: tuple[str, ...] = (
                    *seg.redirections,
                    *seg.tokens[1:],
                    *extra_git,
                    *_inline_code_targets(verb, args),
                )
            else:
                candidates = targets
            for tok in candidates:
                category = _is_privileged_target(tok, event.cwd, root)
                if category:
                    return (
                        f"shell modification targeting privileged {category} configuration "
                        f"(`{tok}`) requires the human directly (see `docs/adr/`)."
                    )
            pattern = _find_privileged_pattern(args) if mutating_find else None
            if pattern:
                return (
                    f"`find -name {pattern}` with -delete/-exec matches privileged hook, MCP or "
                    "baseline configuration; the human decides (see `docs/adr/`)."
                )
            folder = _protected_parent(
                verb, args, _effective_cwd(verb, args, event.cwd, root), root, protected
            )
            if folder:
                return (
                    f"removing, moving or overwriting `{folder}` would take hook, MCP or baseline "
                    "configuration with it; the human decides (see `docs/adr/`)."
                )
    return None


def _resolve_under(target: str, base_dir: str) -> str:
    cleaned = _strip_win32_device_prefix(target.replace("\\", "/"))
    if not cleaned or not base_dir:
        return cleaned or target
    candidate = Path(cleaned)
    if candidate.is_absolute() or _DRIVE_LETTER_RE.match(cleaned):
        return cleaned
    base = _strip_win32_device_prefix(base_dir.replace("\\", "/"))
    return str(Path(base) / candidate)


def _git_command(
    args: Sequence[str], cwd: str = "", root: Path = REPO_ROOT
) -> tuple[str, tuple[str, ...], str]:
    """Return `(subcommand, rest, effective_cwd)` honoring `git -C <dir>`."""
    effective_cwd = cwd or str(root)
    index = 0
    while index < len(args):
        tok = args[index]
        if tok == "-C" and index + 1 < len(args):
            effective_cwd = _resolve_under(args[index + 1].strip("\"'"), effective_cwd)
            index += 2
        elif tok.startswith("-C") and len(tok) > 2:
            effective_cwd = _resolve_under(tok[2:].strip("\"'"), effective_cwd)
            index += 1
        elif tok in _GIT_GLOBAL_VALUE_OPTS:
            index += 2
        elif tok.startswith("-"):
            index += 1
        else:
            return tok, tuple(args[index + 1 :]), effective_cwd
    return "", (), effective_cwd


def _git_subcommand(args: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    sub, rest, _ = _git_command(args)
    return sub, rest


def _effective_cwd(verb: str, args: Sequence[str], cwd: str, root: Path) -> str:
    if verb in ("git", "git.exe"):
        _, _, git_cwd = _git_command(args, cwd, root)
        return git_cwd
    return cwd


def _git_output_targets(sub: str, rest: Sequence[str], git_cwd: str = "") -> list[str]:
    outputs: list[str] = []
    accept_short_o = sub in ("diff", "show")
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        if tok.startswith("--output="):
            outputs.append(tok.split("=", 1)[1])
        elif (tok == "--output" or (accept_short_o and tok == "-o")) and idx + 1 < len(rest):
            outputs.append(rest[idx + 1])
            idx += 2
            continue
        elif accept_short_o and tok.startswith("-o") and len(tok) > 2:
            outputs.append(tok[2:])
        idx += 1
    if not git_cwd:
        return outputs
    return [_resolve_under(out.strip("\"'"), git_cwd) for out in outputs]


def _json_tool_outfiles(verb: str, args: Sequence[str]) -> tuple[str, ...] | None:
    """Return `python -m json.tool` output file targets, or None for other commands."""
    if verb not in ("python", "python3", "py") or list(args[:2]) != ["-m", "json.tool"]:
        return None
    positional: list[str] = []
    idx = 2
    stop_flags = False
    while idx < len(args):
        tok = args[idx]
        if not stop_flags and tok == "--":
            stop_flags = True
        elif not stop_flags and tok == "--indent":
            idx += 2
            continue
        elif not stop_flags and tok.startswith("-") and tok != "-":
            pass
        else:
            positional.append(tok)
        idx += 1
    return tuple(positional[1:])


def _write_targets(
    seg: _Segment, verb: str, args: Sequence[str], cwd: str = "", root: Path = REPO_ROOT
) -> tuple[str, ...] | None:
    """Tokens a known read-only command may write; None means "inspect every token"."""
    if verb in _READ_ONLY_CMDS or verb in _READ_ONLY_INSPECTORS:
        return seg.redirections
    if verb in ("git", "git.exe"):
        sub, rest, git_cwd = _git_command(args, cwd, root)
        if sub == "grep" and any(t.startswith(("-O", "--open-files-in-pager")) for t in rest):
            return None
        if sub in _GIT_READ_SUBCOMMANDS:
            return (*seg.redirections, *_git_output_targets(sub, rest, git_cwd))
    json_outs = _json_tool_outfiles(verb, args)
    if json_outs is not None:
        return (*seg.redirections, *json_outs)
    return None


def _guarded_basenames() -> tuple[str, ...]:
    return (*_PRIVILEGED_BASENAMES, *(Path(m).name for m in cli.PROTECTED_MODULES))


def _has_glob(token: str) -> bool:
    return any(ch in token for ch in ("*", "?", "["))


def _is_win_switch(tok: str) -> bool:
    return bool(_WIN_SWITCH_RE.match(tok))


def _lexical_abs(token: str, cwd: str, root: Path) -> str:
    """Absolute, normalized POSIX form of `token` without touching the filesystem (globs ok)."""
    text = _normalize_input_path(os.path.expanduser(token.strip("\"'")))
    if not (text.startswith("/") or re.match(r"^[A-Za-z]:", text)):
        base = _normalize_input_path(cwd or str(root)).rstrip("/")
        text = f"{base}/{text}"
    return _norm_case(_norm_win_segments(posixpath.normpath(text)))


def _privileged_folders(root: Path) -> tuple[str, ...]:
    base = _norm_case(root.resolve().as_posix())
    folders = tuple(_norm_case(posixpath.normpath(f"{base}/{p}")) for p in _PRIVILEGED_PARENTS)
    return (*folders, _norm_case((Path.home() / ".gemini" / "config").resolve().as_posix()))


def _protected_folders(root: Path) -> tuple[str, ...]:
    base = _norm_case(root.resolve().as_posix())
    return tuple(_norm_case(posixpath.normpath(f"{base}/{p}")) for p in _PROTECTED_PARENTS)


def _covers(target: str, folder: str) -> bool:
    """`target` is `folder`, one of its ancestors, or a glob matching it."""
    prefix = target if target.endswith("/") else target + "/"
    return target == folder or folder.startswith(prefix) or fnmatch.fnmatchcase(folder, target)


def _find_starts_and_names(args: Sequence[str]) -> tuple[list[str], list[str]]:
    starts: list[str] = []
    for tok in args:
        if tok.startswith("-") or tok in ("(", "!", ")"):
            break
        starts.append(tok)
    names = [
        args[i + 1].strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()
        for i, tok in enumerate(args[:-1])
        if tok.lower() in _FIND_NAME_OPTS
    ]
    return starts or ["."], names


def _split_pwsh_list(token: str) -> list[str]:
    """Expand unquoted comma-separated PowerShell `string[]` elements into items."""
    return [part.strip().strip("\"'") for part in token.split(",") if part.strip().strip("\"'")]


def _removal_and_destinations(
    verb: str, args: Sequence[str]
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return `(removed, sources, destinations, filters)` for file mutation commands."""
    if verb in ("git", "git.exe"):
        sub, rest = _git_subcommand(args)
        if sub == "rm":
            if "--cached" in rest:
                return [], [], [], []
            files = [a for a in rest if not a.startswith("-")]
            return files, files, [], []
        if sub == "mv":
            files = [a for a in rest if not a.startswith("-")]
            if len(files) >= 2:
                return files[:-1], files[:-1], files[-1:], []
        return [], [], [], []
    if verb == "robocopy":
        paths = [a for a in args if not a.startswith("-") and not _is_win_switch(a)]
        flags = {a.lower() for a in args if _is_win_switch(a)}
        dest = paths[1:2]
        purges = bool(flags & {"/mir", "/purge", "/move"})
        return (dest if purges else []), paths[:1], dest, []
    if verb in _PWSH_ITEM_VERBS:
        explicit_paths: list[str] = []
        explicit_dests: list[str] = []
        filters: list[str] = []
        positional: list[str] = []
        idx = 0
        while idx < len(args):
            tok = args[idx]
            low = tok.lower()
            if low in ("-path", "-literalpath", "-lp") and idx + 1 < len(args):
                explicit_paths.extend(_split_pwsh_list(args[idx + 1]))
                idx += 2
            elif low in ("-destination", "-dest") and idx + 1 < len(args):
                explicit_dests.extend(_split_pwsh_list(args[idx + 1]))
                idx += 2
            elif low in ("-include", "-filter") and idx + 1 < len(args):
                filters.extend(_split_pwsh_list(args[idx + 1]))
                idx += 2
            elif low in ("-exclude", "-newname", "-credential") and idx + 1 < len(args):
                idx += 2
            elif tok.startswith("-"):
                idx += 1
            else:
                positional.extend(_split_pwsh_list(tok))
                idx += 1
        if explicit_dests:
            sources, destinations = [*explicit_paths, *positional], explicit_dests
        elif verb in ("move-item", "mi", "copy-item", "cpi"):
            if explicit_paths and positional:
                sources, destinations = explicit_paths, positional[-1:]
            elif len(positional) >= 2:
                sources, destinations = positional[:-1], positional[-1:]
            else:
                sources, destinations = [*explicit_paths, *positional], []
        else:
            sources, destinations = [*explicit_paths, *positional], []
        removed = sources if verb in _REMOVE_OR_MOVE_VERBS else []
        return removed, sources, destinations, filters

    skip_win = verb in _WIN_CMD_FILE_VERBS
    supports_target_dir = verb in ("mv", "cp")
    explicit_dests = []
    positional = []
    idx = 0
    while idx < len(args):
        tok = args[idx]
        if supports_target_dir:
            if tok == "--":
                positional.extend(args[idx + 1 :])
                break
            if tok in ("-t", "--target-directory") and idx + 1 < len(args):
                explicit_dests.append(args[idx + 1])
                idx += 2
                continue
            if tok.startswith("--target-directory="):
                explicit_dests.append(tok.split("=", 1)[1])
                idx += 1
                continue
            if tok.startswith("-t") and len(tok) > 2:
                explicit_dests.append(tok[2:])
                idx += 1
                continue
            if tok in ("-S", "--suffix") and idx + 1 < len(args):
                idx += 2
                continue
        if tok.startswith("-") or (skip_win and _is_win_switch(tok)):
            idx += 1
            continue
        positional.append(tok)
        idx += 1

    if explicit_dests:
        sources, destinations = positional, explicit_dests
    elif verb in _MOVE_OR_COPY_VERBS and len(positional) >= 2:
        sources, destinations = positional[:-1], positional[-1:]
    elif verb in _REMOVE_OR_MOVE_VERBS:
        sources, destinations = positional, []
    else:
        sources, destinations = [], []
    removed = sources if verb in _REMOVE_OR_MOVE_VERBS else []
    return removed, sources, destinations, []


def _is_recursive_transfer(verb: str, args: Sequence[str]) -> bool:
    if verb in ("cp", "mv"):
        return any(
            t in ("--recursive", "--archive")
            or _has_short_flag(t, "r")
            or _has_short_flag(t, "R")
            or _has_short_flag(t, "a")
            for t in args
        )
    if verb in ("copy-item", "cpi", "move-item", "mi"):
        return any(t.lower() in ("-recurse", "-r") for t in args)
    if verb in ("xcopy", "robocopy"):
        return any(t.lower() in ("/s", "/e", "/mir") for t in args)
    return False


def _guarded_files_under(root: Path, folders: Sequence[str]) -> tuple[str, ...]:
    base = _norm_case(root.resolve().as_posix())
    candidates: list[str] = []
    if f"{base}/.agents" in folders:
        candidates.extend(
            f"{base}/.agents/{name}"
            for name in ("hooks.json", ".mcp.json", "mcp.json", "mcp_config.json")
        )
    if f"{base}/harness" in folders:
        candidates.extend(f"{base}/harness/{name}" for name in ("core.toml", "baseline.json"))
    if f"{base}/scripts/harness" in folders:
        candidates.extend(f"{base}/{_norm_case(m)}" for m in cli.PROTECTED_MODULES)
    return tuple(candidates)


def _protected_parent(
    verb: str, args: Sequence[str], cwd: str, root: Path, folders: Sequence[str]
) -> str | None:
    """A removed, moved or overwritten folder that holds privileged or protected files."""
    guarded = _guarded_basenames()
    guarded_abs = _guarded_files_under(root, folders)
    home_cfg = _norm_case((Path.home() / ".gemini" / "config").resolve().as_posix())
    if verb == "find":
        if not any(a in _FIND_ACTIONS for a in args):
            return None
        starts, filters = _find_starts_and_names(args)
        removed, sources, destinations = starts, [], []
    else:
        removed, sources, destinations, filters = _removal_and_destinations(verb, args)
    if filters and not any(
        fnmatch.fnmatchcase(g.lower(), p.lower())
        for p in filters
        for g in (*guarded, "x_mcp_x.json")
    ):
        return None
    for tok in removed:
        target = _lexical_abs(tok, cwd, root)
        if any(_covers(target, folder) for folder in folders):
            return tok
        if _has_glob(target):
            if any(fnmatch.fnmatchcase(g, target) for g in guarded_abs):
                return tok
            if home_cfg in folders and target.startswith(home_cfg + "/"):
                return tok
    brings_guarded = False
    if destinations:
        if verb == "robocopy" or _is_recursive_transfer(verb, args):
            brings_guarded = True
        else:
            for src in sources:
                cleaned_src = src.strip("\"'")
                if cleaned_src in (".", "..") or cleaned_src.endswith(("/", "\\", "/.", "\\.")):
                    brings_guarded = True
                    break
                s_name = Path(cleaned_src.replace("\\", "/")).name.lower()
                if any(
                    fnmatch.fnmatchcase(s_name, pattern) for pattern in (*guarded, "*mcp*.json")
                ) or (
                    _has_glob(s_name)
                    and any(
                        fnmatch.fnmatchcase(g.lower(), s_name)
                        for g in (*guarded, "mcp_config.json")
                    )
                ):
                    brings_guarded = True
                    break
    for tok in destinations if brings_guarded else []:
        target = _lexical_abs(tok, cwd, root)
        if any(target == folder for folder in folders):
            return tok
    return None


def _find_privileged_pattern(args: Sequence[str]) -> str | None:
    """The `-name`/`-path` pattern of a mutating `find` that matches a privileged file name."""
    for index, tok in enumerate(args[:-1]):
        if tok.lower() not in _FIND_NAME_OPTS:
            continue
        pattern = args[index + 1].strip("\"'").replace("\\", "/").rsplit("/", 1)[-1].lower()
        if any(fnmatch.fnmatchcase(name, pattern) for name in _PRIVILEGED_BASENAMES):
            return args[index + 1]
    return None


def _inline_code_targets(verb: str, args: Sequence[str]) -> tuple[str, ...]:
    """Quoted paths inside `python -c` code that mutates files (`os.remove('x')`, ...)."""
    if verb not in ("python", "python3", "py") or "-c" not in args:
        return ()
    code = " ".join(args)
    if not _INLINE_SHELL_MUTATION_RE.search(code):
        return ()
    return tuple(_QUOTED_TEXT_RE.findall(code))


def _resolved_str(path: str, cwd: str, root: Path) -> str:
    candidate = Path(_normalize_input_path(path))
    if not candidate.is_absolute():
        base = _normalize_input_path(cwd) if cwd else ""
        candidate = Path(base or root) / candidate
    return str(candidate)


def _is_protected_script_rel(rel: str | None) -> bool:
    if not rel:
        return False
    norm = _norm_case(rel)
    return norm in cli.NORMALIZED_PROTECTED or norm.startswith("scripts/harness/")


def _is_nested_harness_subpackage(rel: str) -> bool:
    norm = _norm_case(rel)
    prefix = "scripts/harness/"
    return norm.startswith(prefix) and "/" in norm[len(prefix) :]


def _touches_protected_module(seg: _Segment, cwd: str, root: Path) -> str | None:
    verb, args = _command_verb(seg.tokens)
    for redir in seg.redirections:
        rel = repo_relative(redir, cwd, root)
        if _is_protected_script_rel(rel):
            return rel
    if not verb:
        return None
    inline = " ".join(args)
    if (
        verb in ("python", "python3", "py")
        and "-c" in args
        and _INLINE_SHELL_MUTATION_RE.search(inline)
    ):
        for mod in (*cli.PROTECTED_MODULES, "scripts/harness/check_tamper.py"):
            if Path(mod).name in inline or mod in inline:
                return mod
    json_outs = _json_tool_outfiles(verb, args)
    if json_outs is not None:
        for out in json_outs:
            rel = repo_relative(out, cwd, root)
            if _is_protected_script_rel(rel):
                return rel
        return None
    target_cwd = cwd
    inspect_args: Sequence[str] = args
    if verb in ("git", "git.exe"):
        sub, rest, git_cwd = _git_command(args, cwd, root)
        if sub in ("diff", "show", "log"):
            for out in _git_output_targets(sub, rest, git_cwd):
                rel = repo_relative(out, cwd, root)
                if _is_protected_script_rel(rel):
                    return rel
            return None
        if sub not in ("restore", "rm", "mv"):
            return None
        target_cwd = git_cwd
        inspect_args = rest
    elif verb not in _MUTATING_FILE_VERBS:
        return None

    for tok in inspect_args:
        if tok.startswith("-"):
            continue
        cleaned = tok.strip("\"'")
        normalized = cleaned.replace("\\", "/")
        if "scripts/harness" in _norm_case(normalized) or "scripts/harness" in _norm_case(
            _resolved_str(cleaned, target_cwd, root).replace("\\", "/")
        ):
            return cleaned
        rel = repo_relative(_resolve_under(cleaned, target_cwd), cwd, root)
        if _is_protected_script_rel(rel):
            return rel
    return None


_CLAUDE_SUBAGENT_TOOLS = frozenset({"agent", "task"})
_CLAUDE_NATIVE_TYPES = frozenset({"general-purpose", "explore", "plan", "claude"})
_ANTIGRAVITY_NATIVE_TYPES = frozenset({"self", "research"})
_HEAVY_MODEL_TOKENS = frozenset({"fable", "opus", "pro"})
_LIGHT_CLAUDE_TOKENS = frozenset({"haiku", "sonnet"})
_LIGHT_ANTIGRAVITY_MODELS = frozenset({"flash", "flash_lite", "flash-lite"})
_SWARM_READONLY_ACTIONS = frozenset({"status", "models", "title", "kill"})


def _subagent_model_tokens(raw_model: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", raw_model.lower()))


def _is_heavy_model(raw_model: str, tokens: set[str]) -> bool:
    if raw_model.strip().lower() == "inherit":
        return True
    return bool(tokens & _HEAVY_MODEL_TOKENS)


def _is_light_claude(raw_model: str, tokens: set[str]) -> bool:
    if not raw_model or _is_heavy_model(raw_model, tokens):
        return False
    return bool(tokens & _LIGHT_CLAUDE_TOKENS)


def _is_light_antigravity(raw_model: str, tokens: set[str]) -> bool:
    if not raw_model or _is_heavy_model(raw_model, tokens):
        return False
    cleaned = raw_model.strip().lower()
    return cleaned in _LIGHT_ANTIGRAVITY_MODELS or "flash" in tokens


def subagent_routing(event: Event, config_path: Path | None = None) -> str | None:
    """Guard 7: require light models for native subagents, researcher, implementer, and swarm."""
    if event.kind != "subagent":
        return None
    if event.event != "pre":
        return None

    tool = (event.tool or "").strip().lower()
    stype = (event.subagent_type or "").strip().lower()
    raw_model = (event.model or "").strip()
    tokens = _subagent_model_tokens(raw_model)

    if tool == "swarm":
        action = (event.action or "").strip().lower()
        if action in _SWARM_READONLY_ACTIONS:
            return None
        if not _is_light_antigravity(raw_model, tokens):
            act = event.action or "unspecified"
            return f"swarm action `{act}` requires an explicit light model (flash or flash_lite)."
        return None

    if not event.subagent_type:
        return f"subagent tool `{event.tool}` requires a subagent type."

    if tool in _CLAUDE_SUBAGENT_TOOLS:
        if stype in _CLAUDE_NATIVE_TYPES and not _is_light_claude(raw_model, tokens):
            return (
                f"native subagent `{event.subagent_type}` needs an explicit light model "
                "(sonnet or haiku); or use the implementer / researcher subagents."
            )
        return None

    if tool == "invoke_subagent":
        if stype in _ANTIGRAVITY_NATIVE_TYPES:
            if not _is_light_antigravity(raw_model, tokens):
                return (
                    f"native subagent `{event.subagent_type}` needs an explicit light model "
                    "(flash or flash_lite); or use the implementer / researcher subagents."
                )
            return None
        if stype == "researcher":
            if not _is_light_antigravity(raw_model, tokens):
                return (
                    "subagent `researcher` requires an explicit light model (flash or flash_lite)."
                )
            return None
        if stype == "implementer":
            if not (_is_light_antigravity(raw_model, tokens) or raw_model.lower() == "inherit"):
                return (
                    "subagent `implementer` requires an explicit model "
                    "(flash, flash_lite, or inherit for tier escalation)."
                )
            return None
        return None

    return None


_PROTECTED_BRANCHES = frozenset({"main", "master"})
_GIT_PUSH_VALUE_OPTS = frozenset({"-o", "--push-option", "--repo", "--receive-pack", "--exec"})


def _read_git_branch(git_dir: Path) -> str:
    head_path = git_dir / "HEAD"
    try:
        head_text = head_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    prefix = "ref: refs/heads/"
    if head_text.startswith(prefix):
        return head_text[len(prefix) :].strip()
    return ""


def _worktree_info(path: Path) -> tuple[Path, bool, str] | None:
    """Return `(wt_root, is_linked, branch)` for the enclosing git worktree, or None."""
    try:
        resolved = path.resolve()
    except OSError:
        return None
    for ancestor in (resolved, *resolved.parents):
        git_marker = ancestor / ".git"
        try:
            if git_marker.is_dir():
                return ancestor, False, _read_git_branch(git_marker)
            if not git_marker.is_file():
                continue
        except OSError:
            return None
        resolved_gitdir = _resolve_git_dir(git_marker, ancestor)
        if resolved_gitdir is None:
            return None
        return ancestor, True, _read_git_branch(resolved_gitdir)
    return None


def _is_protected_ref(ref: str) -> bool:
    cleaned = ref.strip()
    if cleaned.startswith("refs/heads/"):
        cleaned = cleaned[len("refs/heads/") :]
    return cleaned in _PROTECTED_BRANCHES


def _push_positional_args(rest: Sequence[str]) -> list[str]:
    positional: list[str] = []
    idx = 0
    stop_flags = False
    while idx < len(rest):
        tok = rest[idx]
        if not stop_flags and tok == "--":
            stop_flags = True
            idx += 1
            continue
        if not stop_flags and tok in _GIT_PUSH_VALUE_OPTS and idx + 1 < len(rest):
            idx += 2
            continue
        if not stop_flags and tok.startswith("-"):
            idx += 1
            continue
        positional.append(tok)
        idx += 1
    return positional


def _check_git_workflow_push(rest: Sequence[str], target_dir: Path) -> str | None:
    positional = _push_positional_args(rest)
    refspecs = positional[1:] if len(positional) >= 2 else []
    info = _worktree_info(target_dir)

    if len(positional) == 1 and _is_protected_ref(positional[0]):
        return (
            f"pushing `{positional[0]}` directly is blocked; push a feature branch from a "
            "linked worktree."
        )

    for refspec in refspecs:
        cleaned = refspec.lstrip("+")
        if ":" in cleaned:
            src, _, dst = cleaned.partition(":")
            parts: tuple[str, ...] = (src, dst)
        else:
            parts = (cleaned,)
        for part in parts:
            if _is_protected_ref(part):
                return (
                    f"pushing to or from protected branch `{part}` is blocked; push a feature "
                    "branch instead."
                )
        if parts[0] == "HEAD" and info is not None:
            _, is_linked, branch = info
            if not is_linked or branch in _PROTECTED_BRANCHES:
                return (
                    "pushing `HEAD` from the main checkout or a protected branch is blocked; "
                    "switch to a feature branch in a linked worktree."
                )

    if not refspecs and info is not None:
        _, is_linked, branch = info
        if branch in _PROTECTED_BRANCHES:
            return (
                f"pushing from protected branch `{branch}` is blocked; switch to a feature "
                "branch in a linked worktree."
            )
        if not is_linked:
            return (
                "pushing without an explicit feature branch from the main checkout is blocked; "
                "work from a dedicated git worktree."
            )
    return None


def git_workflow(event: Event, root: Path = REPO_ROOT) -> str | None:
    """Guard 8: enforce linked git worktree isolation and protect main/master branches."""
    if event.kind == "write":
        for path in event.paths:
            resolved = _resolved_str(path, event.cwd, root)
            info = _worktree_info(Path(resolved))
            if info is None:
                continue
            _, is_linked, branch = info
            if not is_linked:
                return (
                    "edits must happen in a dedicated git worktree (`git worktree add "
                    "../wt-<repo>-<slug> -b feat/<slug> main`); see skill git-worktree-flow."
                )
            if branch in _PROTECTED_BRANCHES:
                return (
                    f"edits on branch `{branch}` are blocked; switch to a feature branch in "
                    "a linked worktree."
                )
    if event.kind == "shell" and event.command:
        for seg in _parse_commands(event.command):
            verb, args = _command_verb(seg.tokens)
            if verb not in ("git", "git.exe"):
                continue
            sub, rest, git_cwd = _git_command(args, event.cwd, root)
            target_dir = Path(_normalize_input_path(git_cwd))
            if sub == "commit":
                info = _worktree_info(target_dir)
                if info is None:
                    continue
                _, is_linked, branch = info
                if not is_linked:
                    return (
                        "commits must happen in a dedicated git worktree (`git worktree add "
                        "../wt-<repo>-<slug> -b feat/<slug> main`), not the main checkout."
                    )
                if branch in _PROTECTED_BRANCHES:
                    return (
                        f"commits on branch `{branch}` are blocked; switch to a feature branch "
                        "in a linked worktree."
                    )
            elif sub == "push":
                reason = _check_git_workflow_push(rest, target_dir)
                if reason:
                    return reason
    return None


def harness_integrity(
    event: Event,
    root: Path = REPO_ROOT,
    state_dir: Path = cli.STATE_DIR,
    now: float | None = None,
) -> str | None:
    """Guard 9: validate syntax on full writes, protect cli.py, and journal incremental edits."""
    if event.kind == "write":
        cli_rel = _norm_case("scripts/harness/cli.py")
        resolved_inputs = [_resolved_str(p, event.cwd, root) for p in event.paths]
        for raw, resolved in zip(event.paths, resolved_inputs, strict=True):
            rel = repo_relative(resolved, event.cwd, root)
            if not rel or not _is_protected_script_rel(rel):
                continue
            if _is_nested_harness_subpackage(rel):
                return (
                    f"refusing write to `{raw}` inside protected `scripts/harness/` because "
                    "nested subpackages can shadow harness modules."
                )
            if _norm_case(rel) == cli_rel:
                return (
                    f"edits to `{raw}` (`scripts/harness/cli.py`) require the human because "
                    "cli.py owns harness fail-closed recovery."
                )
            if event.tool in FULL_WRITE_TOOLS and rel.endswith(".py") and event.content:
                try:
                    ast.parse(event.content, filename=rel)
                except SyntaxError as exc:
                    return (
                        f"refusing full write to protected harness module `{rel}` with invalid "
                        f"Python syntax (line {exc.lineno}: {exc.msg})."
                    )
        cli.prepare_integrity_snapshot(
            resolved_inputs,
            event.session_id,
            root=root,
            state_dir=state_dir,
            now=now,
        )
    if event.kind == "shell" and event.command:
        folders = _protected_folders(root)
        for seg in _parse_commands(event.command):
            verb, args = _command_verb(seg.tokens)
            hit = _touches_protected_module(seg, event.cwd, root) or _protected_parent(
                verb, args, _effective_cwd(verb, args, event.cwd, root), root, folders
            )
            if hit:
                return (
                    f"mutating protected harness path `{hit}` from shell is blocked; ask the human "
                    "to review or use verified edits."
                )
    return None


_PR_MCP_TOOL_SUBSTRINGS = ("create_pull_request", "open_pull_request", "create_pr")


def pr_confirmation(event: Event) -> str | None:
    """Confirm guard: require explicit human confirmation before creating a Pull Request."""
    tool_lower = event.tool.lower()
    if any(marker in tool_lower for marker in _PR_MCP_TOOL_SUBSTRINGS):
        return (
            f"opening a Pull Request via `{event.tool}` requires explicit human confirmation "
            "at the end of the task."
        )
    if event.kind == "shell" and event.command:
        for seg in _parse_commands(event.command):
            verb, args = _command_verb(seg.tokens)
            if not verb:
                continue
            verb_lower = verb.lower()
            args_lower = tuple(a.lower() for a in args)
            if verb_lower in ("gh", "gh.exe"):
                positional = [a for a in args_lower if not a.startswith("-")]
                if len(positional) >= 2 and positional[0] == "pr" and positional[1] == "create":
                    return (
                        "`gh pr create` opens a Pull Request; ask the human for explicit "
                        "confirmation first."
                    )
            all_tokens = (verb_lower, *args_lower)
            if (
                any(tok.endswith("pr_via_rest_api.py") for tok in all_tokens)
                and "--request-approval" not in args_lower
            ):
                return (
                    "`pr_via_rest_api.py` opens a Pull Request; run with `--request-approval` "
                    "or obtain explicit human confirmation first."
                )
            if (
                any(tok.endswith("watch_worktree.py") for tok in all_tokens)
                and "publish" in args_lower
            ):
                return (
                    "`watch_worktree.py publish` pushes and opens a Draft PR; confirm with "
                    "the human first."
                )
    return None


ALL = (
    secret_in_write,
    sensitive_file,
    privileged_config,
    dangerous_shell,
    data_egress,
    exfil_url,
    subagent_routing,
    git_workflow,
    harness_integrity,
)

CONFIRM = (pr_confirmation,)
