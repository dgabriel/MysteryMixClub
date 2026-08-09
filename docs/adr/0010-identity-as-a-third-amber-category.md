# ADR 0010: Identity is a third amber category, alongside action and achievement

**Status:** Superseded by ADR 0012
**Date:** 2026-08-08

> **Retired 2026-08-09.** The category gate this ADR extends — and the
> one-hero-mark-per-screen bound it introduced — were removed by ADR 0012:
> amber placement is now a design decision, constrained only by "never
> decorative" and contrast. The brand mark keeps its amber; it simply no longer
> needs the licence this ADR granted. Kept for the reasoning, which is the
> argument for why a brand mark needed licensing at all under a category rule.

## Context

ADR 0009 adopted Design System v1.0, which replaced the retired "Rust once per
screen" counting rule with a category rule: amber (`accent`,
`oklch(0.72 0.17 55)`) appears on **action or achievement** and nowhere
decorative. That rule is stated in `docs/design/style-guide.md` and in the
CLAUDE.md quick reference, and every redesign ticket is bound by it.

R3 (`MysteryMixClub-0fnf.3`) translated the app's signature motif from the
Duchamp concentric ring to the design system's vinyl disc. The disc keeps the
component name `ConcentricRings` — a record literally is concentric rings — and
keeps its four props, so all 29 call sites across 19 files needed no edit.

That translation forced a question the two-category rule cannot answer.

The retired style guide gave the shared nav's brand mark a **standing
exception**: its single off-center Rust dot ("the fish", after the Duchamp
source artwork) was persistent *brand identity*, explicitly outside any
screen's one-Rust budget. The redesign has to do something with that
exception. A brand mark is plainly neither an action nor an achievement, so
under a strict reading of the two-category rule the mark cannot carry amber at
all, and the app loses its accent-colored identity mark entirely.

Two facts constrain the answer:

1. **The design system itself puts amber in the mark.** `VinylDisc` in the
   style tile (`App.tsx:110`) renders its centre label text in
   `oklch(0.72 0.17 55)`. The tile also uses the disc as its own footer brand
   mark (`App.tsx:653`). So amber-in-the-brand-mark is sanctioned by the
   approved design, not invented by us — but the tile never names the category,
   because a style tile does not have to reason about a rule it is
   simultaneously defining.

2. **The `accent` prop is not nav-only.** It is passed at hero marks on
   `AboutRoute`, `TermsRoute`, `PrivacyRoute`, `HelpRoute`, `OnboardingScreen`,
   `JoinClubScreen`, and `MyClubsScreen` — not just in `TopNav`. So the retired
   guide's narrow "the nav mark is exempt" wording does not cover the actual
   usage, and never did.

Leaving this unrecorded would mean every subsequent redesign ticket inherits an
undocumented amber use and has to guess whether it is a violation.

## Decision

**Identity is a third amber category, alongside action and achievement.** Amber
may mark the brand. This is a deliberate addition to the design system's
two-category rule, made here rather than silently absorbed into "achievement."

The category is bounded to exactly two placements:

- **the shared nav's persistent 28px mark** — chrome, present on every screen,
  outside any individual screen's reasoning about amber;
- **at most one amber hero mark in a screen's own content.**

A second hero mark in one screen's content is a violation.

The bound is two placements rather than the tidier "once per screen" because
one-per-screen would be a rule the app violates the moment it is written:
`AboutRoute`, `TermsRoute`, `PrivacyRoute`, `HelpRoute` and `JoinClubScreen`
each render `TopNav` *and* their own hero mark, and `MyClubsScreen` gets
`TopNav` via `AuthedLayout`. Writing a rule that six shipped screens already
break would make the guide unenforceable on day one. Nav chrome and screen
content are genuinely different scopes, and the rule now says so.

The exception licenses nothing else. It does not make amber available as
decoration, pattern, or ornament on the screens that use it.

## Consequences

- `ConcentricRings`'s `accent` prop changes meaning without changing its
  signature: it was "show the off-center Rust dot," it is now "show the amber
  centre label." All 29 call sites keep working untouched, and each one's
  intent — this is the brand mark — survives the translation.
- The retired "fish" exception is deleted from the style guide and replaced by
  this category. The fish was specific to the Duchamp artwork and has no
  referent in a vinyl-disc motif.
- **The disc's label carries amber as a fill, not as text.** The tile puts
  amber on the literal string `MMC` at `size * 0.072`, which is a 5.2px glyph
  at the 72px size the app actually ships — below the `text-micro` floor the
  guide already restricts to non-information-bearing chrome, so illegible at
  every size we render. Rendering no text also avoids adding visible text nodes
  to a component mounted at 29 call sites, where `getByText`/`textContent`
  assertions could pick them up. This is a deliberate divergence from a literal
  port of the tile.
- A future ticket that wants amber for a fourth reason must extend this ADR
  rather than reasoning by analogy from it. Three categories is already one
  more than the design system shipped with; the value of a category rule is
  that it is short.

  > **This is what retired the rule.** A fourth category was drafted on
  > 2026-08-09 (personal identity — the signed-in user's own name). On reading
  > it Dawn's response was that the constraint would be superseded regularly,
  > which made the gate a recurring tax rather than a rule. ADR 0012 removes it
  > instead of extending it a fourth time.

## Revisit if

- Real profile photos or per-club imagery land, giving screens a second
  identity object and making the two-placement bound ambiguous.
- The nav is restructured — in particular, if the design system's bottom-nav
  pattern is ever adopted (deliberately deferred during the redesign, since
  swapping `TopNav` for a bottom nav is a navigation behavior change), the
  "nav chrome is a separate scope" half of this decision needs re-checking.
- A designer decides the brand mark should not carry amber at all, in which
  case this ADR is superseded rather than amended — the two-category rule would
  simply stand as the DS wrote it.
