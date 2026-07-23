# MysteryMixClub — Style Guide

> Inspired by Marcel Duchamp's *Rotorelief* series. Clean, simple, compact.

---

## Principles

1. **Restraint over decoration.** Every element earns its place.
2. **One accent per composition.** Rust appears once — as a signal, never as pattern.
3. **Breathing room is structure.** Whitespace is not emptiness; it's the grid.
4. **Quiet confidence.** Nothing shouts. The app feels handpicked, not algorithmic.

---

## Color

| Name        | Hex       | Role                                              |
|-------------|-----------|---------------------------------------------------|
| Cream       | `#F0EDE6` | Primary background                                |
| Sage        | `#506755` | Primary surface, buttons, active states           |
| Sage Light  | `#A8C4AD` | Hover states, secondary surfaces                  |
| Sage Pale   | `#D4E3D7` | Badges, tags, subtle backgrounds                  |
| Rust        | `#AD4F39` | Single accent — one use per screen/composition    |
| Gold        | `#83681A` | Achievement signal — winner and most-noted moments |
| Vinyl       | `#6B7EB5` | Avatar illustrations only — the 5 music hardware icons |
| Ink         | `#2E2B27` | Primary text, headings                            |
| Muted       | `#6D6A66` | Secondary text, labels, placeholders              |
| Border      | `#D6D2CA` | Dividers, input underlines, card borders          |

### Usage rules

- **Rust is a signal.** Use it for the single most important piece of information or action on a screen — a status badge, a card accent line, a CTA arrow. Never use it twice in the same view.
  - **Exception — the nav brand mark.** The concentric-rings mark in the shared top nav may carry its single off-center Rust dot ("the fish") as persistent *brand identity*. Because the nav is global chrome, this dot does **not** count against a screen's one-Rust budget: a screen may still use Rust once in its own content. This is the only standing exception to the one-use rule.
