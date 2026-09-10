# ADR 0024: Scope pre-push checks to changed paths

**Status:** Accepted
**Date:** 2026-09-09

## Context

Pre-push has always run frontend typecheck, backend `mypy`, and the full
backend `pytest` suite (1300+ tests, ~90-100s) unconditionally, regardless of
what a given push actually touched — a one-line documentation fix paid the
same local cost as a full-stack feature.

That cost became concrete today: a single-line style tweak (removing an
`uppercase` class, capitalizing two words) took roughly 7 minutes end to end.
Most of that was CI, not the local hook, but the local hook's ~100s of
backend tests for a change that never touched `backend/` was real, avoidable
waste stacked on top of it.

## Decision

Both hook copies (`.husky/pre-push`, `.beads/hooks/pre-push`, kept in sync
per existing convention) now scope which checks run to the actual diff:

- Frontend typecheck runs only if `frontend/` has changes.
- Backend `mypy` + `pytest` run only if `backend/` has changes.
- Neither runs for a push that touches neither (docs, root config, CI
  workflow files, etc.).
- A push touching both runs both, same order as before.

The diff range is `remote_sha..local_sha` from the hook's own stdin when the
remote ref already exists (pushing more commits to an already-open PR — the
common case). A brand-new branch's first push has no remote side to diff
against, so it falls back to the merge-base with `origin/develop`, then
`origin/main` — every branch is based off one of those. If no usable range
can be found, or `git diff` itself errors against a range that was found,
the hook runs everything: an unknown diff is never treated as "nothing
changed."

**Deliberately not touched: CI.** `ci.yml`'s `frontend` and `backend` jobs
still always both run regardless of diff size. Skipping a GitHub Actions job
outright based on changed paths risks a required status check in branch
protection never reporting for that push — which can leave a PR permanently
stuck unable to merge, a materially different failure mode than a local hook
just taking longer than it needed to. That's a separate decision, flagged
back to Dawn, not folded into this one.

## Consequences

- A docs-only or config-only push now completes pre-push in roughly the time
  it takes `git` to compute a diff, not ~100s.
- A frontend-only push skips the backend suite entirely (and vice versa),
  cutting local pre-push time roughly in half for the common single-surface
  change.
- **The safety margin moved, not shrunk.** CI still runs the full suite
  either way before merge is possible — this hook was always a fast local
  pre-flight, not the actual gate. See `docs/git-hygiene.md` → "Pre-flight
  before pushing."
- A change that touches `backend/` indirectly without a file literally under
  that path (e.g. a root `pyproject.toml` affecting backend tooling, or a CI
  workflow change that could break the backend job) won't trigger local
  backend tests. CI is still the real gate for that case; this is a
  deliberate tradeoff of local-hook speed against local-hook completeness,
  not a claim that the hook now catches everything it used to.

## Revisit if

- The path-matching (`^frontend/` / `^backend/`, plain prefix match) proves
  too coarse once a change touches something structurally adjacent but not
  literally under either directory (e.g. a shared root-level config both
  sides depend on) and that gap causes a real missed local check.
- CI's own per-job cost becomes worth the required-status-check risk this
  ADR explicitly declined to take on for the local hook — that's a fresh
  decision, not a retroactive edit to this one.
