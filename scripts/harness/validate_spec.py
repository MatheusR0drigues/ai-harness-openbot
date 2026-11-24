"""Single gate for spec documents in specs/<feature>/ (stdlib only, Python >= 3.11).

Self-contained on purpose: this file also ships byte-identical as plugin/scripts/validate_spec.py
in the global OpenBot plugin, where no other harness module sits next to it.

Layout: specs/<feature>/{requirements.md, design.md, tasks.md, progress.md}. Only the phase files
that exist are checked, so a Specify-phase spec may hold just requirements.md.

Spec folder rules:
- A folder without any entry has not started yet and is valid (ADR-0003); a folder holding any
  file, even a dotfile placeholder, is a spec and must follow the rules below.
- Any other folder needs requirements.md (or bugfix.md for a bugfix spec): design.md, tasks.md or
  progress.md without it is an error, because the Specify phase comes first.
- progress.md is a free-form log and bugfix.md has no fixed shape: neither is parsed, and tasks of
  a bugfix spec are not cross-checked against requirement ids.
- Fenced code blocks are ignored in every file. Inline code spans are ignored when looking for the
  EARS keyword and for vague terms, so `--fast` or a quoted `SHALL` never counts as prose.

requirements.md (PT-BR or EN):
- `### Requisito <n>[: title]` or `### Requirement <n>[: title]` sections with unique numbers.
- Each section has a `**História:**`, `**Historia:**` or `**User Story:**` line and a
  `#### Critérios de Aceite`, `#### Criterios de Aceite` or `#### Acceptance Criteria` heading
  followed by a numbered list with unique numbers. Criterion k of requirement n has id `n.k`;
  requirement n itself has id `n`.
- Every criterion contains an uppercase EARS keyword `DEVE`, `DEVEM` or `SHALL`
  (QUANDO/ENQUANTO/SE/ONDE ... DEVE; WHEN/WHILE/IF/WHERE ... SHALL) and no word of VAGUE_TERMS.
  Indented, non-blank lines without a Markdown marker continue the criterion above (ADR-0006).
- The document has a `## Fora de Escopo` or `## Out of Scope` section.
design.md: a `## Segurança`, `## Seguranca` or `## Threat Model` section (more words may follow).
tasks.md:
  - [ ] 1. Top-level task            `[x]` = done, `[-]` or `[~]` = in progress
    - [ ]* 1.1 Optional sub-task       `*` right after the box marks the task optional
      - _Requisitos: 1.1, 2.3_         or `_Requirements: ..._`: criteria the task covers
      - _Depende de: 1_                or `_Depends on: ..._`: tasks this one needs
- Task ids are unique and the parent of a sub-task (`2` for `2.1`) exists.
- Every referenced requirement id exists in requirements.md (when that file exists).
- A dependency names an existing, earlier task: no self, unknown or forward dependency. Depending
  on another task's parent (e.g. `_Depends on: 1_` from task 2) is allowed.
- A mandatory task never depends on an optional one (marked `*` itself or under a `*` parent).
- No dependency cycle (DFS in `find_cycle`). A parent task implicitly depends on its sub-tasks, so
  a sub-task that depends on its own parent is reported as a cycle.

Usage:
  python scripts/harness/validate_spec.py --all            # every specs/*/ of the repository
  python scripts/harness/validate_spec.py specs/<feature>  # one spec folder (or a file in it)
The repository root is the first folder at or above the working directory that contains `.git`
(the working directory itself when there is none). `--all` validates each specs/*/ folder of that
root except names starting with `_` or `.` (templates) and passes when specs/ does not exist. A
relative spec path is looked up in the working directory first, then under the repository root.
Problems print as `file:line: message`, or `file: message` when a whole section is missing.
Exit code: 0 when every spec is valid, 1 otherwise (usage errors included).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

USAGE = "usage: validate_spec.py --all | <spec-dir>"
SPECS_DIRNAME = "specs"
BOM = "\ufeff"
EXCERPT_CHARS = 100

REQUIREMENT_HEADING = re.compile(
    r"^###\s+(?:Requisito|Requirement)\b[ \t]*(?P<number>\d+)?", re.IGNORECASE
)
USER_STORY = re.compile(r"\*\*(?:História|Historia|User Story):\*\*", re.IGNORECASE)
CRITERIA_HEADING = re.compile(
    r"^#{2,6}\s+(?:Critérios de Aceite|Criterios de Aceite|Acceptance Criteria)\b",
    re.IGNORECASE,
)
SECTION_NUMBER = r"(?:\d+(?:\.\d+)*\.?\s+)?"  # optional `5.` / `5.1` prefix in numbered docs
OUT_OF_SCOPE_HEADING = re.compile(
    r"^#{2,6}\s+" + SECTION_NUMBER + r"(?:Fora de Escopo|Out of Scope)\b", re.IGNORECASE
)
SECURITY_HEADING = re.compile(
    r"^#{2,6}\s+" + SECTION_NUMBER + r"(?:Segurança|Seguranca|Threat Model)\b", re.IGNORECASE
)
HEADING = re.compile(r"^(?P<level>#{1,6})(?:\s|$)")
NUMBERED_ITEM = re.compile(r"^\s*(?P<number>\d+)\.\s+(?P<text>.*)$")
FENCE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+).+?\1")
EARS_KEYWORD = re.compile(r"\b(?:DEVEM?|SHALL)\b")
STRUCTURAL_MARKERS = ("-", "*", "+", ">", "#", "`", "|", "<")

TASK_LINE = re.compile(
    r"^\s*-\s*\[(?P<state>[ xX~-])\](?P<optional>\*)?\s+"
    r"(?P<id>\d+(?:\.\d+)*)\.?\s+(?P<title>.*)$"
)
REQUIREMENTS_REF = re.compile(
    r"^\s*(?:-\s+)?_?(?:Requisitos?|Requirements?)\s*:\s*(?P<ids>.*?)_?\s*$", re.IGNORECASE
)
DEPENDS_REF = re.compile(
    r"^\s*(?:-\s+)?_?(?:Depende[ _]de|Depends[ _]on)\s*:\s*(?P<ids>.*?)_?\s*$", re.IGNORECASE
)
ID = re.compile(r"\d+(?:\.\d+)*")

# Words that make a criterion unmeasurable. Matched case-insensitively as whole words (accents
# included) outside inline code; replace them with an observable limit.
VAGUE_TERMS: tuple[str, ...] = (
    # PT-BR
    "rápido", "rapido", "rápida", "rapida", "rápidos", "rapidos", "rápidas", "rapidas",
    "rapidamente",
    "fácil", "facil", "fáceis", "faceis", "facilmente",
    "amigável", "amigavel", "amigáveis", "amigaveis",
    "intuitivo", "intuitiva", "intuitivos", "intuitivas",
    "adequado", "adequada", "adequados", "adequadas", "adequadamente",
    "eficiente", "eficientes", "eficientemente",
    "robusto", "robusta", "robustos", "robustas",
    "performático", "performatico", "performática", "performatica",
    "otimizado", "otimizada", "otimizados", "otimizadas",
    "escalável", "escalavel", "escaláveis", "escalaveis",
    "bonito", "bonita", "moderno", "moderna",
    "se possível", "se possivel", "quando necessário", "quando necessario",
    "conforme necessário", "conforme necessario",
    # EN
    "fast", "quick", "quickly", "easy", "easily", "user-friendly", "user friendly",
    "intuitive", "appropriate", "appropriately", "adequate", "adequately",
    "efficient", "efficiently", "robust", "performant", "optimized", "optimised", "optimal",
    "scalable", "seamless", "seamlessly", "modern", "beautiful",
    "as needed", "as appropriate", "if possible", "when necessary", "as necessary",
)  # fmt: skip
VAGUE_PATTERN = re.compile(
    r"(?<!\w)(?:"
    + "|".join(
        r"\s+".join(re.escape(word) for word in term.split())
        for term in sorted(VAGUE_TERMS, key=len, reverse=True)
    )
    + r")(?!\w)",
    re.IGNORECASE,
)

HINT = "\n".join(
    (
        "requirements.md: give every `### Requisito <n>: <title>` (or `### Requirement <n>`) a "
        "`**História:**` (or `**User Story:**`) line and a numbered list under "
        "`#### Critérios de Aceite` (or `#### Acceptance Criteria`).",
        "Write each criterion in EARS form with an uppercase keyword outside backticks, e.g. "
        "`1. QUANDO <gatilho>, o sistema DEVE <resposta>.` or "
        "`1. WHEN <trigger>, THE SYSTEM SHALL <response>.`; wrapped lines must be indented.",
        "Replace vague words with measurable limits (e.g. `em até 2 s`, `at most 3 retries`) and "
        "add a `## Fora de Escopo` (or `## Out of Scope`) section.",
        "design.md: add a `## Segurança` (or `## Threat Model`) section: threat, control and the "
        "gate or test that verifies it.",
        "tasks.md: `- [ ] <n>. <title>`, sub-tasks `- [ ] <n>.<m> <title>`, optional `- [ ]* ...`; "
        "`- _Requisitos: <ids>_` cites existing criteria; `- _Depende de: <ids>_` cites only "
        "earlier tasks, and a mandatory task never depends on an optional one.",
        "Fix the document, never the validator.",
    )
)


@dataclass(slots=True)
class Criterion:
    number: str
    line: int
    text: str


@dataclass(slots=True)
class Requirement:
    number: str | None
    line: int
    title: str
    has_story: bool = False
    criteria: list[Criterion] = field(default_factory=lambda: [])


@dataclass(frozen=True, slots=True)
class Reference:
    target: str
    line: int


@dataclass(slots=True)
class Task:
    task_id: str
    line: int
    title: str
    done: bool = False
    optional: bool = False
    requirements: list[Reference] = field(default_factory=lambda: [])
    depends_on: list[Reference] = field(default_factory=lambda: [])

    @property
    def parent(self) -> str:
        return self.task_id.rpartition(".")[0]


def iter_lines(text: str) -> Iterator[tuple[int, str, bool]]:
    """Yield (line number, line, fenced); fenced is True for code fences and their content."""
    fence: str | None = None
    for number, line in enumerate(text.removeprefix(BOM).splitlines(), start=1):
        stripped = line.strip()
        if fence is not None:
            if stripped.startswith(fence) and stripped == stripped[0] * len(stripped):
                fence = None
            yield number, line, True
        elif match := FENCE.match(line):
            fence = match.group("fence")
            yield number, line, True
        else:
            yield number, line, False


def has_heading(text: str, pattern: re.Pattern[str]) -> bool:
    return any(pattern.match(line) for _, line, fenced in iter_lines(text) if not fenced)


def excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 3] + "..."


def is_continuation(line: str) -> bool:
    """ADR-0006: an indented, non-blank text line without a Markdown structural marker."""
    content = line.lstrip()
    return line[:1].isspace() and bool(content) and not content.startswith(STRUCTURAL_MARKERS)


def vague_terms(text: str) -> list[str]:
    found: list[str] = []
    for match in VAGUE_PATTERN.finditer(text):
        term = " ".join(match.group(0).lower().split())
        if term not in found:
            found.append(term)
    return found


def parse_requirements(text: str) -> list[Requirement]:
    requirements: list[Requirement] = []
    current: Requirement | None = None
    in_criteria = False
    continuation_open = False
    for number, line, fenced in iter_lines(text):
        if fenced:
            continuation_open = False
            continue
        if heading := REQUIREMENT_HEADING.match(line):
            current = Requirement(heading.group("number"), number, line.lstrip("#").strip())
            requirements.append(current)
            in_criteria = continuation_open = False
            continue
        if current is None:
            continue
        if CRITERIA_HEADING.match(line):
            in_criteria, continuation_open = True, False
        elif other := HEADING.match(line):
            in_criteria = continuation_open = False
            if len(other.group("level")) <= 3:
                current = None  # a section such as `## Fora de Escopo` ends the requirement
        elif USER_STORY.search(line):
            current.has_story = True
            continuation_open = False
        elif in_criteria and (item := NUMBERED_ITEM.match(line)):
            current.criteria.append(Criterion(item.group("number"), number, item.group("text")))
            continuation_open = True
        elif continuation_open and is_continuation(line):
            current.criteria[-1].text += " " + line.strip()
        else:
            continuation_open = False
    return requirements


def collect_requirement_ids(requirements: Sequence[Requirement]) -> set[str]:
    ids: set[str] = set()
    for requirement in requirements:
        if requirement.number is None:
            continue
        ids.add(requirement.number)
        ids.update(f"{requirement.number}.{c.number}" for c in requirement.criteria)
    return ids


def validate_requirements_text(
    text: str, path: str = "requirements.md"
) -> tuple[list[str], set[str]]:
    """Return (problems, requirement ids such as {"1", "1.1", "1.2"}) for a requirements.md."""
    requirements = parse_requirements(text)
    problems: list[str] = []
    if not requirements:
        problems.append(
            f"{path}: no requirement sections found; expected `### Requisito <n>: <title>` "
            "or `### Requirement <n>: <title>`"
        )
    if not has_heading(text, OUT_OF_SCOPE_HEADING):
        problems.append(
            f"{path}: missing section `## Fora de Escopo` (or `## Out of Scope`) stating what "
            "the feature will not do"
        )
    first_line: dict[str, int] = {}
    for requirement in requirements:
        where = f"{path}:{requirement.line}"
        number = requirement.number or "?"
        if requirement.number is None:
            problems.append(
                f"{where}: requirement heading needs a number, e.g. `### Requisito 1: <title>`"
            )
        elif requirement.number in first_line:
            problems.append(
                f"{where}: duplicate requirement number {number} "
                f"(first used on line {first_line[number]})"
            )
        else:
            first_line[number] = requirement.line
        if not requirement.has_story:
            problems.append(
                f"{where}: requirement {number}: missing story line `**História:**` "
                "(or `**User Story:**`)"
            )
        if not requirement.criteria:
            problems.append(
                f"{where}: requirement {number}: no numbered acceptance criteria under "
                "`#### Critérios de Aceite` (or `#### Acceptance Criteria`)"
            )
        seen: set[str] = set()
        for criterion in requirement.criteria:
            label = f"{path}:{criterion.line}: criterion {number}.{criterion.number}"
            if criterion.number in seen:
                problems.append(f"{label}: duplicate criterion number; number them 1, 2, 3, ...")
            seen.add(criterion.number)
            prose = CODE_SPAN.sub(" ", criterion.text)
            if not EARS_KEYWORD.search(prose):
                problems.append(
                    f"{label}: lacks an uppercase EARS keyword `DEVE`, `DEVEM` or `SHALL` "
                    f"outside backticks: {excerpt(criterion.text)}"
                )
            if found := vague_terms(prose):
                terms = ", ".join(f"'{term}'" for term in found)
                problems.append(
                    f"{label}: vague term(s) {terms}; replace with a measurable limit "
                    "(e.g. `em até 2 s`, `at most 3 retries`)"
                )
    return problems, collect_requirement_ids(requirements)


def validate_design_text(text: str, path: str = "design.md") -> list[str]:
    if has_heading(text, SECURITY_HEADING):
        return []
    return [
        f"{path}: missing section `## Segurança` (or `## Threat Model`) listing each threat, "
        "its control and the gate or test that verifies it"
    ]


def parse_tasks(text: str) -> list[Task]:
    tasks: list[Task] = []
    current: Task | None = None
    for number, line, fenced in iter_lines(text):
        if fenced:
            continue  # spec tools may append a JSON dependency graph in a code fence
        if match := TASK_LINE.match(line):
            current = Task(
                task_id=match.group("id"),
                line=number,
                title=match.group("title").strip(),
                done=match.group("state") in "xX",
                optional=match.group("optional") == "*",
            )
            tasks.append(current)
        elif HEADING.match(line):
            current = None  # references under `## Notes` belong to no task
        elif current is None:
            continue
        elif ref := REQUIREMENTS_REF.match(line):
            current.requirements.extend(Reference(i, number) for i in ID.findall(ref["ids"]))
        elif dep := DEPENDS_REF.match(line):
            current.depends_on.extend(Reference(i, number) for i in ID.findall(dep["ids"]))
    return tasks


def find_cycle(graph: Mapping[str, Sequence[str]]) -> list[str] | None:
    """Return the first dependency cycle found by DFS as a closed path, e.g. ["1", "2", "1"].

    `graph` maps a node to the nodes it depends on; nodes are visited in insertion order, so the
    result is deterministic. Nodes that only appear as targets have no outgoing edges.
    """
    state: dict[str, bool] = {}  # True = on the current DFS path, False = fully explored
    for start in graph:
        if start in state:
            continue
        path = [start]
        stack: list[Iterator[str]] = [iter(graph.get(start, ()))]
        state[start] = True
        while stack:
            for target in stack[-1]:
                if state.get(target) is True:
                    return [*path[path.index(target) :], target]
                if target not in state:
                    state[target] = True
                    path.append(target)
                    stack.append(iter(graph.get(target, ())))
                    break
            else:
                state[path.pop()] = False
                stack.pop()
    return None


def dependency_graph(tasks: Sequence[Task]) -> dict[str, list[str]]:
    """Edges from a task to what it needs: its known dependencies plus its direct sub-tasks."""
    graph: dict[str, list[str]] = {}
    for task in tasks:
        graph.setdefault(task.task_id, [])
    for task in tasks:
        edges = graph[task.task_id]
        for ref in task.depends_on:
            if ref.target in graph and ref.target != task.task_id and ref.target not in edges:
                edges.append(ref.target)
        siblings = graph.get(task.parent)
        if siblings is not None and task.task_id not in siblings:
            siblings.append(task.task_id)
    return graph


def validate_tasks_text(
    text: str, requirement_ids: set[str] | None = None, path: str = "tasks.md"
) -> list[str]:
    """Check tasks.md; requirement references are only checked when `requirement_ids` is given."""
    tasks = parse_tasks(text)
    if not tasks:
        return [f"{path}: no tasks found; expected `- [ ] <n>. <title>` lines"]
    problems: list[str] = []
    first: dict[str, Task] = {}
    position: dict[str, int] = {}
    for index, task in enumerate(tasks):
        if task.task_id in first:
            problems.append(
                f"{path}:{task.line}: task {task.task_id}: duplicate task id "
                f"(first declared on line {first[task.task_id].line})"
            )
        else:
            first[task.task_id] = task
            position[task.task_id] = index

    def optional_marker(task_id: str) -> str | None:
        """Id of the task whose `*` makes `task_id` optional: the task itself or an ancestor."""
        while task_id:
            task = first.get(task_id)
            if task is not None and task.optional:
                return task_id
            task_id = task_id.rpartition(".")[0]
        return None

    for index, task in enumerate(tasks):
        name = f"task {task.task_id}"
        if task.parent and task.parent not in first:
            problems.append(f"{path}:{task.line}: {name}: parent task {task.parent} is missing")
        for ref in task.depends_on:
            where, dep = f"{path}:{ref.line}: {name}", ref.target
            if dep == task.task_id:
                problems.append(f"{where}: depends on itself")
            elif dep not in first:
                problems.append(f"{where}: depends on unknown task {dep}")
            elif position[dep] > index:
                problems.append(
                    f"{where}: forward dependency on task {dep} declared later "
                    f"(line {first[dep].line}); reorder or split the tasks"
                )
            elif (marker := optional_marker(dep)) and optional_marker(task.task_id) is None:
                via = "" if marker == dep else f" (optional through the `*` of task {marker})"
                problems.append(
                    f"{where}: mandatory task depends on optional task {dep}{via}; drop the "
                    f"dependency, make {dep} mandatory or mark {task.task_id} optional with `*`"
                )
        if requirement_ids is not None:
            problems.extend(
                f"{path}:{ref.line}: {name}: references unknown requirement {ref.target}"
                for ref in task.requirements
                if ref.target not in requirement_ids
            )
    if cycle := find_cycle(dependency_graph(tasks)):
        implicit = any(b.startswith(a + ".") for a, b in pairwise(cycle))
        note = " (a parent task implicitly depends on its sub-tasks)" if implicit else ""
        problems.append(
            f"{path}:{first[cycle[0]].line}: dependency cycle: {' -> '.join(cycle)}{note}"
        )
    return problems


def read_document(path: Path) -> str:
    # utf-8-sig strips a BOM (Windows editors / PowerShell 5 add one) that would hide line 1.
    return path.read_text(encoding="utf-8-sig")


def is_not_started(spec: Path) -> bool:
    """ADR-0003: the folder exists but holds nothing yet."""
    return not any(spec.iterdir())


def validate_spec_dir(path: Path, label: str | None = None) -> list[str]:
    """Validate one spec folder; problems are prefixed with `label` (default: the path)."""
    prefix = path.as_posix() if label is None else label
    if not path.is_dir():
        return [f"{prefix}: spec folder does not exist"]
    if is_not_started(path):
        return []
    problems: list[str] = []
    texts: dict[str, str] = {}
    for name in ("requirements.md", "design.md", "tasks.md"):
        if (path / name).is_file():
            try:
                texts[name] = read_document(path / name)
            except UnicodeDecodeError:
                problems.append(f"{prefix}/{name}: not valid UTF-8 text; save it as UTF-8")
    known: set[str] | None = None
    if (path / "requirements.md").is_file():
        if "requirements.md" in texts:
            found, known = validate_requirements_text(
                texts["requirements.md"], f"{prefix}/requirements.md"
            )
            problems += found
    elif not (path / "bugfix.md").is_file():
        problems.append(
            f"{prefix}: requirements.md is missing (bugfix specs use bugfix.md); write the "
            "Specify phase before design.md, tasks.md or progress.md"
        )
    if "design.md" in texts:
        problems += validate_design_text(texts["design.md"], f"{prefix}/design.md")
    if "tasks.md" in texts:
        problems += validate_tasks_text(texts["tasks.md"], known, f"{prefix}/tasks.md")
    return problems


def find_repo_root(start: Path) -> Path:
    """Nearest folder at or above `start` that contains `.git` (dir or worktree file).

    Falls back to `start` itself when no `.git` exists above it.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def report(results: Mapping[str, Sequence[str]]) -> int:
    failed = False
    for label, problems in results.items():
        if not problems:
            print(f"SPEC VALID: {label}")
            continue
        failed = True
        print(f"SPEC INVALID: {label} ({len(problems)} problem(s))")
        for problem in problems:
            print(f"  {problem}")
    if failed:
        print("--- fix hint ---")
        print(HINT)
    return 1 if failed else 0


