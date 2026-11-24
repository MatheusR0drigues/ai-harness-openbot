"""Hook dispatcher for OpenBot (IDE, CLI, and 2.0) - stdlib only.

Hookless OpenBot builds run CI verification instead; direct CLI invocation:
  python scripts/harness/cli.py hook <event> --agent openbot
reading the JSON payload from stdin.

Events:
  pre              PreToolUse: run all 7 guards; fail closed with `{"decision": "deny"}`
                   on violations/errors; silent exit 0 on allowed calls (NEVER `allow`).
  post             PostToolUse: clear transactional integrity snapshot and print `{}`.
  pre-invocation   PreInvocation: print `{}`.
  post-invocation  PostInvocation: print `{}`.
  stop             Stop: honor terminal reasons immediately; otherwise run `verify --fast`
                   up to MAX_CONTINUATIONS attempts, then return `{"decision": "stop"}`.
  session-start    SessionStart: validate harness config and the controls baseline; emit
                   `injectSteps` only when there is a warning.

Why the Stop counter is persisted per conversation (and never reset by `continuationActive`):
the OpenBot IDE never sends `continuationActive`, so a Stop caused by our own
`{"decision": "continue"}` looks exactly like the end of a fresh user turn. Resetting the
counter whenever `continuationActive` is false would restart the cycle on every IDE Stop and
loop forever. The counter file in STATE_DIR is therefore the only loop bound: it resets when
`verify --fast` passes or a terminal `terminationReason` ends the chain, and after giving up it
stays above MAX_CONTINUATIONS so later failing Stops end the session instead of continuing.
`model_stop` and `NO_TOOL_CALL` are normal model endings, not terminal reasons.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import cli
import config
import guards
import payload
from config import ConfigError
from payload import Event, PayloadError

REPO_ROOT = config.REPO_ROOT
STATE_DIR = Path(tempfile.gettempdir()) / "ai-harness"
MAX_CONTINUATIONS = 2

TERMINAL_REASONS = frozenset(
    {
        "USER_CANCELED",
        "ERROR",
        "error",
        "MAX_INVOCATIONS",
        "MAX_FORCED_INVOCATIONS",
        "MAX_TOKEN_BUDGET_EXCEEDED",
        "max_steps_exceeded",
        "TERMINAL_STEP_TYPE",
        "TERMINAL_CUSTOM_HOOK",
        "INJECTED_RESPONSE",
    }
)

Guard = Callable[[Event], "str | None"]
VerifyFn = Callable[[], tuple[bool, str]]
NoticeFn = Callable[[], "str | None"]
GUARDS: tuple[Guard, ...] = guards.ALL

UNREADABLE_HINT = (
    "The harness blocks tool calls it cannot inspect. If this keeps happening, the agent's hook "
    "payload format changed: tell the human (see docs/agent-setup.md, payload inspection)."
)


@dataclass(frozen=True, slots=True)
class Response:
    code: int
    stdout: str = ""
    stderr: str = ""


def block(reason: str) -> Response:
    """OpenBot deny contract; also used for unknown agents so a typo still fails closed."""
    return Response(0, json.dumps({"decision": "deny", "reason": reason}))


def handle_pre(event: Event, active_guards: Sequence[Guard]) -> Response:
    for guard in active_guards:
        name = getattr(guard, "__name__", "guard")
        try:
            reason = guard(event)
        except Exception as exc:  # fail closed: a broken guard must not let the call through
            return block(f"BLOCKED by harness: guard `{name}` failed ({exc}).")
        if reason:
            return block(f"BLOCKED by harness ({name}): {reason}")
    return Response(0)


def fast_verify() -> tuple[bool, str]:
    try:
        cfg = config.load()
    except ConfigError as exc:
        return False, f"HARNESS CONFIG INVALID: {exc}"
    import verify

    return verify.run_gates(verify.select_gates(cfg.gates, fast=True), verify.subprocess_runner)


def _counter_file(state_dir: Path, session: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", session or "default")[:100]
    return state_dir / f"stop-{safe}.count"


def _read_count(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_count(path: Path, count: int) -> None:
    if count == 0:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(count), encoding="utf-8")


def default_tamper_notice(root: Path | None = None) -> str | None:
    """Warn when `harness/core.toml` or `scripts/harness/*.py` drift."""
    target = REPO_ROOT if root is None else root
    try:
        import check_tamper
    except Exception as exc:
        return (
            "Harness: the tamper baseline could not be checked "
            f"(check_tamper.py failed to import: {type(exc).__name__}: {exc})."
        )
    try:
        if not check_tamper.should_enforce_in_repo(target):
            return None
        return check_tamper.notice(target)
    except Exception as exc:
        return f"Harness: the tamper baseline check failed ({type(exc).__name__}: {exc})."


def handle_stop(
    event: Event,
    verify_fn: VerifyFn,
    state_dir: Path,
    tamper_fn: NoticeFn = default_tamper_notice,
) -> Response:
    counter = _counter_file(state_dir, event.session_id)
    tamper_reason = tamper_fn()
    if tamper_reason:
        _write_count(counter, 0)
        return Response(
            0, json.dumps({"decision": "stop", "reason": tamper_reason}), stderr=tamper_reason
        )
    if event.termination_reason in TERMINAL_REASONS:
        _write_count(counter, 0)
        return Response(0, json.dumps({"decision": "stop"}))

    count = _read_count(counter)
    ok, report = verify_fn()
    if ok:
        _write_count(counter, 0)
        return Response(0, json.dumps({"decision": "stop"}))

    count += 1
    if count > MAX_CONTINUATIONS:
        # Keep count above cap until verify passes so IDE runs never restart the cycle forever.
        _write_count(counter, count)
        message = (
            f"Harness: `verify --fast` still fails; gave up after {MAX_CONTINUATIONS} automatic "
            f"attempts. Report the failure to the human instead of claiming done.\n{report}"
        )
        return Response(0, json.dumps({"decision": "stop", "reason": message}), message)

    _write_count(counter, count)
    reason = (
        f"The harness fast gate failed after your changes (automatic attempt {count}/"
        f"{MAX_CONTINUATIONS}). Fix the cause shown below before finishing; do not weaken gates "
        f"or tests.\n{report}"
    )
    return Response(0, json.dumps({"decision": "continue", "reason": reason}))


def handle_post(_event: Event) -> Response:
    return Response(0, "{}")


def handle_invocation(_event: Event) -> Response:
    return Response(0, "{}")


def _controls_notice(cfg: config.HarnessConfig) -> str | None:
    """Warn when gates or guards required by `[controls]` are missing (check_controls.py)."""
    try:
        import check_controls
    except Exception as exc:  # a missing or broken auditor must never crash SessionStart
        return (
            "Harness: the controls baseline could not be checked "
            f"(check_controls.py failed to import: {type(exc).__name__}: {exc})."
        )
    try:
        problems = check_controls.check(cfg, [g.__name__ for g in guards.ALL])
    except Exception as exc:
        return f"Harness: the controls baseline check failed ({type(exc).__name__}: {exc})."
    if not problems:
        return None
    details = "\n".join(f"- {problem}" for problem in problems)
    return (
        "Harness controls baseline is not intact; restore it or record the removal in an ADR "
        f"under docs/adr/:\n{details}"
    )


def default_config_notice(config_path: Path | None = None, root: Path | None = None) -> str | None:
    target = config.CONFIG_PATH if config_path is None else config_path
    resolved_root = (
        (target.parent if config_path is not None else REPO_ROOT) if root is None else root
    )
    tamper_msg = default_tamper_notice(resolved_root)
    if not target.is_file():
        missing = (
            "Harness: `harness.toml` not found in this repository. "
            "Run `python scripts/harness/cli.py init`."
        )
        return f"{missing}\n\n{tamper_msg}" if tamper_msg else missing
    try:
        cfg = config.load(target)
    except ConfigError as exc:
        invalid = f"Harness config invalid (`harness.toml`): {exc}"
        return f"{invalid}\n\n{tamper_msg}" if tamper_msg else invalid
    controls_msg = _controls_notice(cfg)
    notices = [msg for msg in (controls_msg, tamper_msg) if msg]
    return "\n\n".join(notices) or None


def handle_session_start(_event: Event, notice_fn: NoticeFn = default_config_notice) -> Response:
    message = notice_fn()
    if not message:
        return Response(0, "{}")
    body = {"injectSteps": [{"systemMessage": {"systemMessage": message}}]}
    return Response(0, json.dumps(body))


def run(
    agent: str,
    event_name: str,
    raw: str,
    guards_seq: Sequence[Guard] = GUARDS,
    *,
    verify_fn: VerifyFn = fast_verify,
    state_dir: Path = STATE_DIR,
    notice_fn: NoticeFn = default_config_notice,
    tamper_fn: NoticeFn = default_tamper_notice,
) -> Response:
    try:
        event = payload.parse(agent, event_name, raw)
    except RecursionError:
        exc = PayloadError("payload is nested too deeply to inspect")
        if event_name == "pre":
            return block(f"BLOCKED: harness could not read the hook payload ({exc}).")
        return Response(1, stderr=f"WARNING: harness hook skipped ({exc}).")
    except PayloadError as exc:
        if event_name == "pre":
            return block(
                f"BLOCKED: harness could not read the hook payload ({exc}). {UNREADABLE_HINT}"
            )
        return Response(1, stderr=f"WARNING: harness hook skipped ({exc}).")

    if event.event == "post":
        try:
            cli.clear_integrity_snapshot(event.session_id)
        except OSError as exc:
            return Response(
                1, stderr=f"WARNING: harness could not clear its integrity journal ({exc})."
            )
        return handle_post(event)
    if event.event == "pre":
        return handle_pre(event, guards_seq)
    if event.event == "stop":
        return handle_stop(event, verify_fn, state_dir, tamper_fn)
    if event.event in ("pre-invocation", "post-invocation"):
        return handle_invocation(event)
    return handle_session_start(event, notice_fn)


def parse_args(argv: Sequence[str]) -> tuple[str, str]:
    """Manual parsing on purpose: argparse exits with 2 on usage errors."""
    args = list(argv)
    event = args[0] if args else ""
    agent = ""
    if "--agent" in args:
        index = args.index("--agent")
        agent = args[index + 1] if index + 1 < len(args) else ""
    return event, agent


def main(argv: Sequence[str] | None = None) -> int:
    event, agent = parse_args(sys.argv[1:] if argv is None else argv)
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    response = run(agent, event, raw)
    if response.stdout:
        sys.stdout.write(response.stdout + "\n")
    if response.stderr:
        sys.stderr.write(response.stderr + "\n")
    return response.code


if __name__ == "__main__":
    sys.exit(main())
