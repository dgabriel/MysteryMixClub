# ADR 0035: Blocking is one-directional, quiet, per-viewer read filtering

**Status:** Accepted
**Date:** 2026-09-23

## Context

App Store Guideline 1.2 requires a way for a member to "block abusive users"
(`MysteryMixClub-4vii.42`, a blocker of the 4vii.46 release gate). The
question was not *whether* to build it but *what a block should do* in an app
whose social fabric is small, invite-only clubs with shared, persistent
records (mixes, submissions, votes).

Alternatives considered:

- **Two-way removal from each other's club experience.** Heavy machinery for
  an app where clubs are invite-only and organizers already have "remove
  member"; it would also mutate shared history in ways other members can see.
- **Report-only moderation.** Guideline 1.2 explicitly wants the *user*
  empowered, not just the operator — a report alone doesn't stop the reporter
  from seeing the content they flagged while review is pending.
- **Client-side hiding.** Cheaper, but the data still lands on the blocker's
  device, and any new client (or API shape) could forget to filter — the
  filter has to live where the response is built.

## Decision

A block is a **one-directional privacy preference of the blocker**,
enforced **server-side at read time**, on the blocker's views only:

- Row shape: `blocks (blocker_id, blocked_id, created_at)`, composite PK of
  the pair. Blocking is idempotent (re-POST returns the standing block),
  unrestricted by state (you may block a member who already left or was
  removed — they can still have notes in your history), and rejected only for
  self-blocks (400) or users who never shared a club with you (neutral 404,
  so the endpoint doesn't confirm whether an account exists).
- **Effect:** everywhere the blocker can *read* another member's text, the
  blocked member's notes are filtered out of the response: note lists on
  closed mixes, `submitter_note` on playlist and reveal entries, the note
  rows inside results and submission history, and — since Most Noted is an
  aggregate of notes — the Most Noted computation reruns per viewer with
  blocked authors excluded. Blocked members are also omitted from `voters[]`.
- **Deliberately NOT filtered:** vote aggregates (`vote_count`), submitter
  display names, leaderboard rows, and song rows themselves. These are the
  club's shared record; a block is private and one member's preference must
  not silently rewrite what the record says happened. A bare display name
  carries no content channel; name abuse is handled by the content filter
  (4vii.43) + reporting instead.
- **Quiet by design:** the blocked member is never notified and their own
  experience is byte-for-byte unchanged. No push, no email, no UI signal.
  Confrontation dynamics in tiny clubs argued for this over any "you've been
  blocked" affordance.
- **Unblock is a plain DELETE**, instantly reversible; the UI offers no
  armed-confirm either direction.
- Deletion cascades with either user (`ON DELETE CASCADE` both sides):
  interpersonal state has no orphan meaning, unlike `reports` whose audit
  value survives account deletion via `SET NULL`.

## Consequences

- Every read path that serves one user's view of another's text has to know
  about blocks: `notes.py`, `mixes.py` (playlist, results, reveal),
  `users.py` (submission history), `most_noted.py` (new
  `exclude_author_ids` parameter), `clubs.py` (the `blocked_by_me` viewer
  flag on member rows). A future read endpoint that exposes member text and
  skips this filter is a bug class the tests in `test_blocks.py` are meant
  to make loud.
- `compute_most_noted` now takes an exclusion set, so its results are
  per-viewer — any future caching of Most Noted must key on the viewer's
  block set or it will leak.
- The club-members response carries `blocked_by_me`, shaped `bool | None`
  (None = "not computed", mirroring the `viewer_is_admin` precedent on
  role-change responses) so older/partial responses stay parseable.
- `purge_accounts` deletes block rows explicitly (house style: explicit
  FK-safe deletes, not reliance on the cascade) so hard-delete behavior is
  greppable from one place.

## Revisit if

- Blocking needs to become mutual (e.g. reports show harassment continuing
  through channels this doesn't cover — at that point the answer is probably
  organizer removal, not a fancier block).
- Clubs grow large/open enough that vote-count or name exposure matters to
  block targets; the current "shared record stays intact" stance assumed
  small invite-only clubs.
- Any surface is added where a member's *actions* (not just text) reach
  another member and need gating.
