# MysteryMixClub — Style Guide

> Design System v1.0 — a dark room, a warm lamp, and the record. Compressed
> display type over airy body copy. Clean, simple, compact.

This guide replaces the Duchamp/Rotorelief cream–sage–rust system wholesale.
See ADR 0009 for why, and for what was deliberately not adopted along with it.

---

## Principles

1. **Restraint over decoration.** Every element earns its place.
2. **Amber means something happened or something can happen.** The accent marks
   action or achievement, never pattern.
3. **Elevation is the grid.** Depth, not whitespace alone, carries hierarchy in
   a dark system — but whitespace still does the rest.
4. **Quiet confidence.** Nothing shouts. The app feels handpicked, not
   algorithmic.

---

## Color

Colors ship as `oklch()` in `tailwind.config.js` — that is the authoritative
form, because it is what the approved style tile renders. Hex is given here for
contrast math and for the two files that cannot read a token
(`frontend/index.html`'s `theme-color`, `frontend/public/manifest.json`).

**Never write a raw hex in a component.** Use the named token.

### Surface ladder (Z0 → Z4)

The ladder is named for *what the surface is*, not by Z-number, so JSX reads
`bg-card` rather than `bg-z1`. The Z-numbers live on in the shadow keys.

| Token             | Hex       | Z  | Role                                                                     |
|-------------------|-----------|----|--------------------------------------------------------------------------|
| `floor`           | `#030304` | Z0 | The page background. The room the record is in. Nothing sits behind it.  |
| `sunken`          | `#070708` | —  | Chrome *below* content — bottom nav, footer, empty-state wells. Darker than a card on purpose. |
| `card`            | `#0D0D0F` | Z1 | The primary content surface: every card, list row, and panel body.       |
| `popover`         | `#151617` | —  | Detached transient surfaces — menus, dropdowns, tooltips. Also the input fill where an input needs one. |
| `tile`            | `#1A1B1C` | Z2 | Interactive tile, secondary button fill, inset chip inside a card.        |
| `panel`           | `#28292A` | Z3 | Elevated panel. Also the placeholder block behind offset album art.       |
| `sheet`           | `#3A3A3C` | Z4 | Modal, drawer, bottom sheet. Ceiling of the ladder.                       |
| `accent-surface`  | `#1A1512` | —  | Amber-tinted surface for an achievement or callout row — rank 1, an accent rationale block. |
| `track`           | `#393A3E` | —  | Unfilled portion of a progress or score bar.                             |

### Foreground ramp

| Token                | Hex       | Role                                                                     |
|----------------------|-----------|--------------------------------------------------------------------------|
| `foreground`         | `#F7F5F1` | Primary text and active icons. Warm off-white — never pure white.        |
| `muted-foreground`   | `#8E8F93` | Supporting text, captions, metadata, mono labels. The default for anything not primary. |
| `subtle-foreground`  | `#7F8084` | Inactive nav icons and glyphs; secondary notes on `floor`/`sunken`/`card`/`popover` **only**. |
| `faint-foreground`   | `#707174` | Non-essential annotation only. Fails AA on every surface.                |
| `ghost-foreground`   | `#5D5D5F` | Decorative and disabled glyph fills. **Never text, on any surface.**     |

### Accent (amber)

| Token               | Hex       | Role                                                                       |
|---------------------|-----------|----------------------------------------------------------------------------|
| `accent`            | `#F3821D` | The one accent. Interactive state, mix/season numbers, rank-1 indicators, focus ring. |
| `accent-hover`      | `#FDA258` | Hover step for an `accent` fill. Brightens, never dims. `accent-foreground` on it is 10.36:1. |
| `accent-foreground` | `#020202` | Text and icons *on* an amber fill. Near-black, no hue. 7.96:1.             |
| `accent-hairline`   | `rgba(201,139,48,0.25)` | Amber-tinted 1px rule bounding an `accent-surface` region.   |

There is exactly one accent name. Do not introduce `primary` as a second name
for the same color.

### Status

| Token                     | Hex       | Role                                                              |
|---------------------------|-----------|-------------------------------------------------------------------|
| `destructive`             | `#D40924` | Destructive **fill** — delete buttons, danger badges. Never text.  |
| `destructive-hover`       | `#BE222A` | Hover step for a `destructive` fill. **Deepens** where `accent-hover` brightens. |
| `destructive-foreground`  | `#F5F5F5` | Text on a `destructive` fill. 4.99:1.                             |
| `destructive-text`        | `#F2716A` | Form-error text and error underlines (ADR 0004). 6.77:1 on `card`. |
| `positive`                | `#5DA260` | Upward score delta, success.                                      |
| `negative`                | `#DE4E4B` | Downward score delta.                                             |

`destructive` as text is 3.57:1 on `card` — an outright AA failure. Error copy
always uses `destructive-text`; `destructive` is a fill color and nothing else.

The two hover steps move in opposite directions on purpose.
`destructive-foreground` on `destructive` has only 0.49 of headroom over
4.5:1, and brightening the red spends it (a lightness step to `#DF202E` drops
the label to 4.39:1, an AA failure). Deepening buys headroom instead — 5.58:1
— and `destructive-hover` still clears 3:1 against `card` (3.19:1) and `floor`
(3.39:1). It does not go deeper than L 0.52 because that is where the boundary
ratio would fall below 3:1.

**Every `oklch()` value in `tailwind.config.js` must be inside the sRGB gamut,
and the hex in this guide must be its true computed value.** This guide is the
source for contrast math, so a wrong hex propagates into every later
calculation. An out-of-gamut value is worse than merely imprecise: below one
JND of excursion, CSS Color 4's gamut-mapping binary search and naive clipping
disagree about the result, so the rendered color stops being knowable and any
ratio computed from it is fiction. Verify the linear-RGB channels land in
[0, 1] *before* mapping, and round-trip the hex back to oklch.

### Hairlines

Three steps, and only three. Do not write an arbitrary `rgba(255,255,255,…)`
border alpha. These tokens (and `accent-hairline`) carry a **fixed** alpha and
deliberately do not accept an opacity modifier — `border-hairline/50` is
silently ignored. Pick the right step instead.

| Token              | Value                     | Role                                                      |
|--------------------|---------------------------|-----------------------------------------------------------|
| `hairline-soft`    | `rgba(255,255,255,0.05)`  | Dividers *within* a card — list-row separators, gutters.  |
| `hairline`         | `rgba(255,255,255,0.09)`  | Default. Card edges, section rules, nav top border.       |
| `hairline-strong`  | `rgba(255,255,255,0.12)`  | Edge of a floating element that must read against artwork. |

Named `hairline`, not `border`, because the legacy `border` token stays defined
until the sweep ticket.

### Chart series (ADR 0008)

| Token     | Hex       | Role                                              |
|-----------|-----------|---------------------------------------------------|
| `chart-1` | `#F3821D` | Series 1. Identical to `accent`.                  |
| `chart-2` | `#00A692` | Series 2 (teal).                                  |
| `chart-3` | `#0089CA` | Series 3 (blue).                                  |
| `chart-4` | `#DE4E4B` | Series 4 (red).                                   |
| `chart-5` | `#D2B27C` | Series 5 (sand).                                  |

### Usage rules

- **Amber is a category rule, not a counting rule.** This is the single biggest
  behavioral change from the old guide. The retired system said "Rust once per
  screen" and reviewers counted. The new rule is: **amber appears on action or
  achievement, and nowhere decorative.** A screen may legitimately carry an
  amber CTA *and* an amber rank-1 marker — both are in category. What is
  forbidden is amber as pattern, texture, or ornament. Component tickets
  enforce the category, not a count.
  - **Exception — identity. Amber may mark the brand.** The `ConcentricRings`
    disc renders an amber centre label when `accent` is set, and that is the
    brand mark. Identity is a **third category alongside action and
    achievement**, and stating it that way is a deliberate addition to the
    design system's two-category rule — the DS's own style tile puts amber in
    the disc's centre label, so the mark carrying amber is sanctioned by the
    tile rather than invented here, but the DS never named the category, and a
    brand mark is plainly neither an action nor an achievement.

    Identity is bounded to two placements and no more:
    - the shared nav's persistent 28px mark, which is chrome, appears on every
      screen, and sits outside any individual screen's reasoning about amber;
    - **at most one** amber hero mark in a screen's own content (`AboutRoute`,
      `TermsRoute`, `PrivacyRoute`, `HelpRoute`, `OnboardingScreen`,
      `JoinClubScreen`, `MyClubsScreen`).

    The exception licenses nothing else. It does not make amber available as
    decoration, pattern, or ornament on the screens that use it, and a second
    hero mark is a violation. Do not delete the brand mark's amber as one.
  - **Exception — the About page's second decorative accent.** `AboutRoute.tsx`
    renders a small `<3` on the support section in the accent color. This was a
    deliberate override by Dawn under the old system and it survives the
    redesign as `text-accent`. **Any reviewer or agent flagging it as a
    violation is wrong.**
  - **Exception — Google's official Sign-In button (ADR 0007).**
    `frontend/src/components/GoogleSignInButton.tsx` sits outside this system
    entirely: Google's branding terms require their logo, colors, and type to
    render unmodified, so raw hex in `className` is correct there and only
    there. It currently renders Google's *light* button, which will sit oddly
    on a near-black page; Google publishes an official **dark** variant
    (`#131314` fill, `#8E918F` border, `#E3E3E3` text) and switching to it is
    still using Google's own values, not a reskin. That switch belongs to the
    auth-surface ticket.
  - **Exception — form validation errors (ADR 0004).** Invalid fields are their
    own color category, separate from amber entirely: every invalid field on a
    form may show `destructive-text` at once, however many are invalid, and
    this consumes nothing from the screen's amber reasoning. The category
    boundary is unchanged from the old guide — a third-party sign-in being
    denied or cancelled is *not* a form error and stays plain `foreground`
    text. Only the color changed (rust `#AD4F39` → `destructive-text`).
