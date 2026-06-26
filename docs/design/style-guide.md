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
| Sage        | `#7A9E82` | Primary surface, buttons, active states           |
| Sage Light  | `#A8C4AD` | Hover states, secondary surfaces                  |
| Sage Pale   | `#D4E3D7` | Badges, tags, subtle backgrounds                  |
| Rust        | `#B5533C` | Single accent — one use per screen/composition    |
| Ink         | `#2E2B27` | Primary text, headings                            |
| Muted       | `#8A8680` | Secondary text, labels, placeholders              |
| Border      | `#D6D2CA` | Dividers, input underlines, card borders          |

### Usage rules

- **Rust is a signal.** Use it for the single most important piece of information or action on a screen — a status badge, a card accent line, a CTA arrow. Never use it twice in the same view.
  - **Exception — the nav brand mark.** The concentric-rings mark in the shared top nav may carry its single off-center Rust dot ("the fish") as persistent *brand identity*. Because the nav is global chrome, this dot does **not** count against a screen's one-Rust budget: a screen may still use Rust once in its own content. This is the only standing exception to the one-use rule.
- **No pure black or pure white.** Cream is the lightest surface; Ink is the darkest text.
- **Sage family handles hierarchy.** Sage for primary, Sage Light for hover/secondary, Sage Pale for background tags.

---

## Typography

| Role            | Font                  | Size   | Weight  | Treatment                        |
|-----------------|-----------------------|--------|---------|----------------------------------|
| Display         | DM Serif Display      | 32–40px | Regular | Headlines, round names, page titles |
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
- Background: Sage `#7A9E82`
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
- Color: Rust `#B5533C`
- Underline with `text-underline-offset: 3px`
- Use for tertiary actions only

---

### Inputs

- **No box border.** Underline only: `border-bottom: 1px solid #2E2B27`
- Background: transparent
- Font: DM Mono, 13px
- Label above: DM Mono, 9px, ALL CAPS, letter-spacing 0.15em, Muted color
- Placeholder: Muted `#8A8680`
- Focus state: underline color shifts to Sage `#7A9E82`

---

### Cards

- Background: white (slightly lifted from Cream background)
- Border: `1px solid #D6D2CA`
- Border radius: `3px`
- Padding: `20px 24px`
- Optional left accent bar: `3px wide`, Rust `#B5533C` — only when the card requires special attention (active round, your submission due, etc.)

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
- Text: Sage `#7A9E82`
- Font: DM Mono, 9px, ALL CAPS, letter-spacing 0.15em
- Padding: `4px 10px`
- Border radius: `1px`

**Accent (Rust) — one per screen**
- Background: transparent
- Border: `1px solid #B5533C`
- Text: Rust `#B5533C`
- Same font/padding as default badge

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
- Round names can be poetic — *Late Summer Feels*, *The One That Got Away*
- Status labels are plain: `open`, `voting`, `closed`, `reveal`
- Error messages: direct and calm — "That link didn't work. Try another." not "Oops!"

---

*Last updated: May 2026*
