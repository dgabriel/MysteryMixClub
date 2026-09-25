# ADR 0038: Modals are white panels with a clear dark border

**Status:** Accepted
**Date:** 2026-09-25

MysteryMixClub-3fjt. Reverses the style guide's "modals stay dark on a light
page" rule (written with ADR 0013); the rest of ADR 0013 stands.

## Context

Every authed route renders on the light `paper` surface (ADR 0013), but modals
were kept dark: a `sheet` (Z4) panel over a dark scrim, on the reasoning that a
dialog sits above the page, so the light surface stops at the scrim.

Dawn found the "how it works" modal hard to read and asked for a white
background with black text. Measuring confirmed a real bug behind that: its
intro, step descriptions and footnote were `muted-foreground` on `sheet`,
3.49:1, below AA's 4.5:1. The report modal had the same problem, and its form
error used `destructive-text` (3.94:1 there). The style guide's R18 note
claimed every modal used `foreground` only; by the time these two modals
shipped that was no longer true. `sheet` is the one surface where half the dark
ramp fails, which made it an easy place to regress.

Two options were on the table:

- **Keep modals dark, fix the text to `foreground`.** Guide-compliant and
  smaller, but it keeps the trap: any grey text added later fails again.
- **Make modals white with a dark border (chosen).** Every modal uses the
  paper ramp, where each supporting token (`ink-muted` 4.67:1, `ink-accent`
  4.61:1, `ink-destructive` 4.56:1) clears AA, and the look matches the pages
  the modals open over.

## Decision

Every modal is a white `paper` panel with a 2px `ink` border and the
light-surface shadow (`shadow-art-ink`), over the existing dark scrim
(`bg-floor/80`). Everything inside uses the paper ramp and the `onPaper`
component variants.

The styling lives in one module, `frontend/src/components/modalSurface.ts`
(`MODAL_SCRIM`, `MODAL_PANEL`, `MODAL_CLOSE`), used by all five modals: the
"how it works" guide, what's new, report content, the Apple Music sign-in
interstitial, and the unsaved-changes prompt. `modalSurface.test.tsx` fails if
a modal loses the white panel or uses a dark-ramp text class.

`TopNav`'s mobile menu is navigation chrome, not a modal, and keeps its dark
`sheet`; the style guide already excludes `TopNav` from light-surface rules.

## Consequences

- The modal contrast failures are gone, and grey text in a modal is safe again.
- `sheet` now has one user: the mobile nav menu.
- The positive-green "complete" step marker in the guide measures about
  3.06:1 on white: enough for a non-text graphic (WCAG 1.4.11's 3:1), and the
  state is also announced as text to screen readers. There is no paper-ramp
  green; if one is added, use it here.
- A new modal must use `modalSurface.ts`, or the guard test (for the modals it
  renders) and the style guide will both say so.

## Revisit if

- A modal ever needs to open over a dark page (the pre-auth routes are still
  dark). A white panel over a dark page is fine visually, but check it then.
- A drawer or bottom sheet is introduced: decide then whether it follows this
  or stays chrome like the mobile menu.