- **No pure black or pure white.** `floor` is the darkest surface;
  `foreground` is a warm off-white.
- **Platform brand colors are not design tokens.** Spotify `#1DB954`, Apple
  Music `#FC3C44`, YouTube `#FF0000`, Bandcamp `#1DA0C3`, Deezer `#EF5466`,
  Tidal `#00FFFF` are third-party brand values — the same category as the
  Google button. They do **not** go in `tailwind.config.js`. They live in one
  TS constant module with the ADR-0007 rationale in a header comment
  (`frontend/src/lib/platformBrand.ts`).
  - **A brand-tinted badge is valid on `card` or darker only** — that is
    `floor`, `sunken`, `card`, `popover`. Brand text is read against its own
    ~6% tint composited over the surface below, so the surface moves the
    ratio. YouTube red measures 4.74:1 on `card` but **4.22:1 on `tile`, an AA
    failure**; Bandcamp runs 6.41:1 on `floor` down to 5.23:1 on `tile`. This
    is a hard placement constraint, not a rounding concern. The full table
    lives in `platformBrand.ts`.
- **Charts use the chart ramp and never borrow `accent` as decoration.** Note
  that `chart-1` *is* `accent` — a single-series chart legitimately renders
  amber, and that is the one sanctioned amber-not-on-action case. Baselines use
  `hairline`; tick labels use `muted-foreground`, never a series color.
