# ADR-0010: Push the harness to child repositories through pull requests

- Date: 2026-10-03
- Status: Superseded by ADR-0012 (replaced by Global Plugin + `cli.py init` local kit)

## Context

ADR-0001 shipped the harness as a template copied without a sync mechanism. The owner now keeps
several repositories (first: a private child repository) that must follow this harness on
any machine. Agents give priority to workspace rules and the hooks require the harness at
`<repo>/scripts/harness/`, so a remote reference cannot work: the files must live in each child.
Agents in a child cannot install or update the harness (guards `generated_file`,
`privileged_config`, `harness_integrity`), so CI must do it. The owner is on the GitHub Free plan,
which has no branch protection or required checks for private repositories.

## Decision

- `harness/distribution.toml` lists the harness-owned files; `scripts/harness/distribute.py`
  installs or updates them in a child, writes `.harness/lock.toml` (version, commit, hashes) and
  regenerates the adapters in the child. Project files are created only when missing.
- A tag `v<version>` (or a manual dispatch) runs `.github/workflows/propagate.yml`: full verify,
  then for every repository in `harness/consumers.toml` a short-lived GitHub App token scoped to
  that child, an update on branch `harness/update-<version>` and a pull request. It never pushes
  another branch and never force-pushes. It sets the child variables `HARNESS_LATEST_VERSION`,
  `HARNESS_LATEST_DATE` and `HARNESS_MIN_VERSION`.
- Each child runs `.github/workflows/harness-current.yml` on pull requests: it commits a stale
  adapter sync to same-repository branches and fails on drift, on a version below the minimum, or
  on a version behind the latest after a 7-day grace period.
- Child ADRs are numbered from 1000 so they never collide with harness ADRs.
- This supersedes only the "without a sync mechanism" part of ADR-0001.

## Accepted risks (GitHub Free plan)

- The `harness-current` check is advisory: a red check does not block a merge.
- The App has write access to child repositories and could technically push to their main
  branch; only the workflow code (tested) restricts it to `harness/update-*`.
- Day-to-day control relies on the offline session-start warning and on human discipline.
- Revisit when the owner moves to GitHub Pro/Team (make `harness-current` a required check,
  protect main) or when there are more than three child repositories.

## Consequences

- Easier: a release reaches every child as a reviewable pull request.
- Easier: a hand edit to a harness file in a child is visible on every pull request.
- Harder: harness improvements made in a child must be ported here by hand (no back-flow yet).
- Harder: the owner must create and guard a GitHub App private key.
