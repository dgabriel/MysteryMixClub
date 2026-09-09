# ADR 0023: Bump @flaught/core to 0.10.0, keep its two new tools on

**Status:** Accepted
**Date:** 2026-09-09

## Context

`@flaught/core` has been pinned at 0.7.2 since ADR 0020 (2026-08-21).
ADR 0017 made that pin deliberate — "so a newly published version can't
start running in CI unreviewed" — which means a version bump is a reviewed
decision each time, not something Dependabot should ever touch for this
package.

Three releases sit between 0.7.2 and the current latest (0.10.0): 0.8.0,
0.8.1, 0.9.0. Checked GitHub's releases API, the individual tag pages, a
tag-to-tag compare view, and npm's registry metadata for each — 0.8.1 has
no corresponding GitHub release or tag (likely an npm-only patch publish
with no formal release notes) and its specific changes couldn't be
recovered by any of those routes. 0.8.0 (first formal release) and 0.9.0
did yield real content:

- **0.9.0** decouples the LLM pass from checkout to support running
  adversarial review on fork PRs, and bumps the findings schema to v3.
  Neither is disruptive here — this repo has no active fork-PR contribution
  flow today, and schema v3's `analysis_completeness` metadata is additive.
- **0.10.0** is the release that actually matters for this bump, because it
  changes default CI-visible behavior: two new deterministic tools,
  `test_weakening` and `dependency_sanity`, ship **on by default**. Also
  adds `llm.min_confidence` (default 0, opt-in tuning) and a `flaught init
  --paranoid` preset (not used here, `flaught init` isn't re-run).

This bump lands on top of ADR 0022's blocking gate — the first time a
version bump could actually fail a merge, not just add PR-comment noise.
That raises the bar for "did I check this bump is safe" from "read the
changelog" to "actually run it against this repo's real state first."

## Decision

Bump the pin to `0.10.0` in `ci.yml`. Keep both new tools **on**, made
explicit in `.advreview.yml` rather than left to schema default — same
lesson ADR 0022 already applied to `dismissals:`, extended here to the
whole `tools:` block (`semgrep`/`linter`/`vuln_scanner` were already
implicitly on; now explicit alongside the two new ones):

- **`test_weakening`** (flags removed assertions, new skip markers,
  loosened matchers, deleted test files, comment-replaced test bodies) —
  kept on. It fits this repo's own existing test-rigor conventions
  (targeted-then-full-suite pre-push discipline, ADR 0005's test-isolation
  design) rather than fighting them.
- **`dependency_sanity`** (typosquat detection, npm registry queries during
  JS reviews) — kept on. It defends against a real supply-chain risk class;
  the npm-registry calls it makes are to a public registry with no secrets
  involved, and a registry outage degrades to "tool couldn't run" (exit 2,
  non-blocking per ADR 0022) rather than a hard CI failure.

Verified locally before pushing (this repo's own local `flaught` install
already resolved to 0.10.0, unpinned, ahead of the CI pin) that `flaught
review` against this branch's actual diff — with `tools:` and `dismissals:`
now explicit — doesn't trip the now-blocking gate. That check caught a real,
otherwise-silent break: **`.flaught-dismissals.json`'s fingerprints stopped
matching under 0.10.0.** Schema v2 (0.7.2) stored a 16-hex-char truncated
SHA-256; schema v4 (0.10.0) stores the full 32-hex-char hash, and dismissal
matching is exact-string, not prefix. Confirmed this wasn't a hash-algorithm
change — every stored short fingerprint is an exact prefix of some current
full fingerprint — by generating a fresh findings artifact and matching on
that prefix relationship, then rewriting each dismissal's `fingerprint` field
to the full form (preserving `reason`/`dismissed_by`/`dismissed_at` exactly,
rather than re-running `flaught dismiss` and losing the original audit
trail). 10 of the file's 12 entries matched and were migrated this way; the
other 2 (`MysteryMixClub-2nz5`'s unpinned-GitHub-Action findings) no longer
exist in the codebase at all — those actions are pinned to SHAs now — so
they were removed via `flaught dismissals remove` rather than migrated.
Post-migration, `flaught review` against `develop`'s current state returns
to the same "17 of 22 findings dismissed, exit 0" shape PR #283 established
before this bump.

Without this check, the bump would have shipped with every previously
reviewed finding silently reappearing as new and undismissed — on a gate
that now blocks merge (ADR 0022) — the exact failure mode "run it against
real state first" exists to catch.

**`llm.min_confidence` is now set to `0.5`, revising this ADR's own earlier
"optional tuning, not required" framing.** Local `--no-llm` verification
can't exercise the LLM pass at all (no local Groq key), so this PR's CI runs
were the first real test of it under blocking mode — and it round-tripped
three times, dismissing the same handful of concerns (dismissal-fingerprint
risk, `dependency_sanity` exposure, a nonexistent second version pin)
reworded fresh by a non-deterministic model every run. Every one of those
findings scored 0.1–0.44 confidence. That's no longer speculative — it's
the exact noise pattern the setting exists to filter, demonstrated in CI
logs, not guessed at.

## Consequences

- **`.flaught-dismissals.json`'s fingerprints are now full-length (schema
  v4 form)**, migrated in this same PR. A dismissal made under an older
  schema is not portable across a version bump without this kind of check —
  add "does `flaught review` still show dismissals as dismissed, not just
  `exit 0`" to what a future bump verifies, not just the exit code.
- **Both new tools are live in every PR's review from here on**, not just
  documented as available. Expect first-contact findings the way ADR 0019's
  local reinstall and PR #283 both did — a working new tool run against
  real code surfaces real, previously-invisible findings, not necessarily
  new problems introduced by whatever triggered the run.
- **`.advreview.yml`'s `tools:` block is now fully explicit**, closing the
  last piece of the implicit-default pattern ADR 0018 first flagged and
  ADR 0022 started fixing for `dismissals:`.
- **0.8.1's specific changes remain unknown** — not blocking, since 0.9.0's
  and 0.10.0's changelogs together account for everything CI-relevant found,
  but flagged here rather than silently assumed empty.
- **Still not fixed**: `MysteryMixClub-ta06` (linter tool not resolving in
  CI). Checked whether 0.10.0 changed linter auto-detection — no evidence
  in the fetched release notes that it does; ta06 remains open, separate
  work.

## Revisit if

- A future bump needs the same "run it against real state before merging"
  treatment now that the gate blocks — this isn't a one-time exception,
  it's the standing bar for any version bump from here on.
- `dependency_sanity`'s npm-registry calls prove flaky enough in CI
  (rate-limiting, latency) to be worth disabling or moving to a lower
  frequency than every PR.
