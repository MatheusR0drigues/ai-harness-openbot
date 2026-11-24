# Requirements Document

## Introduction

Export the audit log of a workspace as JSON Lines.

## Requirements

### Requirement 1: Audit log export

**User Story:** As an auditor, I want to export the audit log, so that I can archive it outside the application.

#### Acceptance Criteria

1. WHEN the auditor runs `audit export --since 2026-01-01`, THE SYSTEM SHALL write one JSON object per event to standard output.
2. IF the `--since` date is in the future, THEN THE SYSTEM SHALL exit with code 2 and print the accepted date format.

### Requirement 2

**User Story:** As an operator, I want exports to be bounded, so that a single export cannot exhaust the disk.

#### Acceptance Criteria

1. WHILE an export is running, THE SYSTEM SHALL stop writing after 100 MB and exit with code 3.
2. WHERE the `--gzip` option is set, THE SYSTEM SHALL compress the output with gzip level 6.

## Out of Scope

- Importing audit logs back into the application.
