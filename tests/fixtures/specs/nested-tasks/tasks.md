# Implementation Plan

## Overview

Structure captured from a Kiro-generated tasks.md: nested sub-tasks, property markers, a
checkpoint that depends on a parent task and the JSON dependency graph Kiro appends.

## Tasks

- [ ] 1. Counting core
  - [ ] 1.1 Write unit tests for count_lines (must fail)
    - Parametrized table of inputs and expected counts.
    - _Requirements: 1.1, 2.1_
  - [ ] 1.2 Implement count_lines
    - Run the tests from 1.1 and see them pass.
    - _Requirements: 2.1, 2.2_
    - _Depends on: 1.1_
  - [ ]* 1.3 Write the line-count property test
    - **Property 1: Line count follows the constructive model**
    - **Validates: Requirements 2.1, 2.2**
    - _Requirements: 2.1, 2.2_
    - _Depends on: 1.2_

- [ ] 2. Checkpoint - core
  - Run `verify --fast` and make sure it is green.
  - _Depends on: 1_

## Notes

- Tasks marked with `*` are optional.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] }
  ]
}
```