def validate_all(root: Path) -> int:
    specs_dir = root / SPECS_DIRNAME
    if not specs_dir.is_dir():
        print(f"SPECS VALID: no {SPECS_DIRNAME}/ folder under {root.as_posix()}; nothing to check")
        return 0
    specs = sorted(
        p for p in specs_dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))
    )
    if not specs:
        print(f"SPECS VALID: no spec folders in {display(specs_dir, root)}; nothing to check")
        return 0
    labels = {spec: display(spec, root) for spec in specs}
    return report({labels[spec]: validate_spec_dir(spec, labels[spec]) for spec in specs})


def validate_one(raw: str, root: Path) -> int:
    target = Path(raw)
    if not target.is_absolute() and not target.exists():
        target = root / target  # a relative path may be relative to the repository root
    if target.is_file():
        target = target.parent
    if not target.is_dir():
        print(f"SPEC INVALID: {raw} does not exist")
        print(f"  looked in the working directory and under {root.as_posix()}")
        return 1
    label = display(target, root)
    return report({label: validate_spec_dir(target, label)})


def main(argv: Sequence[str] | None = None, root: Path | None = None) -> int:
    """CLI entry point; `root` overrides the repository root found from the working directory."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if len(args) != 1 or (args[0].startswith("-") and args[0] != "--all"):
        print(f"SPEC USAGE ERROR: expected `--all` or one spec folder, got {args}")
        print(USAGE)
        return 1
    repo_root = find_repo_root(Path.cwd()) if root is None else root
    if args[0] == "--all":
        return validate_all(repo_root)
    return validate_one(args[0], repo_root)


if __name__ == "__main__":
    # Spec text may hold characters a legacy Windows code page cannot encode: escape, never crash.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="backslashreplace")
    sys.exit(main())
