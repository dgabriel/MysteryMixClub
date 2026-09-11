# ADR 0026: Flaught bump to 0.12.0 — real PR comments, config-injection hardening

**Status:** Accepted
**Date:** 2026-09-11

## Context

`MysteryMixClub-0wsc`. While triaging PR #291's Flaught findings the
previous session, we found and filed two upstream bugs against
`flaught/core` (which Dawn also maintains):

- **flaught/core#75** — the "Comment on PR" CI step re-ran
  `flaught review --no-llm` to render the PR comment without a second
  billed LLM call. That meant the comment a human actually reads on GitHub
  never contained an LLM-sourced finding, with no indication anything was
  missing — a reviewer had to know to download the `findings.json` workflow
  artifact by hand to see the full picture. **Fixed in 0.12.0**
  (`flaught report --from <path>`, a pure artifact→markdown renderer with
  no LLM call and no git diff — the comment step now renders the real,
  already-computed findings instead of a second, incomplete run).

- **flaught/core#76** — `flaught review` always reviews the entire
  cumulative PR diff on every push, so a non-deterministic LLM re-rolls its
  judgment on already-reviewed code whenever any commit lands, producing
  differently-angled (not just reworded) findings that don't fingerprint-
  match prior dismissals. **Still open upstream** — 0.12.0 only documents
  the behavior (`docs/github-actions.md`) and points at dismissal TTLs as
  the current mitigation; the incremental-review mechanism itself is
  design-heavy and not yet shipped. Not fixed by this bump.

Two more relevant changes shipped in the 0.10.0 → 0.12.0 range, both found
by reading the real CHANGELOG rather than assumed from version numbers
alone:

- **0.11.0** added `--config-from-base` — loads `.advreview.yml` from the
  `--base` ref via `git show` instead of the working tree, closing a
  config-injection path where a malicious PR could edit `linter.command`
  (a real shell-executed string, ADR 0025) or other tool commands to run
  arbitrary shell in a job that holds `GROQ_API_KEY`/`GITHUB_TOKEN`.
- **0.11.0** also fixed a Groq 400 (`failed_generation`) on reasoning
  models — retries once, and raised the recommended defaults
  (`max_tokens` 4096→8192, `reasoning_effort: low` added). This is not
  speculative: PR #291 hit exactly this failure directly, on this repo's
  own `groq/compound-mini` config ("LLM review failed: Refute (skeptic)
  pass failed: Bad request from openai-compatible... (400)").
- **0.12.0** also fixed a real gate-logic defect: a finding the skeptic/
  refute pass had determined **false** (`refuted`) still tripped the
  severity gate, because `computeExitCode` only excluded `dismissed`
  findings, not refuted ones. Surfaced by Flaught's own dogfooding on its
  PR #77. This changes gate behavior for us too (a refuted finding no
  longer blocks merge) — a defect fix, not a policy choice we made.

## Decision

Bump `@flaught/core` 0.10.0 → 0.12.0 in `.github/workflows/ci.yml`
(ADR 0017's exact-pin discipline maintained). Alongside the version bump:

1. **Comment step now uses `flaught report --from findings.json`**
   instead of re-running `flaught review --no-llm`. One real review run
   per PR instead of two; the comment now reflects every finding —
   deterministic and LLM — that actually gated the PR.
2. **`--config-from-base` added to the real review run.** Consequence
   accepted: a PR that itself edits `.advreview.yml` is reviewed under the
   pre-PR config until merged (same tradeoff ADR 0025's linter-command fix
   would now face on a future edit) — security over self-referential
   convenience, matching this repo's existing dependency_sanity/dismissals
   posture (ADR 0023).
3. **`llm.max_tokens` 4096 → 8192, `llm.reasoning_effort: low` added** in
   `.advreview.yml`, matching 0.11.0's new recommended default and directly
   addressing the live 400 error hit last session on this exact
   provider/model.

Verified locally before pushing, not just read from the changelog: ran
`flaught review --base origin/develop --head HEAD --config-from-base` and
`flaught report --from` against this branch's own diff — confirmed
`--config-from-base` works, and the two renders are identical, matching
0.12.0's own PR description's claim of byte-identical output between a
full review and `report --from` on the same artifact.

## Consequences

- The PR comment is now a complete, trustworthy picture of what's gating
  a merge — no more "download the artifact to see what actually failed."
- One fewer full `flaught review` invocation per PR (context assembly +
  deterministic tools no longer run twice) — modest CI time savings.
- `flaught/core#76` (full-diff re-review churn) is **not** fixed by this
  bump. Expect the same churn pattern seen on PR #291 until upstream ships
  incremental review — this ADR doesn't change that, only tracks it.
- Config-injection hardening (`--config-from-base`) is a real security
  improvement with a real (accepted) cost: self-editing `.advreview.yml`
  PRs review against stale config until merged.
- The gate-logic fix (refuted findings no longer block) may quietly change
  outcomes on future PRs relative to 0.10.0 behavior — a defect fix, worth
  knowing about if a PR that would have failed under 0.10.0 passes cleanly
  under 0.12.0 because a skeptic-refuted finding no longer counts.

## Revisit if

- `flaught/core#76` ships an incremental-review mechanism upstream —
  re-evaluate whether dismissal-TTL-based mitigation is still needed once
  it does.
- A future `.advreview.yml`-editing PR is itself blocked/confused by
  reviewing against stale (pre-PR) config under `--config-from-base` —
  weigh whether that tradeoff still holds.
