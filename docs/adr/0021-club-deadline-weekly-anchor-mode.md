# ADR 0021: Club deadlines can be anchored to a fixed weekday/time, alongside the existing duration window

**Status:** Accepted
**Date:** 2026-09-09

## Context

Every club's mix deadlines are currently computed as a fixed duration
(`clubs.submission_window_hours` / `voting_window_hours`, 4-168h, default
72h) counted from whenever that phase happens to open — the deadline
"floats" with whatever time the previous phase closed. Dawn's own club has
found this makes deadlines feel arbitrary and easy to miss; their group gets
noticeably more engagement on a fixed weekly cadence (songs due Tuesday
12:00, votes due Saturday 12:00) than on a rolling N-hour window.

Two shapes were on the table:

1. **Replace** the duration window entirely with a weekday+time anchor.
2. **Add** an opt-in alternate mode, leaving duration-based clubs untouched.

Replacing outright would force every existing club (and every club that
genuinely wants a flexible rolling window — e.g. one whose members are
scattered across time zones with no shared "always free" slot) into the
anchored model with no fallback. There's also no timezone concept anywhere
in the schema today (`DateTime(timezone=True)` columns are UTC-aware
storage, not an IANA zone), so "noon" needs a zone to mean anything, and
that's new surface area regardless of which shape is chosen.

A related question was whether submission and voting could independently
choose duration vs. anchor. Splitting them independently doubles the
settings surface and the edge cases (mixed-mode stamping, mixed-mode
validation) for a benefit that wasn't requested — Dawn's ask was a single
weekly rhythm covering both phases.

## Decision

Add a per-club `deadline_mode` (`"duration"` | `"weekly_anchor"`), default
`"duration"`, governing **both** submission and voting phases together — no
per-phase mixing. `"duration"` is byte-for-byte the existing behavior.
`"weekly_anchor"` adds `timezone` (IANA name, e.g. `America/New_York`) plus
a weekday+time pair for each phase, and computes each deadline as the next
occurrence of that weekday/time in that zone, with a 24-hour minimum-lead
guard (if the raw next occurrence is under 24h away, it rolls to the
following week) so a phase that happens to open right before its anchor
time never gets a near-zero window.

All five call sites that currently do
`datetime.now(timezone.utc) + timedelta(hours=club.X_window_hours)`
(`advance_mix_state`'s three stamps, `rollback_mix_to_submission`, and
`advance_mixes.py`'s Branch 1) go through one new helper,
`compute_phase_deadline()`, instead of each re-deriving the logic inline.

Timezone math uses Python 3.11's stdlib `zoneinfo`, with `tzdata` added as
an explicit backend dependency so zone data doesn't depend on the host OS
having it installed — relevant for minimal container images, and cheap
insurance regardless.

## Consequences

- Fully additive and backward compatible: every existing club keeps its
  current duration-window behavior with zero migration action required.
- New settings-UI surface: a mode toggle plus, in weekly-anchor mode, a
  timezone picker and two weekday+time pickers, on both club creation and
  the organizer's inline club-settings edit.
- New dependency: `tzdata` (stdlib `zoneinfo`'s IANA data source).
- DST correctness relies on `zoneinfo`'s default fold resolution for the
  ambiguous/skipped hour at a transition boundary; this is not exhaustively
  hardened beyond stdlib's own behavior — a real edge case (an anchor time
  that lands exactly in a skipped or repeated hour) is handled however
  `zoneinfo` resolves it by default, not with bespoke fold-disambiguation
  logic. Covered by a DST-boundary unit test, not a formal spec.
- The five deadline-stamping call sites now share one code path instead of
  five near-duplicated inline blocks — a readability improvement that falls
  out of this change, not its primary motivation.
- Deadline **display** (`formatDeadline`) needs no change: it already
  renders a viewer's local time from an absolute stored timestamp, which
  stays correct regardless of which mode produced that timestamp.

## Revisit if

- A club wants submission and voting on different modes (e.g. one anchored,
  one rolling) — this decision deliberately doesn't support that; revisit if
  real demand shows up rather than speculatively building it now.
- A club wants more than one anchor slot per phase (e.g. two acceptable
  submission windows) — out of scope here, genuinely different shape.
- Push notifications or calendar (.ics) export land later and want to read
  the weekly-anchor configuration directly (e.g. to schedule a reminder
  ahead of the anchor time) — this ADR's fields are the natural source for
  that, but wiring it up is separate work.
