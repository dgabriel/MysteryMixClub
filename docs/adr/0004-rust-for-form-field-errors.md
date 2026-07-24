# ADR 0004: Rust marks invalid form fields, as a second Rust category alongside the one-per-screen decorative signal

**Status:** Accepted
**Date:** 2026-07-24

## Context

MYS-239 requires the new-club form's validation errors to read as obvious,
not the same low-contrast Ink text as ordinary body copy. Every error
message in the app today (`grep` confirmed this is app-wide, not local to
one form) renders as `font-mono text-[13px] text-ink` — visually
indistinguishable from helper/hint text on the same screen.

Rust (`#AD4F39`) is the palette's only color that reads as "error" or
"signal," but the style guide caps it at one use per screen, ever
("never use it twice in the same view"). MYS-239 also requires each form
field to validate independently rather than surfacing only the first
failure — meaning two or more fields can legitimately be invalid at the
same time. Under the strict one-Rust rule, only one of those simultaneous
errors could ever be marked, silently contradicting the "all fields
validate consistently" requirement the moment a second field failed.

Separately: `CreateClubScreen`'s header already spends the screen's Rust
budget on a purely decorative element — the off-center dot on its
`ConcentricRings` motif (`accent` prop). That decorative use predates this
form-error need and is not unique to this screen; roughly a dozen screens
across the app use the same `accent` dot as default header dressing, not as
a deliberate "most important thing on this screen" signal the way the guide
originally intended.

Alternatives considered:
- **Keep Rust to one instance, use weight/icon for additional errors**
  (dropped): produces a visibly inconsistent hierarchy — the 2nd/3rd
  invalid field would look "less wrong" than the first, which is backwards
  for a bug about *inconsistent* validation feedback.
- **No color at all, bold text + icon only** (dropped): weaker signal than
  the ask; doesn't resolve why Rust exists in the palette if the one
  situation that most wants a strong error color can't use it.

## Decision

Rust gets a second, independent budget: **form validation errors**, alongside
the existing one-per-screen decorative/informational budget. Every invalid
field on a form may render Rust (underline + inline error text with a small
warning icon) simultaneously, regardless of how many fields are invalid at
once — this is a category exception, not a per-screen count increase.

Decorative Rust yields to it. A screen containing a form does not also get
to spend Rust decoratively — `CreateClubScreen`'s `ConcentricRings` drops
`accent` as part of this change. A purely decorative flourish should never
contend with a functional error signal for the same visual resource; this
already matches how most other `accent` usages in the app function (default
header dressing, not a deliberate single-signal choice), so no other screen
needed to change.

The style guide (`docs/design/style-guide.md`) is updated to document this
as a named exception, structured the same way as the existing nav-brand
exception.

## Consequences

- Rust is no longer literally "one use per screen" — it is "one use per
  Rust *category* per screen," with exactly two categories defined so far:
  decorative/informational (1 per screen, unless it's the exempted nav
  brand mark), and form validation error (unlimited, scoped to invalid
  fields on forms). A third category should not be added without stopping
  to ask, per the original rule's spirit.
- Only `CreateClubScreen` and its shared field components (`TextField`,
  `DeadlineWindowField`) are updated by this ADR's implementation. Every
  other form's error text (`WaitlistForm`, `EmailEntryScreen`,
  `OnboardingScreen`, `ProfileScreen`, `MixDetailRoute`, `ClubHomeScreen`,
  `MyClubsScreen`, `AdminScreen`, `JoinClubScreen`) still renders the old
  understated Ink-only error style until similarly migrated — tracked as
  follow-on work, not resolved here.
- `CreateClubScreen` permanently loses its decorative Rust dot in the header
  ring motif in exchange for functional error marking.

## Revisit if

Multiple simultaneous Rust error states on one screen start reading as
visually noisy rather than clear (e.g. in user feedback or a design
review) — in which case consider capping the number of field-level Rust
markers shown at once, or moving to a single summary-style error banner
instead of per-field color.
