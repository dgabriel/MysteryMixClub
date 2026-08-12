# ADR 0011: The amber accent stays `#F3821D`; the DS's `#c98b30` annotation is not adopted

**Status:** Accepted
**Date:** 2026-08-09

## Context

ADR 0009 adopted Design System v1.0 and left one item explicitly open. The DS
style tile annotates each color token with **both** an `oklch()` value and a hex
string, and for the accent the two disagree materially:

```
{ name: "--primary", value: "oklch(0.72 0.17 55)", hex: "#c98b30", role: "Amber accent" }
                              ^ renders #F3821D          ^ duller, and 17° more gold
```

ADR 0009 shipped the `oklch()` — it is what the approved tile actually paints —
and flagged the disagreement as something that "must be made once, centrally, in
`tailwind.config.js`, before any component ticket hard-codes around the current
values." This ADR closes that item.

The DS repo has since been cloned locally
(`github.com/dgabriel/DesignSystemForMysteryMixClub`, a Figma Make export),
which allowed a check that was not possible when ADR 0009 was written: does
either candidate appear anywhere outside the annotation table?

- `rgb(201,139,48)` — exactly `#c98b30` — **is** live in the tile as an amber
  border at `App.tsx:226, 371, 521, 639` (alphas 0.2 / 0.25 / 0.3).
- None of the six annotated **surface** hexes (`#0c0b0e`, `#181720`, `#201f2a`,
  `#282733`, `#e8e5db`, `#7e7c8a`) appears anywhere in the repo outside that
  table — no hex use, no `rgb()` twin.

That asymmetry is real and initially looked decisive for `#c98b30`. Weighed
against it:

- The tile's swatch (`App.tsx:512`) paints `value` — the `oklch()` — with the hex
  as a caption *beneath* it. The chip a viewer sees is `#F3821D`.
- The tile's own ACCENT RATIONALE prose (`App.tsx:525-526`) reads: "Warm amber at
  **OKLCH(0.72, 0.17, h55)** — the hue of a studio lamp backlighting a record."
  The DS states its accent in `oklch()`, in its own words.

Because the evidence genuinely cut both ways, `#c98b30` was **implemented and
rendered** on the real app (`MysteryMixClub-0fnf.19`) rather than decided on
paper. Dawn's verdict on seeing it: *"the buttons and text look dull."* The
change was reverted the same session.

## Decision

**`accent` stays `oklch(0.72 0.17 55)` (`#F3821D`). No token moves. ADR 0009's
open item is closed as "annotation not adopted."**

`accent-hairline` remains `rgba(201, 139, 48, 0.25)` — the DS's own border value,
which is `#c98b30`-based. It is therefore a *deliberate* second amber, confined
to 1px rules at ≤25% alpha, where the hue difference is not perceptible. It is
not an inconsistency to be "fixed" by re-pointing it at `accent`.

## Consequences

- **The DS's hex annotation column is confirmed non-authoritative in full**, not
  just for surfaces. Anyone reading `COLOR_TOKENS` in the DS tile should treat
  the `hex` field as stale metadata from the export tool. The `oklch()` field is
  the design.
- **The measured cost of the rejected option is recorded**, so it isn't
  re-derived: `#c98b30` is `oklch(0.683 0.128 72)` — −0.037 L, **−25% chroma**,
  **+17° hue**. The chroma drop is what read as "dull" at button scale; the hue
  shift shifts the mark from orange toward brass. Contrast would have stayed AA
  throughout (`card` 7.42:1 → 6.67:1), which is precisely why the numbers could
  not settle this and rendering it could.
- **Rendering beat computing.** The contrast tables, the gamut checks, and the
  live-`rgb()` corroboration all pointed at `#c98b30`; twenty minutes of
  implementing it and looking at it pointed the other way. For a
  *perceptual* decision, prefer putting the candidate on a real screen over
  strengthening the argument on paper.
- **`accent` as text on `sheet` fails AA at 4.34:1.** Found while evaluating the
  swap; it is a property of the *current* accent and was not recorded by ADR
  0009. Now stated as a rule in `docs/design/style-guide.md`: no amber text on a
  modal/drawer surface; an amber *fill* with `accent-foreground` is fine
  anywhere. This is the one durable code-adjacent finding from the exercise.
- **No token, component, or test changed.** The branch that implemented the swap
  was reverted in full. The only surviving artifacts are this ADR, the closure
  note on ADR 0009, and the style-guide contrast rule above.
- **`accent-surface` keeps hue 55**, matching `accent`. The swap had moved it to
  72 to track the new accent; that is reverted with everything else.

## Revisit if

Dawn's original Figma file (as opposed to the Figma Make export in the DS repo)
becomes available and names an accent — that file would outrank both the
generated `oklch()` and the generated hex. Short of that, treat this as settled:
the annotation has now been tested against the real UI and rejected, so
rediscovering the `#c98b30` / `#F3821D` disagreement in the DS repo is **not**
grounds to reopen it.
