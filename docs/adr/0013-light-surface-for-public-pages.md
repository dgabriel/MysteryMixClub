# ADR 0013: The public pages are a light surface

**Status:** Accepted
**Date:** 2026-08-10
**Amends:** ADR 0009 (for the routes listed below only)
**Issue:** MysteryMixClub-0fnf.29, extended by MysteryMixClub-0fnf.30

> **Amended 2026-08-10 (same day), MysteryMixClub-0fnf.30.** Dawn extended the
> light surface to the authed `/home` screen: *"I also want the light background
> / dark cards."* Two things changed and are folded into the text below —
> `PublicSurface` was renamed **`PaperSurface`** (it now wraps an authed screen,
> so a name describing the audience had become a lie), and the **frame model**
> below is now a first-class part of this decision rather than a hypothetical.
> The scope is `/login`, `/about`, `/terms`, `/privacy`, `/help`, **and `/home`**.
>
> **Amended again 2026-08-11, MysteryMixClub-0fnf.32:** `/clubs/:id` joins them,
> so the scope is now those six plus the club detail page. Nothing else changed —
> the frame model held, and the screen needed no new tokens.
>
> **And again, MysteryMixClub-0fnf.33:** `/mixes/:id`. Eight routes. This one
> carried the first **modal** (`bg-sheet`, Z4), which stays dark — see
> "Modals" below.
>
> **And again, MysteryMixClub-0fnf.34:** `/clubs/new` and `/profile`. Ten
> routes.
>
> **And again, MysteryMixClub-0fnf.35:** `/admin` and `/admin/metrics` — the
> last two authed screens still on the dark ramp. Twelve routes. Every authed
> route is now paper; the four remaining dark screens are all pre-auth. The first
> screen that is *only* a form, so it exercised the field primitives'
> `onPaper` paths end to end (`TextField`, `DeadlineWindowField`, `FormError`)
> and the drawn checkbox. The checkbox is the one thing that needed a
> different token rather than a mechanical swap — see "Non-text graphics"
> below.

## Context

Design System v1.0 (ADR 0009) is a dark system. `floor` is the page, every card
is `card`, and — the part that turned out to matter — the **entire foreground
ramp was derived against near-black**.

On 2026-08-10, during the page-by-page review of the `redesign` branch, Dawn
asked to see the page background in white. It was applied as a one-line scratch
edit to `body` and the result was, predictably, unreadable: the wordmark
vanished, labels vanished, and the disc's shadow rendered as a black bruise.

The instruction that followed was to **keep it and fix the type**.

Measuring first is what made this decision tractable. Every foreground token in
the system fails WCAG AA on white:

| token | on `card` | on white | verdict |
|---|---|---|---|
| `foreground` | 17.83:1 | **1.09:1** | invisible |
| `muted-foreground` | 6.01:1 | 3.23:1 | large text only |
| `subtle-foreground` | 4.92:1 | 3.94:1 | large text only |
| `accent` | 7.42:1 | **2.62:1** | fails |
| `link` | 8.03:1 | **2.42:1** | fails |
| `destructive-text` | 6.79:1 | **2.86:1** | fails |

The two that matter most are the ones that *look* fine: `accent` and `link` are
saturated enough to be visible on white while sitting far below the 4.5:1 floor.
A light background was therefore never a background change. It is a second
foreground ramp, brand accent included.

## Decision

**`/login`, `/about`, `/terms`, `/privacy`, `/help`, `/home`, `/clubs/:id`,
`/mixes/:id`, `/clubs/new`, `/profile`, `/admin` and `/admin/metrics` render on
a light surface with their own derived `ink` ramp. Everything else stays exactly
as ADR 0009 specifies.**

Everything left on the dark ramp is now pre-auth: `/auth/verify`,
`/auth/reset-password`, `/onboarding` and `/invite/:token`.

Four parts:

### 1. The light surface is opt-in per route, never global

`body` stays `bg-floor`. The light surface is applied by wrapping a page in
`<PaperSurface>`. This is deliberate and is the single most important
implementation detail: the experiment that led here set the background on
`body`, which silently applied it to every authed screen too. A global light
background would have required re-deriving the whole app.

`TopNav` is excluded. It carries its own dark fill and reads as app chrome above
a light page.

### 1a. The frame model: light page, dark cards

A `bg-card` island inside a paper page **is its own dark surface**, so everything
within it correctly keeps the dark ramp. Only chrome sitting directly on the page
moves to `ink`. This is what makes the light surface affordable on authed screens:
`/home` needed no card-interior changes at all, because every club row already
renders through the `Card` primitive.

**The trap, and it is a sharp one.** Most text inside a card carries no color
class of its own — it *inherits*. That used to mean `body`'s `text-foreground`,
which was correct by accident. Wrapped in a `PaperSurface`, the same text
inherited `text-ink` and rendered at **1.65:1 on `card`** — every club name on
`/home` was very nearly invisible, and it passed a visual skim. The contrast
audit is what caught it.

`Card` therefore sets `text-foreground` **explicitly**, anchoring its contents to
the dark ramp regardless of the page around it. Any future dark island on a light
page owes the same self-anchoring.

### 2. The `ink` ramp keeps the dark ramp's hues

Each light-surface token is the **maximum chroma that still clears its WCAG
floor on `paper` while staying inside the sRGB gamut**, at the same OKLCH hue as
its dark counterpart. The two ramps are one system seen at two lightnesses, not
two palettes.

