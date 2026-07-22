# Architecture Decision Records

This directory captures **why**, not just what — the tradeoffs behind a
decision, not a restatement of the code. Anyone can read the code to see what
was built; an ADR is for the reasoning a future reader can't recover from a
diff.

## Who writes one, and when

**Everyone — PM and developers alike, including Claude Code.** Whoever is
making or proposing the decision writes the ADR, at decision time (not
retroactively, except where noted below).

Write one for any **major decision**, meaning any of:

- A technology, vendor, or hosting choice (e.g. platform vs. self-managed
  infra, a third-party API dependency, a datastore choice).
- An architectural pattern (auth model, data model shape, API contract
  convention) that other work will build on.
- A deliberate tradeoff that isn't obvious from the code alone — especially
  one that overrides a "normal" or previously-established approach.
- Anything a future contributor (or a future Claude Code session) might
  otherwise "fix" by reverting to the more obvious alternative, not knowing
  it was already tried and rejected.

Don't write one for routine implementation choices, bug fixes, or anything
fully explained by reading the diff. If you're unsure whether something rises
to this bar, err toward writing a short one — a three-paragraph ADR that
turns out not to matter is cheap; a missing one for a decision that gets
silently re-litigated six months later is not.

## Format

One file per decision: `docs/adr/000N-short-slug.md`, numbered sequentially
(check the highest existing number first — don't reuse or gap numbers).
Follow the structure in `0001-feature-flags-as-env-booleans.md`:

```
# ADR NNNN: <decision, stated as a sentence, not just a topic>

**Status:** Proposed | Accepted | Superseded by ADR NNNN
**Date:** YYYY-MM-DD

## Context
Why this decision was needed — the situation, the alternatives on the table,
and any constraint (cost, timeline, portability, prior incident) that shaped
it.

## Decision
What was decided, stated plainly enough that someone skimming just this
section knows what to build to.

## Consequences
What this costs or gives up, not just what it gains. Include anything that
becomes dead code, anything now requiring more manual work, and anything a
related ticket/decision depends on.

## Revisit if
The condition under which this decision should be re-opened, not treated as
permanent.
```

## Superseding a decision

Never edit an existing ADR to reverse its decision — write a new one and mark
the old one's status `Superseded by ADR NNNN`. The old ADR's reasoning is
still real history; overwriting it erases why the *original* call was made,
which is exactly the information an ADR exists to preserve.

## Backfill

Decisions made before this practice was formalized (2026-07-22) aren't
captured here yet. See the backlog ticket tracking that backfill — don't
assume the absence of an ADR means a decision was casual; it may just predate
this directory being load-bearing.