- **Gold is an achievement signal.** Use it exclusively for achievement moments: winner and most-noted reveals (the crown icon on section headings) and a **completed club** (the crown + thin left accent on a finished club's card). Do not use Gold decoratively or expand it to other contexts without updating this guide.
- **Vinyl is for avatar illustrations only.** The five music hardware SVG avatars (cassette, record, boom box, walkman, flying V) use Vinyl as their stroke/fill. Do not use Vinyl outside of avatar illustration contexts.
- **Ink as a surface is a time signal.** An Ink-filled chip with Cream text is reserved for time-critical information — deadlines and countdowns (see Badges → Time signal). One per screen; never decorative.
- **No pure black or pure white.** Cream is the lightest surface; Ink is the darkest text.
- **Sage family handles hierarchy.** Sage for primary, Sage Light for hover/secondary, Sage Pale for background tags.

---

## Typography

| Role            | Font                  | Size   | Weight  | Treatment                        |
|-----------------|-----------------------|--------|---------|----------------------------------|
| Display         | DM Serif Display      | 32–40px | Regular | Headlines, mystery mix names, page titles |
| Display Italic  | DM Serif Display      | 24–32px | Italic  | Subheads, taglines, flavor text  |
| Body            | DM Mono               | 13px   | 300     | Descriptions, paragraph text     |
| Label           | DM Mono               | 9–11px | 400     | ALL CAPS, letter-spacing 0.15em  |
| UI / Buttons    | DM Mono               | 11px   | 400     | ALL CAPS, letter-spacing 0.12em  |
| Accent          | DM Mono               | 11px   | 400     | Rust color, underline, links     |

### Rules

- Labels and buttons are always ALL CAPS with generous letter-spacing.
- Body text uses light weight (300) — avoid medium or bold in running copy.
- Italic display is reserved for secondary information — don't compete with display upright on the same screen.

---

## Spacing

Base unit: **8px**

| Token    | Value |
|----------|-------|
| xs       | 4px   |
| sm       | 8px   |
| md       | 16px  |
| lg       | 24px  |
| xl       | 32px  |
| 2xl      | 48px  |
| 3xl      | 64px  |

Padding inside cards: `20px 24px`
Section gaps: `48px`
Page horizontal padding: `32px` (desktop), `16px` (mobile)

---

## Components

### Buttons

**Primary**
- Background: Sage `#506755`
- Text: Cream `#F0EDE6`
- Font: DM Mono, 11px, ALL CAPS, letter-spacing 0.12em
- Padding: `10px 22px`
- Border radius: `2px`
- No shadow

**Ghost**
- Background: transparent
- Border: 1px solid Border `#D6D2CA`
- Text: Ink `#2E2B27`
- Same font/padding as primary

**Text / Link**
- Background: none
- Color: Rust `#AD4F39`
- Underline with `text-underline-offset: 3px`
- Use for tertiary actions only

---

### Inputs

- **No box border.** Underline only: `border-bottom: 1px solid #2E2B27`
- Background: transparent
- Font: DM Mono, 13px
- Label above: DM Mono, 9px, ALL CAPS, letter-spacing 0.15em, Muted color
- Placeholder: Muted `#6D6A66`
- Focus state: underline color shifts to Sage `#506755`

---

### Cards

- Background: white (slightly lifted from Cream background)
- Border: `1px solid #D6D2CA`
- Border radius: `3px`
- Padding: `20px 24px`
- Optional left accent bar: `3px wide`, Rust `#AD4F39` — only when the card requires special attention (active mystery mix, your submission due, etc.)

**Card anatomy (top to bottom):**
1. Eyebrow — Label style, Muted
2. Title — DM Serif Display, 20px
3. Subtitle — DM Mono, 11px, Muted, 300 weight
4. Divider — 1px Border color
5. Meta row — small stats and badge

---

### Badges

**Default (Sage)**
- Background: Sage Pale `#D4E3D7`
- Text: Sage `#506755`
- Font: DM Mono, 9px, ALL CAPS, letter-spacing 0.15em
- Padding: `4px 10px`
- Border radius: `1px`

**Accent (Rust) — one per screen**
- Background: transparent
- Border: `1px solid #AD4F39`
- Text: Rust `#AD4F39`
- Same font/padding as default badge

**Time signal (Ink) — time-critical information only**
- Background: Ink `#2E2B27`
- Text: Cream `#F0EDE6`
- Font: DM Mono, 11px, ALL CAPS, letter-spacing 0.12em
- Padding: `4px 10px`
- Border radius: `1px`
- May carry one small line icon (12px, stroke `currentColor`)
- Reserved for the moment a player must act by — deadlines and countdowns.
  Never for status, achievement, or decoration. Like Rust, it is a signal:
  **one time-signal chip per screen.** (Added Jul 2026 — the palette's only
  sanctioned Ink-filled surface; it exists because the Sage family cannot
  produce enough contrast for time-critical info without stealing Rust.)

---

## Motif

The **concentric ring** is the visual signature of MysteryMixClub — a direct reference to the Duchamp Rotorelief. It appears as:

- The logo mark
- A loading / empty state illustration
- A subtle background watermark on hero sections (low opacity)

The rings use the Sage color family (Sage Pale → Sage Light → Sage → Sage), layered inward. A single small Rust element — like the fish in the source artwork — may appear off-center within the rings.

**Do not use the motif decoratively.** It appears in one place per screen, purposefully.

---

## Iconography

- Minimal line icons only — no filled icons
- Stroke weight: 1–1.5px
- Size: 16px default, 12px inline
- Color: Muted for inactive, Ink for active, Sage for selected

---

## Motion

- Transitions: `150ms ease` for hover states
- Page transitions: subtle fade, `200ms`
- No bounces, no spring physics — this is not playful, it is quiet
- Loading states: a slowly rotating concentric ring (the motif), not a spinner

---

## Voice & Tone (UI copy)

- Short, confident, lowercase where possible
- No exclamation marks
- No em dashes in UI copy — use a period, comma, or parentheses instead
- Mystery mix names can be poetic, e.g. *Late Summer Feels*, *The One That Got Away*
- Status labels are plain: `open`, `voting`, `closed`, `reveal`
- Error messages: direct and calm, e.g. "That link didn't work. Try another." not "Oops!"

---

*Last updated: July 2026 — Sage and Muted darkened for WCAG 2.1 AA text contrast
(MYS-186): Sage `#7A9E82` → `#506755`, Muted `#8A8680` → `#6D6A66`. Both now clear
4.5:1 against Cream and, for Sage, against Sage Pale (the badge background).
Sage Light and Sage Pale are unchanged — they're never used as text color. Added
the Time signal (Ink) badge variant*

*Updated again July 2026 — Rust and Gold darkened for WCAG 2.1 AA contrast
(MYS-121): Rust `#B5533C` → `#AD4F39` (4.21:1 → 4.54:1 against Cream), Gold
`#C9A028` → `#83681A` (2.10:1 → 4.54:1 against Cream, since Gold's only use —
the achievement crown icon — needs to clear the 3:1 non-text minimum with
headroom). Muted text sitting on a Sage Pale background (badges, active-state
cards, hover tints) now renders as Sage instead of Muted, since Muted-on-Sage-Pale
was 4.04:1 (fails 4.5:1) while Sage-on-Sage-Pale is the palette's established,
already-compliant combo (4.62:1).*
