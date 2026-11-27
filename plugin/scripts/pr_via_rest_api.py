"""Create a GitHub Pull Request via HTTPS REST API using git credential fill (stdlib only).

Designed for environments where `gh` is unavailable or GitHub MCP lacks private-repo access.
Reads the token in memory from `git credential fill`, never passes it via argv, environment
variables, or logs, enforces TLS verification (`ssl.create_default_context()`), sets an explicit
timeout, and sanitizes all error messages.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl

# Bandit B404: only `git` commands run, with fixed argv lists and no shell.
import subprocess  # nosec B404
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

DEFAULT_BASE = "main"
DEFAULT_HOST = "github.com"
DEFAULT_TIMEOUT = 30
GIT_TIMEOUT = 15
_SLUG_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")


class PrError(RuntimeError):
    """Sanitized failure while preparing or submitting a Pull Request."""


def sanitize_secrets(text: str, secrets: Sequence[str]) -> str:
    """Replace any literal or URL-encoded secret occurrences in `text` with `[REDACTED]`."""
    cleaned = text
    for secret in secrets:
        if not secret:
            continue
        cleaned = cleaned.replace(secret, "[REDACTED]")
        encoded = urllib.parse.quote(secret, safe="")
        if encoded and encoded != secret:
            cleaned = cleaned.replace(encoded, "[REDACTED]")
    return cleaned


def _run_git(
    args: Sequence[str],
    *,
    repo_root: Path,
    stdin_text: str | None = None,
    timeout: int = GIT_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-c", "core.fsmonitor=false", "-C", str(repo_root), *args]
    try:
        # Bandit B603, B607: fixed argv without a shell; `git` is the user's own tool on PATH.
        return subprocess.run(  # nosec B603 B607
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PrError(f"git command failed: {exc}") from exc


GitRunner = Callable[..., subprocess.CompletedProcess[str]]


def read_git_credential(
    host: str,
    repo_root: Path,
    *,
    git_runner: GitRunner = _run_git,
) -> str:
    """Read `password` for `https://<host>` in memory via `git credential fill`."""
    if not _HOST_RE.match(host):
        raise PrError(f"invalid host `{host}`")
    proc = git_runner(
        ["credential", "fill"],
        repo_root=repo_root,
        stdin_text=f"protocol=https\nhost={host}\n\n",
    )
    if proc.returncode != 0:
        raise PrError("git credential fill failed")
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1].strip()
            if token:
                return token
    raise PrError(f"no credential password returned by git credential fill for `{host}`")


def detect_current_branch(repo_root: Path, *, git_runner: GitRunner = _run_git) -> str:
    proc = git_runner(["rev-parse", "--abbrev-ref", "HEAD"], repo_root=repo_root)
    if proc.returncode != 0:
        raise PrError("could not detect current git branch")
    branch = proc.stdout.strip()
    if not branch or branch == "HEAD":
        raise PrError("detached HEAD: pass --head <branch> explicitly")
    return branch


def parse_github_slug(remote_url: str, *, expected_host: str = DEFAULT_HOST) -> str:
    """Extract `owner/repo` from an HTTPS or SSH git remote URL."""
    url = remote_url.strip()
    if url.startswith("git@"):
        host_part, sep, path_part = url[4:].partition(":")
        if not sep or host_part != expected_host:
            raise PrError(f"remote host `{host_part}` does not match `{expected_host}`")
        slug = path_part.removesuffix(".git").strip("/")
    else:
        parsed = urllib.parse.urlparse(url)
        host_part = (parsed.hostname or "").lower()
        if host_part != expected_host.lower():
            raise PrError(f"remote host `{host_part}` does not match `{expected_host}`")
        slug = parsed.path.removesuffix(".git").strip("/")
    if not _SLUG_RE.match(slug):
        raise PrError(f"could not parse owner/repo from remote `{url}`")
    return slug


def detect_repo_slug(
    repo_root: Path,
    *,
    expected_host: str = DEFAULT_HOST,
    git_runner: GitRunner = _run_git,
) -> str:
    proc = git_runner(["remote", "get-url", "origin"], repo_root=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise PrError("could not read git remote `origin`; pass --repo owner/repo")
    return parse_github_slug(proc.stdout.strip(), expected_host=expected_host)


def _api_endpoint(host: str, slug: str) -> str:
    if host.lower() == "github.com":
        return f"https://api.github.com/repos/{slug}/pulls"
    return f"https://{host}/api/v3/repos/{slug}/pulls"


def _default_urlopen(
    request: urllib.request.Request, *, timeout: int, context: ssl.SSLContext
) -> Any:
    # Bandit B310: URL scheme is validated to be `https://` and TLS context is verified.
    return urllib.request.urlopen(request, timeout=timeout, context=context)  # nosec B310


def create_pull_request(
    *,
    title: str,
    base: str = DEFAULT_BASE,
    head: str | None = None,
    body: str = "",
    draft: bool = False,
    repo: str | None = None,
    repo_root: Path | None = None,
    host: str = DEFAULT_HOST,
    timeout: int = DEFAULT_TIMEOUT,
    git_runner: GitRunner = _run_git,
    opener: Callable[..., Any] = _default_urlopen,
) -> dict[str, object]:
    """Create a Pull Request via GitHub REST API without leaking credentials."""
    root = (Path.cwd() if repo_root is None else repo_root).resolve()
    clean_title = title.strip()
    clean_base = base.strip()
    if not clean_title:
        raise PrError("--title must be a non-empty string")
    if not clean_base:
        raise PrError("--base must be a non-empty string")
    if timeout <= 0:
        raise PrError("--timeout must be a positive integer")
    if not _HOST_RE.match(host):
        raise PrError(f"invalid host `{host}`")

    clean_head = (
        head.strip() if head is not None else detect_current_branch(root, git_runner=git_runner)
    )
    if not clean_head:
        raise PrError("--head must be a non-empty string")
    if clean_head == clean_base:
        raise PrError(f"--head (`{clean_head}`) cannot equal --base (`{clean_base}`)")

    slug = (
        repo.strip()
        if repo is not None
        else detect_repo_slug(root, expected_host=host, git_runner=git_runner)
    )
    if not _SLUG_RE.match(slug):
        raise PrError(f"invalid --repo `{slug}` (expected owner/repo)")

    url = _api_endpoint(host, slug)
    if not url.startswith("https://"):
        raise PrError("only HTTPS endpoints are allowed")

    token = read_git_credential(host, root, git_runner=git_runner)
    payload = {
        "title": clean_title,
        "head": clean_head,
        "base": clean_base,
        "body": body,
        "draft": draft,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-harness-pr-via-rest-api/1.0",
        },
    )
    context = ssl.create_default_context()
    try:
        with opener(request, timeout=timeout, context=context) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        if exc.fp is not None:
            detail = exc.fp.read().decode("utf-8", errors="replace")
        safe_detail = sanitize_secrets(detail, (token,))
        raise PrError(f"GitHub API returned HTTP {exc.code}: {safe_detail[:400]}") from None
    except urllib.error.URLError as exc:
        safe_reason = sanitize_secrets(str(exc.reason), (token,))
        raise PrError(f"GitHub API request failed: {safe_reason}") from None
    except OSError as exc:
        safe_msg = sanitize_secrets(str(exc), (token,))
        raise PrError(f"GitHub API request failed: {safe_msg}") from None

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise PrError(f"GitHub API returned invalid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise PrError("GitHub API response must be a JSON object")
    return cast("dict[str, object]", parsed)


def format_approval_request(
    *,
    title: str,
    base: str = DEFAULT_BASE,
    head: str | None = None,
    body: str = "",
    repo_root: Path | None = None,
    git_runner: GitRunner = _run_git,
) -> str:
    """Format a human PR approval request locally without credentials or network calls."""
    root = (Path.cwd() if repo_root is None else repo_root).resolve()
    clean_title = title.strip()
    clean_base = base.strip()
    if not clean_title:
        raise PrError("--title must be a non-empty string")
    if not clean_base:
        raise PrError("--base must be a non-empty string")
    clean_head = (
        head.strip() if head is not None else detect_current_branch(root, git_runner=git_runner)
    )
    if not clean_head:
        raise PrError("--head must be a non-empty string")

    proc = git_runner(["log", f"{clean_base}..HEAD", "--oneline"], repo_root=root)
    commits = (
        proc.stdout.strip()
        if proc.returncode == 0 and proc.stdout.strip()
        else "(sem commits locais)"
    )
    body_block = body.strip() or "(sem descrição adicional)"
    return (
        "=== SOLICITACAO DE APROVACAO DE PR ===\n"
        f"Titulo: {clean_title}\n"
        f"Branches: {clean_base} <- {clean_head}\n"
        f"Commits:\n{commits}\n"
        f"Descricao:\n{body_block}\n"
        "Acao: aguarde aprovação explícita do humano e informe --approved-by e --approval-ref."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a GitHub Pull Request via REST API using git credential fill."
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="target base branch (default: main)")
    parser.add_argument("--head", default=None, help="source branch (default: current git branch)")
    parser.add_argument("--title", required=True, help="Pull Request title")
    body_group = parser.add_mutually_exclusive_group()
    body_group.add_argument("--body", default="", help="Pull Request description text")
    body_group.add_argument("--body-file", type=Path, default=None, help="file with PR description")
    parser.add_argument("--draft", action="store_true", help="create Pull Request as draft")
    parser.add_argument(
        "--request-approval",
        action="store_true",
        help="print PR approval request locally without network calls",
    )
    parser.add_argument(
        "--approved-by",
        default="",
        help="human approver identifier required before opening PR",
    )
    parser.add_argument(
        "--approval-ref",
        default="",
        help="approval message ID or link required before opening PR",
    )
    parser.add_argument("--repo", default=None, help="GitHub repository slug (owner/repo)")
    parser.add_argument("--repo-root", type=Path, default=None, help="local git repository root")
    parser.add_argument("--host", default=DEFAULT_HOST, help="GitHub host (default: github.com)")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds"
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    git_runner: GitRunner = _run_git,
    opener: Callable[..., Any] = _default_urlopen,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2

    body_text = args.body
    if args.body_file is not None:
        try:
            body_text = args.body_file.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"ERROR: could not read --body-file: {exc}", file=sys.stderr)
            return 1

    if args.request_approval:
        try:
            summary = format_approval_request(
                title=args.title,
                base=args.base,
                head=args.head,
                body=body_text,
                repo_root=args.repo_root,
                git_runner=git_runner,
            )
        except PrError as exc:
            print(f"PR APPROVAL REQUEST FAILED: {exc}", file=sys.stderr)
            return 1
        print(summary)
        return 0

    approver = args.approved_by.strip()
    approval_ref = args.approval_ref.strip()
    if not approver or not approval_ref:
        print(
            "ERROR: --approved-by and --approval-ref are required to open a PR "
            "(run with --request-approval first and wait for explicit human approval).",
            file=sys.stderr,
        )
        return 2

    approval_footer = f"Aprovado por {approver} ({approval_ref})"
    final_body = (
        f"{body_text.rstrip()}\n\n{approval_footer}" if body_text.strip() else approval_footer
    )

    try:
        result = create_pull_request(
            title=args.title,
            base=args.base,
            head=args.head,
            body=final_body,
            draft=args.draft,
            repo=args.repo,
            repo_root=args.repo_root,
            host=args.host,
            timeout=args.timeout,
            git_runner=git_runner,
            opener=opener,
        )
    except PrError as exc:
        print(f"PR CREATION FAILED: {exc}", file=sys.stderr)
        return 1

    number = result.get("number", "?")
    html_url = result.get("html_url", "")
    print(f"PR CREATED: #{number} {html_url}".strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
