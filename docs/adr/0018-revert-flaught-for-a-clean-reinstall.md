# ADR 0018: Revert Flaught adversarial review entirely, for a clean reinstall

**Status:** Accepted
**Date:** 2026-08-21

## Context

ADR 0017 landed Flaught as an artifact-only, non-blocking CI job. A follow-up
branch (`MysteryMixClub-tq2a`) then iterated on it substantially — blocking
the merge check, posting PR comments, switching provider to Groq, bumping
`@flaught/core` through several versions, and accumulating a number of
config/dismissal decisions along the way (tracked in that branch's own
now-abandoned ADRs 0018/0019, PR #269).

Across that iteration, several gaps surfaced that turned out to trace back to
this repo's own ad hoc, incremental setup rather than to Flaught itself:
`.advreview.yml`'s `tools:` block being commented out gave the impression
semgrep was disabled when it was actually on by schema default; semgrep was
never installed in this repo's CI at all, so it silently produced 0 findings
regardless; the workflow accumulated job-specific `permissions:` and
provider-swap history piecemeal, commit by commit, rather than as one
coherent setup.

Rather than keep patching an installation that grew organically and
inconsistently, the decision is to revert Flaught out of this repo
completely — including ADR 0017's original merged baseline, not just the
follow-up branch — and reinstall from scratch by hand, following Flaught's
own quickstart guide (`docs/github-actions.md` in `flaught/core`) directly,
so the resulting setup matches a known-good reference shape instead of this
repo's particular accumulated history.

## Decision

Removed entirely:

- `.advreview.yml`
- The `flaught` job in `.github/workflows/ci.yml`
- The Flaught references in `docs/ci-cd.md`'s workflow table and secrets
  section

ADR 0017 is marked superseded rather than deleted or edited — its reasoning
is still real history, per this directory's own stated convention
(`docs/adr/README.md`: "Never edit an existing ADR to reverse its
decision"). The abandoned branch's own PR (#269) is closed without merging;
its ADRs 0018/0019 never reached `develop` and aren't referenced here.

`.beads/interactions.jsonl`'s historical entries referencing Flaught are left
untouched — it's an append-only log, not current-state documentation.

## Consequences

- **Zero Flaught trace in this repo as of this commit** — no CI job, no
  config file, no active secret requirement. The `GROQ_API_KEY` /
  `OLLAMA_API_KEY` repository secrets (if still present under GitHub →
  Settings → Secrets and variables → Actions) are now unused and safe to
  remove, though this ADR doesn't do that itself.
- **No adversarial review coverage until reinstalled.** This repo goes back
  to relying on lint/typecheck/test + `npm audit`/`pip-audit` alone, the same
  as before ADR 0017.
- **The next installation starts from Flaught's own documented quickstart**,
  not from copying/adapting this repo's prior setup — deliberately, to avoid
  re-inheriting the accumulated gaps above.

## Revisit if

Once Flaught is reinstalled from the quickstart guide, write a fresh ADR for
that decision rather than reopening this one or ADR 0017.
