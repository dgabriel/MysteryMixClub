# ADR 0008: Use d3.js for charting, with d3 restricted to math and React owning the DOM

**Status:** Accepted
**Date:** 2026-07-30

## Context

The admin dashboard epic (MysteryMixClub-etz7) needed its first chart: a daily
signup trend line on `/admin/metrics` (MysteryMixClub-etz7.4), sourced from
`GET /admin/metrics/signups`. No charting library existed in the frontend
dependency tree before this issue, and no chart had been built in this app
before — this decision sets the pattern the next chart will follow, not just
this one.

Alternatives considered:
- **A batteries-included React charting library** (Recharts, Victory, Nivo,
  Chart.js + a React wrapper): faster to a first chart, but each one ships its
  own visual defaults (fonts, colors, tooltips, legends, gridlines) that would
  need to be fought or reskinned to fit this app's Sage/DM Mono/"restraint
  over decoration" system, and adds a dependency whose own release cadence and
  bundle weight this project doesn't control.
- **A minimal sparkline-only library** (e.g. a small canvas sparkline
  package): would cover this one chart but is the wrong foundation if the
  admin dashboard epic grows into a second or third chart type later.
- **d3.js directly** — chosen. Explicit, non-negotiable choice made by Dawn
  during scoping, not a Claude Code recommendation weighed against the above;
  recorded here because it's a new third-party frontend dependency and it
  establishes the app's charting convention (both trigger the ADR bar in
  `docs/adr/README.md`).

## Decision

Chart with d3, but only for the math: scales (`scaleUtc`, `scaleLinear`),
domain helpers (`extent`, `max`), and shape generation (`line`, producing an
SVG path string). d3 never calls `.select()`/`.append()` or otherwise touches
the DOM directly, and no DOM node is ever handed to it via a ref — the SVG is
written as JSX and React owns reconciliation of every element, the same as
every other component in the app. This is the standard, low-friction way to
combine d3 with React: d3 for computation, React for rendering.

Visual conventions established for this and future charts (now documented in
`docs/design/style-guide.md` under Components → Charts): a single Sage line,
a single Border baseline, no gridlines/legends/tooltips/area-fills, at most
four tick labels (zero, peak, first period, last period), and the marks
scale with their container via `viewBox` while tick *text* is rendered as a
separately-positioned HTML overlay at a fixed size — SVG text sized in
viewBox units shrinks along with the chart on narrow screens, which drops
tick labels below the style guide's 9px Label floor on a phone-width card.
Charts never spend Rust or Gold; a chart is information, not a signal.

## Consequences

- `d3` (`^7.9.0`) and `@types/d3` (`^7.4.3`) are now frontend dependencies.
  d3 is modular (the installed tree pulls in `d3-scale`, `d3-shape`,
  `d3-array`, `d3-time`, etc. as transitive packages), so the actual bundle
  cost is closer to "the handful of submodules imported" than "all of d3" —
  but it is still meaningfully more surface area than a single-purpose
  sparkline package would have been.
- Every future chart in this app should follow the same d3-for-math /
  React-for-DOM split and the visual conventions above, rather than
  introducing a second charting approach. A reviewer should treat a new
  chart that calls into d3's DOM-manipulation API, or that reaches for a
  different charting library, as a regression against this decision.
- The fixed-size HTML tick overlay is one extra layer of positioning math
  (percentage conversions kept in sync with the SVG's own viewBox/margin
  constants) compared to putting text directly in the SVG. This is the right
  tradeoff for a mobile-responsive app, but it does mean every future chart
  needs the same two-layer treatment, not just an SVG.

## Revisit if

The admin dashboard (or any other part of the app) needs a chart type d3's
low-level primitives make meaningfully harder than a higher-level library
would (e.g. interactive tooltips, zoom/pan, a real-time streaming chart) —
at that point, weigh a purpose-built library against continuing to hand-roll
it in d3, rather than assuming this ADR's choice must extend indefinitely.