- **The `vinyl` avatar color is resolved, and there was never more than one
  avatar.** The old guide claimed five music-hardware illustrations; only
  `CassetteAvatar` was ever built, and `UserAvatar` is its only caller. R3 moved
  `UserAvatar` off `border`/`cream`/`vinyl` onto a `hairline` edge, a `tile`
  fill, and a `muted-foreground` stroke (5.37:1 on `tile`, well clear of the
  3:1 floor for non-text graphics). The legacy `vinyl` mid-blue now has no call
  sites and the name no longer collides with the disc motif.
- **The Ink time-signal badge is replaced by an urgency-graded chip.** The old
  guide's one sanctioned dark-filled chip (for deadlines and countdowns) worked
  by contrast inversion — the densest object on a light page — and has no
  analogue in a system where everything is already dark. Resolved in R2
  (`DeadlineChip`): the chip is **neutral by default** (`tile` fill,
  `hairline` edge, `foreground` text) and takes the amber callout treatment
  (`accent-surface` + `accent-hairline` + `accent`) **only while the deadline
  is actually closing**. Grading by urgency is what keeps it inside amber's
  category — "closing soon" is an action prompt, "closes jul 5" is a date — and
  it stops a list of mixes from rendering a page of amber chips. Neutral text
  is `foreground` rather than `muted-foreground` so a time signal still
  outranks a `Badge` status word; that prominence is what survives from the Ink
  fill.

