# ADR-0006: Accept indented continuations in EARS criteria

- Date: 2026-10-02
- Status: Accepted

## Context

`validate_spec.py` checked only the first physical line of each numbered acceptance criterion.
Normal Markdown wrapping could therefore move `SHALL` to an indented continuation and make a
valid criterion fail. Authors had to write long lines or rewrite formatted requirements.

The validator must not accept `SHALL` from unrelated prose, another list item, a nested list,
a heading or a fenced block.

## Decision

Treat consecutive, non-empty, indented text lines without a Markdown structural marker as part
of the preceding numbered acceptance criterion. Preserve the numbered item's starting line for
errors and requirement IDs. Stop continuation at blank, unindented or structural lines.

## Consequences

- Easier: requirements can use normal Markdown wrapping without changing their semantics.
- Harder: the parser tracks whether a criterion continuation is currently open.
- Unchanged: `SHALL` remains uppercase and mandatory; nested lists and unrelated prose cannot
  satisfy the requirement.
