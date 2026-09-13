---
name: mmc-design-system
description: MysteryMixClub (MMC) design system reference — palette, typography, motifs, and component conventions. Use whenever reviewing, critiquing, or designing UI for the MysteryMixClub app so recommendations work within the existing system rather than against it.
---

# MysteryMixClub Design System

MMC's visual identity is inspired by Marcel Duchamp's Rotorelief series — concentric, hypnotic, deliberately unconventional. The system favors restraint and precision over decoration. Every recommendation should protect this restraint: the most common failure mode for outside critique is suggesting "modern" patterns (gradients, drop shadows, card-heavy layouts, decorative color) that are generic elsewhere but wrong here.

## Palette

Four named tokens: **Cream**, **Sage**, **Rust**, **Ink**.

- **Rust (`#AD4F39`)** is a signal color, not a decorative one. It appears **exactly once per screen** — reserved for the single most important element (e.g. one CTA, one active state indicator). If a screen has zero or multiple Rust elements, that's a design system violation worth flagging.
- Cream, Sage, and Ink handle background, surface, and text/ink roles respectively — treat them as the neutral palette that Rust punctuates.
- **Always reference and use the named Tailwind tokens** (e.g. `bg-cream`, `text-ink`, `border-sage`) — never raw hex values or arbitrary Tailwind color utilities (`bg-[#...]`, `text-orange-600`, etc.). If exact hex values for Cream/Sage/Ink are needed, pull them from the project's `tailwind.config` rather than guessing.

## Typography

- **DM Serif Display** — headings, display type, moments that carry the Rotorelief personality.
- **DM Mono** — body copy, UI labels, data, anything functional or systematic.
- The pairing itself does hierarchy work: serif display type signals "moment," mono signals "system." Don't introduce a third typeface or lean on size/weight alone to create hierarchy when this pairing already exists for that purpose.

## Motifs & Component Conventions

- **Concentric ring motif** — recurring visual element echoing the Rotorelief inspiration (rings, radial patterns). Look for opportunities to reinforce it in loading states, decorative accents, or empty states rather than introducing unrelated iconography or illustration styles.
- **Underline-style inputs** — form fields use underline treatment, not boxed/bordered inputs. Flag any boxed input fields as inconsistent with the system.
- No card-heavy layouts with heavy drop shadows — the system reads as flat, precise, and graphic rather than skeuomorphic or elevated.

## Stack Context

React/TypeScript PWA frontend, FastAPI backend, staging at `staging.mysterymixclub.com`. Mobile strategy is Capacitor/Expo (tracked as MYS-165) — when reviewing responsive/mobile behavior, keep touch target and platform-native conventions in mind since this may ship as a wrapped native app, not just a responsive web view.

## How to Apply This

When critiquing MMC screens, run the standard UI/UX analysis framework, but treat violations of the above (off-palette color use, wrong typeface pairing, boxed inputs, missing/duplicated Rust signal, card+shadow patterns) as **design-system consistency** findings — a distinct category from generic usability findings, since fixing them is about system adherence, not necessarily improving the UX in isolation. Don't suggest changes to the core system itself (palette, typeface pairing, motif) unless explicitly asked — treat it as a fixed constraint to design within.