---

## Elevation

Depth is a first-class part of this system. Six shadow tokens:

| Token       | Use                                                              |
|-------------|------------------------------------------------------------------|
| `shadow-z0` | Flat. No shadow.                                                 |
| `shadow-z1` | Barely lifted.                                                   |
| `shadow-z2` | Card at rest.                                                    |
| `shadow-z3` | Card on hover; elevated panel.                                   |
| `shadow-z4` | Modal, drawer, album art at rest. Carries its own 1px white ring. |
| `shadow-art`| Album artwork on hover. Carries its own 1px white ring.          |

**The shadow index does not track the surface index.** This is the rule people
get wrong. A card is a Z1 *surface* (`bg-card`) but wears a Z2 *shadow*
(`shadow-z2`) at rest, rising to `shadow-z3` on hover. Cards buy one step of
shadow above their lightness step. The only place `shadow-zN` pairs 1:1 with
surface N is a swatch grid demonstrating the ladder itself.

`shadow-art` is not "Z5" — artwork is a separate class of object, which is why
it gets a name instead of extending the numeric ladder. Album art is always the
brightest and highest thing on screen: `shadow-z4` at rest, `shadow-art` on
hover.

The white ring inside `shadow-z4` and `shadow-art` is **part of the shadow
token**. Do not add a `border` alongside it.

---

## Typography

Three faces, self-hosted as latin-subset woff2 in `frontend/public/fonts/`.
**Never add a `fonts.googleapis.com` `@import` or `<link>`** (MYS-240) — it was
a render-blocking first-paint request and was removed deliberately. The design
system repo ships exactly that import; it is not carried over.

