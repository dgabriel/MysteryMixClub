# ADR 0019: Don't block merge on Flaught's exit code 2 (tool/LLM error)

**Status:** Accepted
**Date:** 2026-08-21

## Context

ADR 0018 made the `flaught` job in `ci.yml` blocking: any non-zero exit
from `flaught review` fails the job and the PR's merge check. `flaught`
returns exit code 1 when findings are at/above `severity_gate.fail_on`
(a real signal about the code) and exit code 2 for a config/API/LLM
error — e.g. a Groq outage, rate limit, or a missing/rotated secret. ADR
0018 treated both the same on purpose, accepting that risk explicitly
("Acceptable for a same-org private repo with no fork-PR traffic today").

That risk materialized. Flaught's own dogfooding review flagged this
across four consecutive runs spanning three `@flaught/core` versions
(findings F-002, 88% confidence, and F-003, 85%, restating the same root
cause): a Groq outage or slow response blocks every open PR in this repo,
with the merge check giving no way to tell "the code has a problem" apart
from "the LLM provider is unavailable." That's a tool/infra fault, not
evidence of a real code problem, and it shouldn't have the same authority
over mergeability as an actual finding.

`@flaught/core`'s own dogfooding CI (in the Flaught repo itself) already
solves this by splitting the two exit codes into separate check steps
rather than letting the review step's own exit code gate the job directly.
Porting that pattern here is more direct than adding new flags or config on
the Flaught side, and it doesn't require a new `@flaught/core` release
before this repo is protected.

## Decision

Split exit-code handling in the `flaught` job's "Adversarial review" step:

- The review step now runs with `set +e`, captures `flaught review`'s exit
  code to `$GITHUB_OUTPUT` as `exit_code`, and always itself exits 0 — so
  its own pass/fail no longer determines the job's outcome.
- A new **Check severity gate** step runs only `if:
  steps.review.outputs.exit_code == '1'` and fails the job
  (`::error::` + `exit 1`). This is the actual merge gate now — unchanged
  from ADR 0018's intent for real findings.
- A new **Check for errors** step runs only `if:
  steps.review.outputs.exit_code == '2'` and emits `::warning::` without
  failing the job. A tool/infra fault surfaces loudly (a yellow warning
  annotation on the run, plus whatever's in the job logs) but doesn't block
  the PR.

No change to `.advreview.yml`, the severity gate threshold, the PR-comment
step, or the `pull-requests: write` permission — all still as ADR 0018
decided them.

## Consequences

- **A Groq outage or LLM/config error no longer blocks merge.** The
  tradeoff ADR 0018 accepted and later found too costly is gone.
- **A genuinely broken `.advreview.yml`** (also exit code 2 — e.g. a typo
  in `severity_gate.fail_on`) now also only warns instead of blocking.
  That's an accepted side effect: a bad config file is still a tool-level
  problem the same way an outage is, and someone has to read the warning
  and fix it rather than being forced to by a blocked merge. This is the
  same tradeoff Flaught's own CI already makes on itself.
- **Exit code 1 (real findings) is unaffected** — the severity gate still
  blocks merge exactly as ADR 0018 set it up.
- **One more step in the job's log** (two check steps instead of the
  review step's own pass/fail), a minor readability cost against the gain
  in signal quality.

## Revisit if

- Exit-code-2 warnings start getting ignored the way a chronically-red
  non-blocking check does elsewhere (the same risk ADR 0017 flagged for
  full non-blocking) — if LLM/infra errors become common enough that
  nobody looks at the warning, that's a sign the provider itself needs
  fixing (retries, a fallback provider, a cheaper/faster model), not that
  this decision should revert to blocking.
- `@flaught/core` ships a built-in way to distinguish these exit codes
  without hand-rolling the two-step check here (e.g. a `--fail-on
  findings-only` flag) — worth switching to the native option if/when one
  exists, to keep this workflow file thinner.
