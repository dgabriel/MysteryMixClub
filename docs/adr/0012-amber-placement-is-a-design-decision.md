# ADR 0012: Amber placement is a design decision, not a category gate

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** ADR 0010

## Context

ADR 0009 §8 replaced the retired "Rust once per screen" *counting* rule with a
*category* rule: amber appears on **action or achievement** and nowhere
decorative. ADR 0010 then added a third category, **identity**, to license the
amber in the brand mark, and capped it at the nav's persistent mark plus **at
most one** amber hero mark in a screen's own content. ADR 0010 closed by
requiring that any fourth reason extend it by ADR rather than by analogy.

The gate was tested in practice during the 2026-08-09 design review and failed.

Dawn asked for the signed-in user's display name — the eyebrow above `MY CLUBS`
on `/home` — to render in the accent instead of `muted-foreground`. That name is
not an action, not an achievement, and not the brand mark, so under ADR 0010 a
one-line color change required a new ADR to license it. One was drafted
(*"personal identity as a fourth amber category"*, with three qualifying
conditions and a branch-exclusivity argument for why it did not collide with
`MyClubsScreen`'s empty-state brand mark). It was never committed.

Dawn's response on reading it: *"I don't like your 'one accent color per page'
rule. We are regularly going to supersede that."*

That is the decisive fact. A rule that the design owner expects to override
**regularly** is not a rule; it is a recurring tax. And because the gate was
written into `CLAUDE.md`, it was charged to every session and every agent, not
just once — each would stop, flag, and re-litigate a decision already made.

Two clarifications, since the framing in the room and the framing in the docs had
drifted apart:

- The docs never said "one accent per page." ADR 0009 §8 was explicit that amber
  is not a count, and that a screen may carry an amber CTA *and* an amber rank-1
  marker. Actions and achievements were never rationed.
- What actually bound was the **category gate** plus ADR 0010's one-hero-mark
  cap. Those are what this ADR removes.

## Decision

**Amber marks what matters on a screen. Where it goes is a design decision.**

No category list. No per-screen budget. No ADR required to place amber somewhere
new. A screen may carry as many amber elements as the design calls for.

Two constraints survive, and they are the whole rule:

1. **Never as texture, pattern, or ornament.** Amber is not a way to fill space
   or add visual interest to a quiet area. If it is not marking something, it
   does not belong. This is the one piece of ADR 0009 §8 that carries forward
   intact.
2. **It must clear contrast on the surface behind it.** `accent` as text is
   4.34:1 on `sheet` and fails AA there; see the accent table in the style
   guide.

Existing amber placements are unaffected — the `ConcentricRings` brand mark, the
`/home` display-name eyebrow, amber CTAs, rank-1 markers. They stay exactly as
they are and simply no longer carry a justification.

## Consequences

- **ADR 0010 is superseded in full.** Its identity category and its
  two-placement bound are retired. Its reasoning stays on record as the argument
  for why a brand mark needed licensing under a category rule — which is
  precisely the cost this ADR decided not to keep paying.
- **The draft fourth-category ADR was deleted rather than shipped.** It was
  written and superseded inside the same uncommitted change; committing a
  born-superseded file would have been noise. Its substance is recorded in the
  Context above, and its number was reused for this decision.
- **Reviewers and agents lose a mechanical check and gain a judgment call.**
  "That isn't one of the sanctioned categories" is no longer a valid objection,
  and `CLAUDE.md` no longer instructs sessions to stop and ask before placing
  amber. The remaining objections are "that's decoration" and "that fails
  contrast" — both harder to argue and both more likely to be about something
  real.
- **Contrast is now the only mechanically checkable amber rule**, which raises
  its importance. The `sheet` failure above is the one live trap; it is stated
  in the style guide next to the accent table rather than buried here.
- **The style guide keeps a short note on what the rule used to be.** Without it,
  older review comments and code comments citing "in category" read as if they
  reference a rule still in force.
- **Amber density is now unbounded in principle**, and nothing prevents a screen
  from becoming loud. The guard is review, not a rule. If that turns out to be
  insufficient, the answer is a fresh look at the whole accent system rather
  than reinstating the category list.

## Revisit if

Screens start reading as noisy and review is not catching it — at which point
the problem is worth measuring (how many amber elements, on which surfaces)
before writing another rule. Do not reinstate the category gate by default: it
was removed because it cost more than it caught, and that finding would need to
be contradicted, not merely forgotten.