| Role                       | Family                | Size                        | Weight | Transform | Tracking      | Line-height |
|----------------------------|-----------------------|-----------------------------|--------|-----------|---------------|-------------|
| Display / Hero             | Big Shoulders Display | `clamp(2.5rem, 8vw, 5.5rem)`| 800    | uppercase | `display-hero`| 0.88        |
| Display / Section head     | Big Shoulders Display | `clamp(2rem, 5vw, 3.25rem)` | 700    | uppercase | `display-snug`| 0.90        |
| Display / Screen title     | Big Shoulders Display | `1.75rem`                   | 800    | uppercase | `display-snug`| 0.90        |
| Display / Card title       | Big Shoulders Display | `0.875rem`                  | 700    | uppercase | inherit       | 1.0         |
| Display / Item title       | Big Shoulders Display | `0.875rem`                  | 600    | uppercase | inherit       | normal      |
| Body / Lead                | Libre Franklin        | `0.9375rem`                 | 400    | none      | normal        | 1.72        |
| Body / Default             | Libre Franklin        | `1rem`                      | 400    | none      | normal        | 1.72        |
| Body / Card copy           | Libre Franklin        | `0.875rem`                  | 400    | none      | normal        | 1.65        |
| Body / Small note          | Libre Franklin        | `0.7rem`–`0.8rem`           | 400    | none      | normal        | 1.6         |
| Mono / Data value          | JetBrains Mono        | `0.875rem`                  | 400    | none      | normal        | normal      |
| Mono / Score               | JetBrains Mono        | `0.75rem`                   | 400    | none      | normal        | normal      |
| Mono / Eyebrow (wide)      | JetBrains Mono        | `text-meta` (0.7rem)        | 400    | uppercase | `mono-wide`–`mono-widest` | normal |
| Mono / Button              | JetBrains Mono        | `text-label` (0.65rem)      | 400    | uppercase | `mono`        | normal      |
| Mono / Label (default)     | JetBrains Mono        | `text-mini` (0.6rem)        | 400    | uppercase | `mono`–`mono-caps` | normal |
| Mono / Badge               | JetBrains Mono        | `text-mini` (0.6rem)        | 400    | none/upper| `mono-sm`–`mono` | normal   |
| Mono / Chrome micro        | JetBrains Mono        | `text-micro` (0.55rem)      | 400    | uppercase | `mono`–`mono-wide` | 1.4–1.5 |

Display headings use `clamp()` as arbitrary values at the component level.
Those are responsive expressions, not scale steps, and are deliberately not
tokenized.

**Family utilities:** `font-display` (Big Shoulders Display), `font-sans` /
`font-body` (Libre Franklin), `font-mono` (JetBrains Mono). `font-body` is an
exact alias of `font-sans` — same stack, no behavioral difference — provided
only so a component reads `font-display` / `font-body` as a matched pair
instead of `font-display` / `font-sans`. **Prefer `font-sans`; reach for
`font-body` only when it sits directly alongside `font-display` in the same
block.** Libre Franklin is the page default via `body`, so most elements need
neither. (`font-serif` still resolves to DM Serif Display — legacy, deleted by
the sweep ticket. Do not use it in new work.)

### Rules

1. **Display is always uppercase**, always 600–800, always line-height
   0.88–1.0, always negative tracking. There is no lowercase display usage.
2. **Body is always 400.** Libre Franklin 500 ships for `label`/`button`
   element defaults but should stay rare; do not reach for it in running copy.
3. **Line-height 1.72 for running body copy.** Noticeably airier than the old
   system — that is the point. It is the counterweight to the compressed
   display face.
4. **Mono handles every label, number, badge, and button.** Never Libre
   Franklin for a label. Never Big Shoulders for a number.
5. **Uppercase plus positive tracking is the mono signature.** Mono at normal
   tracking is reserved for values — scores, durations, track counts.
6. **Figures are tabular for free** — JetBrains Mono is monospaced, so no
   `font-variant-numeric` rule is needed. Score columns are still
   right-aligned.

### Sub-`text-xs` scale

Tailwind's `text-xs` floor is 0.75rem; this system lives below it. Four steps,
each with its line-height baked in:

| Token        | Size              | Role                                                   |
|--------------|-------------------|--------------------------------------------------------|
| `text-micro` | 0.55rem (8.8px)   | Densest chrome only.                                   |
| `text-mini`  | 0.6rem (9.6px)    | Standard mono label. The most common label size.       |
| `text-label` | 0.65rem (10.4px)  | Mono button text and emphasized labels.                |
| `text-meta`  | 0.7rem (11.2px)   | Mono/body metadata and section eyebrows.               |

**Accessibility floor.** `text-micro` is 8.8px, below the 9px label floor the
old guide held through the MYS-186 contrast pass. **`text-micro` is for
non-information-bearing chrome only. The floor for any label a user must read
is `text-mini`.** If a `text-micro` string carries information, it is the wrong
size.

Sizes at or above 0.75rem use stock Tailwind (`text-xs`, `text-sm`,
`text-base`).

