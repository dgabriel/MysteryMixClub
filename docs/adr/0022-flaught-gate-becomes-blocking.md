# ADR 0022: Flaught's severity gate becomes blocking

**Status:** Accepted
**Date:** 2026-09-09

## Context

ADR 0020 wired Flaught's full review (deterministic + LLM) into CI as
non-blocking, explicitly deferring the blocking decision: "The non-blocking
gate should tighten to blocking once there's a real track record of low
false-positive rate on actual PRs... a new decision... not a retroactive
edit to this one."

PR #283 (the first real PR under that setup) surfaced that track record
directly: 22 findings total, 17 already covered by persisted dismissals
from the original ADR 0019 triage (false positives or already tracked as
their own bd issues), and the remaining 5 — a repeated
`dependabot-missing-cooldown` finding on `.github/dependabot.yml` — sat
comfortably under the medium-severity noise budget. The gate's own exit
code confirmed this: `flaught review` exited 0 on that PR (verified via the
step's own `conclusion`, not just the job's masked status), meaning
blocking mode would not have changed the outcome of the one real PR run to
date. That, plus a full run producing zero *new*, unreviewed findings
against this branch's actual diff, is the track record ADR 0020 asked for.

A separate practical risk surfaced while checking this: PR #283 merged
without anyone reading the Flaught PR comment, only the CI checkmark —
because `continue-on-error: true` makes the job report success regardless
of findings, a human skimming checks has no visual signal that a real,
un-triaged finding might be sitting there. Blocking removes that gap by
construction; a genuine gate trip now fails the merge check rather than
relying on someone remembering to click through to the comment.

## Decision

Two changes, both to the existing `flaught` job in `ci.yml` — no new job,
no permissions change:

1. **The "Run adversarial review" step is no longer `continue-on-error:
   true`.** It now captures `flaught review`'s exit code explicitly and
   distinguishes two failure shapes (per ADR 0017's own documented exit
   codes):
   - **Exit 1** (undismissed findings at or above the severity gate) —
     blocks. `exit 1` from the step, failing the job and the merge check.
   - **Exit 2** (tool/config fault — e.g. `GROQ_API_KEY` unreachable on a
     fork PR) — does not block. Logged as a `::warning::` annotation so
     it's visible without stopping merge, since this is an infra gap, not
     a review outcome the PR's author can act on by changing code.
2. **`.advreview.yml`'s `dismissals:` block is now explicit** (`enabled:
   true`, `path: .flaught-dismissals.json`) rather than left to schema
   default. Now that undismissed findings can block a merge, whether
   dismissals persist is not something to leave implicit — same lesson
   ADR 0018 already paid for once with the `tools:` block.

The "Upload findings" and "Comment on PR" steps are unchanged (`if:
always()` already, so they still run and stay visible even when the gate
now fails the job).

## Consequences

- **A real Flaught finding now blocks merge to `develop`/`main`**, same as
  a failing test. The escape hatch is `flaught dismiss <id> --reason ...`
  (persisted to the git-tracked `.flaught-dismissals.json`) for a false
  positive or a knowingly-deferred real finding (tracked as its own bd
  issue, matching the pattern already established for `MysteryMixClub-2nz5`
  /`xywe`/`io0j`), or an actual code fix.
- **A fork PR with no access to `GROQ_API_KEY` no longer gets permanently
  blocked** by that alone — exit 2 warns rather than fails. This repo is
  effectively single-developer today, so this matters more as future-proofing
  than a current gap.
- **The 5 undismissed `dependabot-missing-cooldown` findings on
  `.github/dependabot.yml` are currently within the medium-severity budget
  (5/15) and don't trip the gate today** — but they're real, un-triaged
  findings sitting in the repo the moment blocking mode is watching. They
  need an explicit fix-or-dismiss decision, not left to ride under budget
  indefinitely as more findings accumulate elsewhere. Not resolved by this
  ADR itself.
- **Still using `@flaught/core@0.7.2`** (pinned) — `MysteryMixClub-axv5`
  scopes the bump to 0.10.0 separately; that bump also turns on two new
  default-on tools (`test_weakening`, `dependency_sanity`), which will add
  to what the gate now blocks on. Land axv5 with its own eyes open to that,
  not as a side effect of this ADR.
- **`MysteryMixClub-ta06` (linter tool not resolving in CI) is unaffected
  by blocking mode** — a tool that can't run degrades to 0 findings for
  that tool rather than erroring the whole review (confirmed: this repo's
  real CI run reported `linter — not run` as a warning banner, exit 0
  overall), so the silent coverage gap persists under blocking exactly as
  it did under non-blocking. Fixing it is still separately worthwhile, just
  not gating.

## Revisit if

- The gate starts blocking real PRs on findings that turn out to be
  systematically false-positive for this repo's patterns (the way the
  Alembic-migration raw-SQL findings already were) — tighten
  `.advreview.yml`'s config (noise budget, excluded paths) rather than
  reverting to non-blocking wholesale.
- Fork-PR contribution becomes real enough that the exit-2 warning-only
  behavior needs a stronger nudge (e.g. failing the check but with a
  clearly distinct message) rather than a background warning nobody reads.