| token | value | hex | ratio on `paper` |
|---|---|---|---|
| `paper` | `oklch(1 0 0)` | `#FFFFFF` | — |
| `ink` | `oklch(0.34 0.02 80)` | `#3D372C` | 11.79:1 |
| `ink-muted` | `oklch(0.56 0.006 270)` | `#737478` | 4.67:1 |
| `ink-accent` | `oklch(0.574 0.142 55)` | `#B65D00` | 4.61:1 |
| `ink-accent-display` | `oklch(0.675 0.167 55)` | `#E27501` | 3.10:1 |
| `ink-link` | `oklch(0.56 0.119 235)` | `#007EB0` | 4.55:1 |
| `ink-destructive` | `oklch(0.595 0.241 25)` | `#EC0128` | 4.56:1 |
| `ink-hairline` | `rgba(0,0,0,0.12)` | — | — |

### 3. The brand amber darkens on paper, and that is the real cost

`accent` cannot survive on white. `#F3821D` is 2.62:1 there, and no amount of
lightness adjustment at that chroma reaches 4.5:1 inside the sRGB gamut — the
color leaves the gamut first. `ink-accent` is the honest answer: hue 55 held,
chroma spent down to 0.142, lightness down to 0.574. It is a burnt orange rather
than a vivid one.

**One exception.** The hero wordmark is `clamp(2.5rem, 7vw, 3.5rem)` at weight
800 — unambiguously WCAG "large text", where the floor is 3:1 rather than 4.5:1.
`ink-accent-display` spends that headroom on chroma and keeps the wordmark's
punch. **It is valid at hero size and nowhere else.**

### 3a. Non-text graphics take `ink-accent` even where a button takes `accent`

An amber **button fill** and an amber **checkbox fill** are not the same
problem, and `/clubs/new` is where that first bit.

A filled button carries its own high-contrast label, so the label is what makes
the control perceivable and the fill's ratio against the page is not what WCAG
1.4.11 is measuring. `accent` (`#F3821D`, 2.62:1 on paper) is fine there, and
that is what `Button`'s paper primary uses.

A checkbox has no label inside it. **The box is the only thing conveying its
state**, which makes it a non-text graphic owing 3:1 against the surface behind
it — both its resting edge and its checked fill. `accent` fails that on paper;
`ink-accent` clears it at 4.61:1, and a `paper` checkmark drawn on that fill
inherits the same 4.61:1.

**The rule:** on paper, if the amber shape *is* the information, it takes
`ink-accent`. If it merely carries text that is the information, `accent` is
allowed. This is why `/clubs/new`'s casual-mode checkbox is visibly a darker
orange than the `create` button directly beneath it. That difference is
correct, not drift.

### 4. Contrast is computed from the rounded 8-bit value

The first cut of this ramp was solved on floating-point sRGB and shipped
`ink-muted` at a theoretical 4.50:1. The browser painted `#76777B` — **4.47:1,
an AA failure**, caught only by measuring the live page with an in-browser
audit. Quantization to 8 bits can cost ~0.05, which is exactly the margin a
value solved *to* the threshold has.

Every value in the table above is verified against the rounded 8-bit color, and
carries margin over its floor.

### 1b. Modals stay dark, on any page

A modal is not *on* the page, it is *above* it, so the light surface stops at
the scrim. `bg-sheet` (Z4) with a `bg-floor/80` scrim is correct over a light
page as much as a dark one — dimming the page behind a dialog is what a scrim is
for.

This also means the `sheet` contrast rules still bite: `muted-foreground` is
3.49:1 there and `accent` as text is 4.34:1, so **modal copy stays
`foreground`**. `AppleMusicPlaylist`'s modal was deliberately excluded when the
rest of that component moved to the ink ramp, for exactly this reason.

## Consequences

**Shared components need a surface prop.** `TextField`, `Button`, `FormError`
and `ConcentricRings` render on both surfaces and gained an `onPaper` flag.
`WaitlistForm` renders *only* on public pages, so it takes the ink ramp
outright. This is viral by nature — any component newly placed on a public page
must be checked, not assumed.

**Only text-shaped tokens change.** `Button`'s `primary`, `ghost` and
`destructive` variants are fills carrying their own foreground and are correct
on any surface. `Badge` is a dark chip and reads correctly on paper unchanged.

**The disc stays dark.** `ConcentricRings` keeps its dark platter — a record is
dark, and inverting it would stop it being the motif. Only the shadow changes:
`shadow-art` is black at 0.7–0.95 alpha with a 1px *white* ring, which on paper
is both a bruise and an invisible edge. `shadow-art-ink` drops the alpha and
swaps the ring to black.

**Verified, not asserted.** An in-browser contrast audit resolves every rendered
text node's real painted color through a canvas (`getComputedStyle` returns
`oklch()` strings, which naive parsing reads as RGB triplets — the first version
of the audit did exactly that and produced fabricated failures). All six routes
plus the check-email and error states report zero violations, and `/profile` and
`/clubs/:id` were re-audited to confirm the still-dark screens did not regress.
Frontend suite: 581 passing.

The audit also skips `aria-hidden` / `role="presentation"` subtrees. The disc
motif sets its own label in near-black on amber, which is decorative and exempt;
counting it produced a false failure.

## What this does not do

- **It does not make the app light.** Authed screens, cards, modals and the
  whole Z0–Z4 ladder are untouched. A full light theme would mean re-deriving
  six shadow tokens, every surface, and the disc motif, and would supersede
  ADR 0009 outright rather than amend it.
- **It does not change `accent`.** ADR 0011 stands: `#F3821D` remains the brand
  amber on dark surfaces, which is everywhere except these five pages.
- **It does not settle pure white.** `paper` is `#FFFFFF` because that is what
  was asked for and approved on screen. The system is otherwise warm — the dark
  ramp's `foreground` is a warm off-white at hue 80 — and a warm paper
  (`#FAF8F4`) would sit closer to that character. Deliberately left as-is rather
  than quietly substituted; revisit if the pages read cold in use.
