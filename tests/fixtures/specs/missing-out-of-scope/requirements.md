# Requirements Document

### Requirement 1: Health endpoint

**User Story:** As an operator, I want a health endpoint, so that the load balancer can route traffic.

#### Acceptance Criteria

1. WHEN `GET /health` is requested, THE SYSTEM SHALL answer `200` with body `ok`.

## Scope

- Only the health endpoint is described; this heading does not satisfy the gate.
