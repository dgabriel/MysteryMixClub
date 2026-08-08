# ADR 0009: Adopt the Design System v1.0 dark/amber visual language wholesale, on Tailwind v3, without shadcn

**Status:** Accepted
**Date:** 2026-08-08

## Context

The app has shipped since inception on the Duchamp/*Rotorelief* system
documented in `docs/design/style-guide.md`: a cream page (`#F0EDE6`), a sage
family for hierarchy, rust as a single once-per-screen accent, gold for
achievement, and DM Serif Display over DM Mono. That system was darkened twice
for WCAG AA (MYS-186, then MYS-121) and its fonts were pulled off the Google
Fonts CDN and self-hosted (MYS-240), so it carries real accumulated
correctness, not just taste.

Dawn produced a new design system as a standalone React repo (the "DS repo") —
a dark near-black surface ladder, a single amber accent, Big Shoulders Display
/ Libre Franklin / JetBrains Mono, and an explicit elevation model. It is a
total replacement of the visual language, not an iteration on it: no color,
no face, and no accent rule survives. The epic tracking the port is
`MysteryMixClub-0fnf`; this ADR is written at the start of it
(`MysteryMixClub-0fnf.1`, the foundation ticket), not after.

The DS repo is a design artifact, not a library we can depend on. Deciding
*which parts of it are the design* — and which are incidental scaffolding from
the tool that produced it — is the actual decision here, and it is the kind a
future contributor could easily get wrong by assuming "adopt the design system"
meant "adopt the repo."

Constraints and findings that shaped the call:

- The DS repo is built on **Tailwind v4** with CSS-first `@theme` config. Our
  frontend is Tailwind v3 with `tailwind.config.js`, wired into a Vite build,
  a `@apply`-using `index.css`, and 336 `font-mono` / 178 `text-ink` / 230
  `text-muted` usages across 62 components.
- The DS repo contains a `components/ui/*` directory of **stock, unmodified
  shadcn/Radix boilerplate**, and a `guidelines/Guidelines.md` that is an
  untouched template stub containing a placeholder Button spec
  ("Primary / Secondary / Tertiary", "filled with the primary brand color").
  Neither is MMC design content.
- The DS repo's `fonts.css` `@import`s from `fonts.googleapis.com` — exactly
  the render-blocking first-paint request MYS-240 removed.
- The DS's `App.tsx` annotates each color token with a hex string *and* an
  `oklch()` value, and the two disagree materially (see Consequences).
- `develop` auto-deploys to staging and `main` is live in production, so a
  half-migrated palette cannot sit on either branch.

## Decision

**Adopt the DS repo's visual system wholesale — its tokens, elevation model,
type scale, and accent rule — and nothing else from the repo.**

Specifically:

1. **The design is the tokens, not the repo.** What is ported is
   `theme.css` and the style tile in `App.tsx`: the Z0–Z4 surface ladder, the
   foreground ramp, the amber accent, the status and chart ramps, the three
   hairline steps, the six elevation shadows, the sub-`text-xs` type scale, the
   2px/1px radii, and the tracking steps. These land in
   `frontend/tailwind.config.js` as named Tailwind tokens.

2. **Tailwind stays v3.** The DS repo's v4 setup is incidental to its tokens —
   the tokens are color/size/shadow values that express identically in a v3
   `theme.extend` block. Migrating our build to v4 would touch the Vite
   pipeline, the PostCSS config, every `@apply` in `index.css`, and the
   arbitrary-value syntax across 62 components, all for zero visual difference.
   That is unnecessary functional risk stacked on top of an already-total
   visual change, and it would make any build regression during the redesign
   ambiguous between "the tokens are wrong" and "the build is wrong."

3. **shadcn and Radix are not adopted.** The DS repo's `components/ui/*` is
   stock generated boilerplate that Dawn did not modify; it carries no MMC
   design decisions. Adopting it would mean taking on a component library, its
   dependency tree, and its own visual defaults in order to gain nothing the
   tokens don't already give us. MMC's components are rebuilt in place against
   the new tokens, ticket by ticket. `guidelines/Guidelines.md` is likewise a
   template stub and must not be cited as a spec by any later ticket.

4. **Fonts stay self-hosted.** Big Shoulders Display, Libre Franklin, and
   JetBrains Mono ship as latin-subset `woff2` in `frontend/public/fonts/`,
   declared with local `@font-face` blocks. The DS repo's
   `fonts.googleapis.com` `@import` is deliberately not carried over — MYS-240
   removed exactly that request for first-paint performance, and the DS repo
   makes the wrong thing look like the default.

5. **Legacy tokens stay defined, never aliased.** The cream/sage/rust/gold
   color keys, `fontFamily.serif` → DM Serif Display, the legacy
   `tracking-label`/`tracking-ui` steps, and the four DM `@font-face` blocks
   all remain in place at their **original values** for the duration of the
   migration, so surfaces whose ticket hasn't landed yet keep rendering. They
   are never re-pointed at a new value — an aliased token silently changes
   un-migrated screens and destroys the ability to tell migrated from
   un-migrated by reading the JSX. A dedicated sweep ticket
   (`MysteryMixClub-0fnf.18`) deletes them as its own reviewable change.

6. **The `redesign` integration branch stands in for `develop` for the whole
   effort.** The foundation ticket flips `body` to the dark base outright
   rather than hiding the new system behind an opt-in `.v2` wrapper class.
   Consequently every un-migrated route renders dark-on-dark and unreadable
   until its ticket lands — expected and accepted. All R-tickets branch from
   and merge into `redesign`; `redesign` merges to `develop` exactly once, when
   the redesign is complete and human-tested. No individual R-ticket goes to
   `develop`, because `develop` auto-deploys to staging and `main` is live in
   prod. The alternative — a throwaway `.v2` class promoted to `body` by the
   sweep — was rejected because a half-dark/half-cream staging build is harder
   to review than a branch that is clearly, uniformly broken until done.

7. **`destructive-text` is added to the DS palette.** The DS ships
   `destructive` (`oklch(0.55 0.22 25)`) with no separate text variant, but
   that value is **3.57:1 on `card`** — an outright WCAG AA failure as text, on
   the app's most accessibility-sensitive surface (form errors, ADR 0004).
   Shipping it as error text would silently undo the MYS-121/MYS-186 contrast
   work. We therefore add `destructive-text` (`oklch(0.70 0.16 25)`, 6.77:1 on
   `card`, 5.09:1 on `panel`). `destructive` remains a **fill-only** token.

8. **Amber's rule is a category, not a count.** The old system's "Rust once per
   screen" was enforced by counting. It is replaced by: amber appears on
   *action or achievement* and nowhere decorative. A screen may carry both an
   amber CTA and an amber rank-1 marker. This is the largest behavioral change
   for reviewers and is stated as such in the rewritten style guide.

9. **Third-party brand colors are not tokens.** Streaming-platform brand hexes
   (Spotify, Apple Music, YouTube, Bandcamp, Deezer, Tidal) stay out of
   `tailwind.config.js`, in the same category as the Google Sign-In button
   (ADR 0007) — they are not ours to name as design tokens.

## Consequences

- **`docs/design/style-guide.md` is replaced wholesale.** It is enforced by
  `CLAUDE.md` on every session, so a stale guide would actively misdirect every
  subsequent ticket. `CLAUDE.md` carries a quick-reference token table and is
  updated to the new tokens and the amber category rule. `AGENTS.md` is
  **deliberately not** updated — despite the name it is not a copy of
  `CLAUDE.md`; it is a bd/beads workflow file containing no design content at
  all, and adding a token table to it would create a second place to forget to
  update.
- **The DS's own hex annotations are wrong and were not shipped.** `App.tsx`
  labels each token with a hex that does not match the `oklch()` beside it —
  `--background` is annotated `#0c0b0e` but computes to `#030304`; `--primary`
  is annotated `#c98b30` but computes to `#F3821D`, a much brighter amber. The
  `oklch()` strings are what the approved tile actually renders, so those ship
  verbatim and the hex column is treated as stale annotation. **If design
  intended the duller annotated values, the whole ladder shifts up ~0.045 L and
  the accent changes materially** — that correction must be made once,
  centrally, in `tailwind.config.js`, before any component ticket hard-codes
  around the current values. Flagged here so it is a known open item rather
  than a discovery in R12. (Relatedly, the tile's prose at App.tsx:629–632
  contradicts its own `SURFACES` constant; the code was taken as authoritative.)
- **The default hairline ships at 0.09, not the 0.07 the ticket specified.**
  `MysteryMixClub-0fnf.1` called for `border: rgba(255,255,255,.07)`. Shipped
  instead: three steps — `hairline-soft` 0.05, `hairline` **0.09**,
  `hairline-strong` 0.12. 0.09 is `theme.css`'s actual `--border`; 0.07 was one
  of seven different border alphas annotated across `App.tsx` and is not the
  DS's own default. The three-step ladder exists because collapsing those seven
  ad hoc alphas into named steps is the only way to stop the next seven from
  appearing. Recorded as a deliberate deviation from the ticket text, not an
  oversight.
- **Every *opaque* color token carries the `<alpha-value>` placeholder.**
  Tailwind v3 passes arbitrary color strings through untouched, so `bg-card/50`
  would silently produce no opacity without it. This is a permanent authoring
  rule for anyone adding an opaque token. The four intentionally-translucent
  tokens — `hairline-soft`, `hairline`, `hairline-strong`, `accent-hairline` —
  are the deliberate exception: they ship as fixed-alpha `rgba()` and therefore
  **ignore opacity modifiers** (`border-hairline/50` has no effect). Their
  alpha *is* their meaning, and there are exactly three sanctioned hairline
  steps; making them modifier-capable would restore the arbitrary-alpha
  freedom the three-step ladder was created to remove (the source tile used
  seven different border alphas across its sites). Recorded because "some
  tokens accept `/50` and four don't" is otherwise a silent trap.
- **The token set is defined twice, on purpose.** The same colors, elevation
  shadows, and radius appear as named Tailwind tokens in `tailwind.config.js`
  *and* as DS-named CSS custom properties in a `:root` block in `index.css`
  (`--background`, `--card`, `--secondary`, `--muted`, `--foreground`,
  `--muted-foreground`, `--primary`, `--border`, `--radius`, `--shadow-z0`…
  `--shadow-art`). The custom properties exist because component code ported
  out of the DS style tile references `var(--card)` / `var(--primary)` /
  `var(--radius)` directly, and without them those would resolve to nothing and
  fail silently — the worst possible failure mode mid-redesign. The two
  definitions are **not** derived from one another: generating the `:root`
  block via Tailwind's `theme()` would drag the `<alpha-value>` placeholder
  into a raw `var()` consumer, where nothing substitutes it and it leaks into
  the declaration. The cost is a genuine duplication that must be edited in
  both places; both blocks carry a comment saying so. The sweep ticket should
  reassess whether the `:root` half can be dropped once no un-ported DS code
  remains.
- **`oklch()` sets a browser floor** of Chrome 111+ / Safari 15.4+ / Firefox
  113+ (all 2022–2023). Acceptable, but it is a real floor and older browsers
  will render unstyled colors rather than degrade.
- **Overriding `fontFamily.mono` re-skins 336 existing usages in one line.**
  Intended: JetBrains Mono is the new data/label face and it lands everywhere
  for free. `fontFamily.sans` is likewise overridden (not merely aliased) so
  unclassed elements inherit Libre Franklin.
- **Font payload roughly triples** — eight new woff2 files (~136 KB total)
  alongside the four retained DM files. MYS-240 was explicitly a font
  performance ticket, so this is a deliberate, recorded regression that the
  sweep partially recovers by deleting the four DM files.
- **ADR 0004 now names a color that no longer exists.** It specifies rust
  `#AD4F39` for form-field errors. Its *category* rule is unchanged and still
  binding; only the color moves, to `destructive-text`. ADR 0004 needs an
  amendment note recording the substitution — an ADR whose stated color has
  been deleted is worse than no ADR. Tracked as a follow-up.
- **ADR 0008 is unaffected in substance.** d3-for-math-only, React-owns-the-DOM,
  and the HTML tick-text overlay all carry forward verbatim. Only the palette
  mapping changes, and the old "charts never spend Rust or Gold" line becomes
  "charts use the chart ramp and never borrow `accent` as decoration" — with
  the wrinkle that `chart-1` *is* `accent`, so a single-series chart
  legitimately renders amber. Charts must not be placed on `sheet`.
- **ADR 0007 is unaffected but its component now looks wrong.**
  `GoogleSignInButton` renders Google's *light* button, which will sit on a
  near-black page. Google publishes an official dark variant; switching to it
  is still using Google's own values and does not violate ADR 0007. Tracked as
  an auth-surface ticket.
- **Two carried-forward items are left explicitly unresolved**, recorded so
  they are not silently decided by whoever touches them first: the old guide's
  Ink time-signal chip (deadlines/countdowns) has no analogue in a system where
  everything is already dark, and the `vinyl` avatar color (`#6B7EB5`) has
  never been contrast-checked against a near-black card and now collides
  by name with the DS's VinylDisc component.
- **The About page's deliberate second decorative accent survives.** It was an
  intentional override under the old system and is named in the new guide so no
  reviewer or agent "fixes" it.

## Revisit if

Tailwind v4 becomes necessary for an unrelated reason (a dependency drops v3
support, or a v4-only feature is genuinely needed) — at that point migrate the
build as its own isolated change with no visual delta, rather than assuming
this ADR forbids v4 permanently. Likewise, revisit the no-shadcn call if a
future surface needs genuinely complex interaction primitives (a combobox,
a virtualized listbox, a focus-trapped modal stack) where hand-rolling
accessible behavior costs more than adopting Radix would — the objection here
is to importing unmodified boilerplate as if it were design, not to Radix as an
accessibility primitive library.