### Tracking

| Token                   | Value      | Use                                         |
|-------------------------|------------|---------------------------------------------|
| `tracking-display-hero` | `-0.025em` | The hero heading.                           |
| `tracking-display-tight`| `-0.02em`  | Large display headings below the hero.      |
| `tracking-display-snug` | `-0.01em`  | Section headings and smaller display type.  |
| `tracking-mono-sm`      | `0.04em`  | Inline data inside a chip.                   |
| `tracking-mono`         | `0.06em`  | Default mono tracking — labels, buttons, badges. |
| `tracking-mono-caps`    | `0.08em`  | Uppercase mono labels needing more air.      |
| `tracking-mono-wide`    | `0.10em`  | Section eyebrows and standings headers.      |
| `tracking-mono-widest`  | `0.12em`  | Hero subtitle and section numerals.          |

---

## Radius

| Token          | Value | Use                                                       |
|----------------|-------|-----------------------------------------------------------|
| `rounded-hair` | 1px   | Inner elements: art, badges, chips, bars, buttons.        |
| `rounded-tile` | 2px   | Containers: cards, sections, panels.                      |
| `rounded-full` | —     | Discs and avatars. Stock Tailwind.                        |

Nothing else. This system is nearly square by design; a 6px or 8px radius reads
as a different product.

---

## Spacing

**Spacing is stock Tailwind.** `tailwind.config.js` defines no `spacing` key
and no custom scale — there are no MMC spacing tokens, and the xs/sm/md/lg
names the retired guide listed never existed as code. Use Tailwind's default
scale (`p-4`, `gap-6`, `mt-12`, …) directly.

What this system does ask for is a **rhythm: an 8px base unit.** Prefer the
steps that land on it:

| Rhythm | Tailwind step | Value |
|--------|---------------|-------|
| half   | `1`           | 4px   |
| 1×     | `2`           | 8px   |
| 2×     | `4`           | 16px  |
| 3×     | `6`           | 24px  |
| 4×     | `8`           | 32px  |
| 6×     | `12`          | 48px  |
| 8×     | `16`          | 64px  |

Odd steps (`3`, `5`, `7`, `9`…) fall off the rhythm — reach for one only with a
reason, not by habit.

Conventions to hold to:

- Padding inside cards: `py-5 px-6` (20px / 24px)
- Section gaps: `gap-12` (48px)
- Page horizontal padding: `px-8` desktop, `px-4` mobile

---

## Components

Per-component specs land with their own redesign tickets (R2 onward). What is
established system-wide, and binding on all of them:

- **Cards** sit on `bg-card` with a `hairline` edge and `rounded-tile`, wearing
  `shadow-z2` at rest and `shadow-z3` on hover. Internal dividers use
  `hairline-soft`.
- **Album art** is `rounded-hair`, `shadow-z4` at rest, `shadow-art` on hover,
  and never carries a `border` — the ring is in the shadow token.
- **Inputs** stay underline-only; where an input needs a fill, it is `popover`.
  The invalid state uses `destructive-text` for both the underline and the
  error copy below the field (ADR 0004), with the small warning-triangle line
  icon inline before the message. Multiple fields may show it at once.
- **Buttons** use mono type: `text-label`, uppercase, `tracking-mono`,
  `rounded-hair`, and never a shadow — a button sits *on* a surface rather than
  being one. Four variants:
  - `primary` — an `accent` fill with `accent-foreground` text, hovering to
    `accent-hover`.
  - `ghost` — a `tile` fill with `foreground` text and a `hairline` edge,
    hovering one surface step to `panel`. It is a *fill*, not a transparent
    box: a hairline alone is ~1.1:1 and cannot be the sole thing identifying a
    control.
  - `destructive` — a `destructive` fill with `destructive-foreground` text,
    hovering to `destructive-hover`. **Target state, not current state:** the
    variant shipped in R2 with zero call sites. Delete affordances still render
    the amber `link` variant, and **R10** (`ClubHomeScreen.tsx:371`, delete
    club) and **R15** (`AdminScreen.tsx:452`, delete account) are the tickets
    that adopt it. Once they land, this is the rule: delete and other
    irreversible actions use `destructive`, never `link`, because amber means
    action or achievement and a delete is neither in the sense that matters.
  - `link` — a text button in `accent`, hovering to `foreground`.
