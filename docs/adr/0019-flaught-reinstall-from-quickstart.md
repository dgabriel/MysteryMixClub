# ADR 0019: Reinstall Flaught locally from its own quickstart guide

**Status:** Accepted
**Date:** 2026-08-21

## Context

ADR 0018 reverted Flaught out of the repo entirely — CI job, `.advreview.yml`,
docs references — after its follow-up branch (`MysteryMixClub-tq2a`, PR #269)
accumulated gaps traceable to this repo's own ad hoc, incremental setup
rather than to Flaught itself. ADR 0018's stated plan was to reinstall from
Flaught's own quickstart guide directly instead of recreating the prior
accumulated config, and to write a fresh ADR once that reinstall happened.

This ADR covers that reinstall's **local, deterministic-only** slice:
`npm install -g @flaught/core` (already present, `@flaught/core@0.7.1`),
`flaught init` to scaffold `.advreview.yml` + `.flaught-prompt/`, and
`flaught review --no-llm` run to a clean exit. Wiring Flaught into
`ci.yml` (the part ADR 0018 also reverted) is deliberately **not** part of
this decision — that's a separate step with its own tradeoffs (permissions,
secrets, blocking-vs-advisory gating) and should get its own ADR when done.

Unlike the prior setup — where semgrep was never installed in CI and so
silently produced 0 findings regardless of `.advreview.yml`'s `tools:`
config — this environment already has `semgrep` on `PATH` (Anaconda-provided,
`1.174.0`), so the first real run surfaced actual findings: 30 total across
two `flaught review` iterations (the noise budget hid some on the first
pass; a second pass against the same diff surfaced the rest). None were in
the diff itself (the diff was only the `.advreview.yml`/`.flaught-prompt/`
scaffold) — Flaught's dependency-graph context assembly scans the whole
repo, not just changed lines.

## Decision

Scaffolded `.advreview.yml` and `.flaught-prompt/` via `flaught init`,
unmodified from the generated defaults (matching ADR 0018's "known-good
reference shape" goal — no hand-editing the commented-out `tools:` block or
anything else).

Triaged all 30 findings from `flaught review --no-llm --base develop` and
persisted dismissals for every one, via `flaught dismiss --reason ...`
(`.flaught-dismissals.json`, git-tracked):

- **18 false positives**, all f-string-built SQL identifiers from
  hardcoded module-level constants/tuples in three files (an Alembic
  migration doing bulk table/column/constraint/index renames, another
  migration adding a named CHECK constraint, and a local offline reporting
  script) — the standard, safe pattern for DDL that can't use bind
  parameters for identifiers. No attacker-controlled input reaches any of
  them.
- **12 real findings, deferred** — filed as their own bd issues rather than
  fixed in this PR, since fixing them means touching production CI
  workflows, provisioning scripts, nginx config, and an email-logging path
  that have nothing to do with installing a review tool:
  - `MysteryMixClub-2nz5` — 9 GitHub Actions steps in `ci.yml`/
    `deploy-prod.yml` pinned to mutable version tags instead of commit SHAs.
  - `MysteryMixClub-xywe` — `ConsoleEmailSender` logs the full
    password-reset link (including its token) via `logger.info`; that
    sender is the fallback whenever `RESEND_API_KEY` is unset, not
    dev-gated.
  - `MysteryMixClub-uqvr` — `curl | bash` (unpinned, unverified) for the
    Node.js install in both droplet bootstrap scripts.
  - `MysteryMixClub-d8hz` — prod nginx config has no explicit
    `ssl_protocols` directive.
  - Two `npm audit`-sourced advisories (`fast-uri`, `js-yaml`) were already
    covered by the existing `MysteryMixClub-io0j` Dependabot cleanup issue —
    dismissed with a reference to it rather than filing duplicates.

The stale `MysteryMixClub-tq2a` (scoped to PR-comment wiring on top of the
now-reverted setup) was closed as superseded; this reinstall is tracked
under a fresh issue, `MysteryMixClub-iys1`.

## Consequences

- **`flaught review --no-llm` now exits 0** on a clean diff, with real
  deterministic coverage (semgrep + linter + vuln scanner) instead of the
  prior setup's silent 0-findings blind spot.
- **Five bd issues opened as a direct result of this install** (2nz5, xywe,
  uqvr, d8hz, plus reuse of io0j) — running a working adversarial-review
  tool against a repo that's never had one immediately surfaces real,
  pre-existing findings unrelated to whatever change triggered the run.
  Expect this pattern again if `flaught review` (or its LLM pass) is later
  run against `main` or other long-diffed branches.
- **No CI integration yet.** This is local-only; every PR still relies on
  lint/typecheck/test + `npm audit`/`pip-audit` for automated coverage,
  same as immediately after ADR 0018. `flaught review` has to be run by
  hand until a follow-up ADR wires it into `ci.yml`.
- **Dismissal reasons double as the false-positive rationale for this rule
  family going forward** — a future raw-SQL finding on a *new* Alembic
  migration will still need its own triage (dismissals are fingerprinted by
  rule+file, not by pattern), but the reasoning here (hardcoded
  identifiers, no bind params for DDL, not attacker-reachable) is the
  template to reapply.

## Revisit if

Wiring Flaught into `ci.yml` (deterministic-only or full LLM pass) is
picked up next — that's a new decision and gets its own ADR, not an edit to
this one.
