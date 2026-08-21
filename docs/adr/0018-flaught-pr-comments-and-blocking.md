# ADR 0018: Make Flaught's CI review post PR comments and block merge

**Status:** Accepted; partially superseded by ADR 0019 (blocking on exit
code 2 specifically — the exit-code-1 severity gate and the PR-comment
change below are still in effect as decided here)
**Date:** 2026-08-20

## Context

ADR 0017 deliberately scoped the first Flaught landing conservatively:
artifact-only (findings as a downloadable Actions artifact, no PR comment)
and non-blocking (`continue-on-error: true`), specifically to prove the tool
out before trusting it with either a permissions increase or a say in
mergeability. ADR 0017's own "Revisit if" section named both of these as
the trigger conditions for this change:

- Findings proving reliable enough over a stretch of PRs to flip the
  severity gate to blocking.
- PR-comment visibility mattering enough to justify the `pull-requests:
  write` permission increase, given findings sitting only in a downloadable
  artifact are easy to never look at.

Both conditions are met — this ADR makes both changes together, since a
finding that now blocks merge needs to be visible on the PR itself, not
just in an artifact someone has to think to download.

Checked whether `@flaught/core` (currently pinned `0.5.0`) has a built-in
PR-comment mode before hand-rolling one: `flaught review --help` lists only
`-r/-b/-h/-c/--json/--output/--no-llm/--pr-description/--quiet/--help` — no
native flag. It does, however, already print a final markdown report to
stdout even with `--quiet` (only the progress lines are suppressed) — the
same table-plus-summary format shown in a local run. Reusing that stdout
directly as the PR comment body avoids hand-rendering the findings JSON a
second time and keeps the CI comment identical to what a developer sees
running `flaught review` locally.

## Decision

Two changes to the `flaught` job in `.github/workflows/ci.yml`:

- **Blocking.** Dropped `continue-on-error: true` from the "Adversarial
  review" step. `flaught review`'s stdout is now redirected (`>`, not piped)
  to `flaught-report.md` — redirection instead of a pipe keeps the step's
  exit code as flaught's own exit code with no dependency on `pipefail`
  being set. Exit code 1 (findings at/above `severity_gate.fail_on`, which
  `.advreview.yml` leaves at its schema default of `"high"` — that default
  is what's actually gating merges now, not a value this ADR chose) or exit
  code 2 (config/LLM error — e.g. a missing `OLLAMA_API_KEY`) now fails the
  job and blocks merge, the same way `frontend`/`backend` already do.
- **PR comment.** New "Post findings to PR" step, `if: always()` so it runs
  whether the review step passed or failed, using `gh pr comment --edit-last
  --create-if-none` against `flaught-report.md` — creates the comment on the
  first run, edits the same comment on every subsequent push instead of
  stacking a new one per push (matched on "last comment by the current
  actor," i.e. the workflow's own token identity — fine today since no other
  job in this workflow posts PR comments, but would need a marker string to
  disambiguate if that changes). This step is itself
  `continue-on-error: true` — deliberately, so that a comment-posting
  failure (e.g. a fork PR, where GitHub forces `GITHUB_TOKEN` to
  read-only regardless of this job's `permissions:` block) surfaces as its
  own line, not as a second, more confusing red X stacked on top of the
  actual review-failure signal.
- **Permissions.** `pull-requests: write` is added at the `flaught` job
  level only (alongside a restated `contents: read`) — every other job
  (`frontend`, `backend`) stays on the workflow-level `contents: read`-only
  grant untouched. The comment above that workflow-level block (tied to
  code-scanning findings #1/#3) is updated to say so explicitly, so a future
  reader doesn't have to diff two jobs to notice the one exception.

No change to `.advreview.yml`'s `llm:` block or provider — that scoping call
from ADR 0017 (full LLM pass, not `--no-llm`) stands as-is.

## Consequences

- **A red Flaught step now blocks merge**, including on a config/LLM error
  (exit 2) — e.g. a rotated-but-not-updated `OLLAMA_API_KEY` now blocks
  every PR until fixed, not just this one silently-skipped step. Acceptable
  for a same-org private repo with no fork-PR traffic today; would need
  revisiting if that ever changes.
  **Superseded by ADR 0019:** in practice this meant a Groq outage blocked
  every open PR, with no signal distinguishing "the code has a real
  problem" from "the LLM provider is down." Exit code 2 now warns instead
  of blocking; exit code 1 (real findings) still blocks as decided here.
- **Findings are visible on the PR without opening Actions**, closing the
  exact gap ADR 0017 flagged as a risk ("findings... easy to never look
  at").
- **A single comment is reused across pushes** rather than one per push,
  so the PR thread doesn't fill up with stale Flaught reports — only the
  latest is ever shown.
- **The comment-posting step is best-effort**, so a fork PR (or any other
  case where `GITHUB_TOKEN` can't write) degrades to "no comment, findings
  still in the artifact and still gating merge" rather than adding a second
  unrelated failure.
- **The severity threshold that now actually blocks merges is the schema
  default (`fail_on: high`)**, inherited silently from `.advreview.yml`
  leaving `severity_gate:` commented out. It was inert under ADR 0017's
  non-blocking setup; it is load-bearing now. Worth uncommenting and
  setting explicitly the first time it needs to change, so the active
  threshold is visible in the config file itself rather than only in this
  ADR.

## Revisit if

- The severity gate proves too noisy (real PRs blocked on findings that
  turn out to be false positives often enough to erode trust) — options are
  loosening `severity_gate.fail_on` to `critical`, or building out the
  dismissal store (`flaught dismiss` / `.flaught-dismissals.json`, already
  scaffolded but commented out in `.advreview.yml`).
- This repo ever takes PRs from forks — `GITHUB_TOKEN` write restrictions on
  fork PRs mean the comment step will silently no-op there by design; worth
  a real look before that's a common path, not just an edge case.
- A second job in this workflow starts posting PR comments as the same
  actor — `--edit-last` would then need a marker string to target only
  Flaught's own comment.