- **Disabled controls** drop the box entirely — no fill, no edge — and drop the
  label to `muted-foreground` (6.01:1 on `card`, 6.38:1 on `floor`). Two things
  this is *not*:
  - Not `disabled:opacity-50`. Over an `accent` fill that puts the near-black
    label at 2.72:1, and on a near-black page opacity flattens a control into
    the background rather than quieting it.
  - Not a `tile` fill. `tile` is what an *enabled* `ghost` button already is,
    so a disabled primary beside a ghost "cancel" would read as a second
    secondary button.

  Removing the fill is the only direction that recedes without brightening:
  nothing is darker than the surface to recede into. Against a ghost button
  next to it, the disabled control has no fill, no edge, and a label at 6.01:1
  versus the ghost's 15.84:1. `cursor-not-allowed` supplements that; it is
  never the signal, because it does not exist on touch.

  **WCAG exempts inactive components from both 1.4.3 and 1.4.11**, so none of
  these ratios is an obligation — holding a disabled label to 4.5:1 exceeds the
  requirement rather than scraping past it. It is held anyway because a user
  still has to read what the unavailable control would have done.
- **Charts** follow ADR 0008 unchanged: **d3 for math only** — scales, extents,
  and shape generators; d3 never touches the DOM, the SVG is JSX, React owns
  every node. Tick text stays an HTML overlay at fixed size rather than SVG
  `<text>`, because viewBox-scaled text drops below the legible floor on narrow
  widths. Marks use `chart-1`…`chart-5`, baselines use `hairline`, tick labels
  use `muted-foreground`. No area fills, legends, tooltips, gridlines, or
  load-in animation. **Charts must not be placed on `sheet`** — two series
  colors fall below 3:1 there.

---

## Motif

The record is the visual signature. `ConcentricRings` **is** the vinyl disc: a
`card`-dark platter carrying a repeating-radial-gradient groove texture, a
centre label, a spindle hole, and `shadow-art` — whose `0 0 0 1px
rgba(255,255,255,0.10)` ring is the thing that makes it read as an object on a
near-black page, since `card` on `floor` is only ~1.3:1 on its own. Per the
elevation rule, that ring **is** the shadow token; do not add a `border`.

The component keeps the name `ConcentricRings` because a record literally is
concentric rings. The motif was translated, not replaced, and all 29 existing
call sites across 19 files needed no edit.

| Prop        | Default | Meaning                                                                 |
|-------------|---------|-------------------------------------------------------------------------|
| `size`      | `96`    | Pixel diameter. Ships from 28px (nav mark) to 88px (page hero).         |
| `spinning`  | `false` | Applies `animate-rotate-rings` — a 6s linear loop, matching the tile.   |
| `accent`    | `false` | Amber centre label — the brand mark. See the identity exception under Color. |
| `className` | `""`    | Passthrough, appended last so a caller can override.                    |

The disc is a `<div>`, not an `<svg>`, because groove spacing has to be in
**physical pixels**: a viewBox-scaled stroke that reads correctly at 88px
collapses to sub-pixel mush at 28px, and CSS has no SVG equivalent of
`repeating-radial-gradient`. It stays `role="presentation"` / `aria-hidden`.

**Degradation.** The style tile drops its secondary label below 60px; this
component uses that same 60px threshold to drop the spindle hole (under ~4px it
is noise rather than detail) and to tighten the groove period from 4px to 3px,
because a 28px mark leaves only a ~6px annulus outside the label to carry
texture. At 28px the mark correctly resolves to its irreducible form: a dark
disc with an amber centre.

