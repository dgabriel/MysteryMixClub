# ADR 0027: Reveal who hasn't submitted/voted, but only past 50%

**Status:** Accepted
**Date:** 2026-09-11

## Context

`MysteryMixClub-xfq5`. Dawn's ask: "show who has not submitted or voted in a
round if more than half the club members have submitted or voted." A peer
nudge for stragglers, deliberately gated — not a running tally visible from
zero, which would just broadcast low early engagement instead of building
momentum toward it.

This overlaps with existing quorum machinery in `mixes.py`
(`submission_quorum_met`/`voting_quorum_met`, MYS-69/MYS-158), which already
defines exactly the two "who's expected to act" sets this feature needs:

- **Submission**: quorum uses club members active *at the moment submissions
  opened* (`joined_at <= submission_opened_at`, `removed_at IS NULL`). The
  existing "X of Y submitted" display (`_member_count`/`_submission_count`)
  instead uses *currently* active members — a different, looser snapshot.
- **Voting**: quorum uses distinct submitters whose `participation_mode ==
  "playing"` — vibing submitters can't vote and were never expected to.
  `voting_eligible_count`/`voted_count` already matches this exactly.

## Decisions

- **Denominator matches the existing on-screen "X of Y" counts**, not
  `submission_quorum_met`'s stricter active-at-open snapshot. A member seeing
  "3 of 4 submitted" and then a missing-list that silently excludes someone
  because they joined after submissions opened would read as a bug, even
  though it's consistent with the (separate, invisible-to-users) auto-advance
  gate. Consistency with what's already displayed on this exact screen wins.
- **Reveal threshold is strictly "more than half"** (`count > total / 2`), not
  "at least half" — an exact 50% split stays hidden. Matches Dawn's literal
  wording and avoids the awkward case of a 2-person club revealing at 1-of-2.
- **Gated by mix state**: `missing_submitters` only populates during
  `open_submission`, `missing_voters` only during `open_voting`. Once a phase
  closes, the nudge is no longer actionable — showing "you never voted" after
  the fact isn't this feature's job.
- **Visible to every club member, not just organizers** (Dawn's call,
  2026-09-11) — a peer nudge, not an admin tool. No new authorization check
  needed: `get_mix` already gates on club membership.
- **Voting's eligible set excludes vibing submitters**, mirroring
  `voting_quorum_met` exactly — a vibing member is never "missing" a vote
  they were never expected to cast.
- **Computed only on the single-mix GET** (`GET /mixes/:id`), not the
  club's mix-list endpoint. A list of mixes would pay a join per row for
  data the club-home tile has no room to display anyway (member names, not
  just a count); `member_count`/`submission_count` stay list-friendly counts.

## Consequences

- New `MissingMemberSummary` wire type (`user_id`, `display_name` — same
  privacy-safe shape as `clubs.py`'s `MemberResponse`, no email) and two new
  nullable `MixResponse` fields.
- Two new query helpers, `_missing_submitters`/`_missing_voters`, deliberately
  *not* unified with `submission_quorum_met`/`voting_quorum_met` despite the
  conceptual overlap — the denominators genuinely differ (display snapshot vs.
  quorum's active-at-open snapshot), so sharing code would mean threading a
  flag through the quorum functions' existing, already-carefully-reasoned
  logic for a display-only feature. Two small, independent functions were
  the smaller change.
- Frontend: a single `MissingMembers` component reused at all three progress-
  readout call sites in `MixDetailRoute.tsx` (submission progress, and both
  voting-progress renders — vibing-viewer and regular-viewer branches), same
  quiet-mono/never-accent treatment as the existing progress line it sits
  under.

## Revisit if

- Members ask for this same nudge to also show once a mix has *closed*
  (retrospective "who never showed up this round") — currently deliberately
  scoped to the live phase only.
- The denominator choice (display snapshot vs. quorum's stricter snapshot)
  turns out to confuse organizers reconciling this list against auto-advance
  behavior — would need to either unify them or document the difference
  more visibly than this ADR.