**Do not use the motif decoratively.** It appears in one place per screen,
purposefully.

---

## Iconography

- Minimal line icons only — no filled icons
- Stroke weight: 1–1.5px
- Size: 16px default, 12px inline
- Color: `subtle-foreground` for inactive chrome glyphs (on `floor`, `sunken`,
  `card`, or `popover` only), `foreground` for active, `accent` for selected

---

## Motion

- Transitions: `150ms ease` for hover states
- Page transitions: subtle fade, `200ms`
- No bounces, no spring physics — this is not playful, it is quiet
- **Every continuous or looping animation must be listed in the
  `prefers-reduced-motion` block in `frontend/src/index.css`.** The DS
  introduces a continuous vinyl rotation, which is a stronger motion claim than
  anything the app currently ships; the component that adds it also adds it to
  that selector list.

---

## Accessibility

MYS-121 and MYS-186 darkened the old palette twice specifically to clear
4.5:1. That commitment carries forward — a dark system does not get a pass.

- **Normal text needs 4.5:1.** Non-text graphics and large text (≥18.66px bold
  / ≥24px) need 3:1.
- **Restricted foregrounds.** `subtle-foreground` is valid on `floor`,
  `sunken`, `card`, and `popover` only — it fails on `tile` and above.
  `muted-foreground` fails on `sheet`, so **modals and drawers use
  `foreground` for all text**. `faint-foreground` fails everywhere and is
  annotation only. `ghost-foreground` is never text.
- **Tightest pair in the system:** `muted-foreground` on `panel` at 4.51:1. Any
  Z3 lightness adjustment breaks it. Re-run the contrast pass after any
  surface change.
- **Verified at the end of the redesign (R18).** Every shipped text/surface
  pair was recomputed from the `oklch()` values that actually render. The only
  pairs below 4.5:1 anywhere in the system are on `sheet` — `muted-foreground`
  3.49, `destructive-text` 3.94, `accent` 4.33 — and the app's two Z4 surfaces
  (the unsaved-changes modal and Apple's reassurance interstitial) both carry
  `foreground` text only, so none of the three is actually rendered. `panel`
  remains the tightest pair in use.
- **Amber text in a modal** is 4.33:1 on `sheet` — it must be large or bold
  there, or not amber.
- **A control is never identified by a hairline alone.** Hairlines are
  ~1.2:1 and invisible to the contrast formula, and a `tile`-on-`card` step is
  only 1.126:1. WCAG 1.4.11 requires 3:1 for a boundary that is the *sole* means
  of identifying a control, so every control must also carry a text or icon
  affordance. This is the most likely a11y regression a dark system
  introduces.
- **Focus rings.** `ring-accent` is comfortable on `card` (7.43:1), but an
  amber ring on an amber-filled button is invisible — those need
  `ring-foreground` or a ring offset.
- **`text-micro` is chrome only** — see Typography.

---

## Voice & Tone (UI copy)

- Short, confident, lowercase where possible
- No exclamation marks
- No em dashes in UI copy — use a period, comma, or parentheses instead
- Mystery mix names can be poetic, e.g. *Late Summer Feels*, *The One That Got Away*
- Status labels are plain: `open`, `voting`, `closed`, `reveal`
- Error messages: direct and calm, e.g. "That link didn't work. Try another." not "Oops!"

---

*Last updated: August 2026 — replaced wholesale by Design System v1.0
(MysteryMixClub-0fnf.1, ADR 0009). The retired Duchamp/Rotorelief system
(Cream `#F0EDE6`, Sage `#506755`, Rust `#AD4F39`, Gold `#83681A`, DM Serif
Display / DM Mono) is gone; its tokens remain **defined** in
`tailwind.config.js` at their original values only so un-migrated surfaces keep
rendering during the migration, and the R18 sweep ticket deletes them. Do not
use a legacy token in new work, and do not alias one onto a new value.*
