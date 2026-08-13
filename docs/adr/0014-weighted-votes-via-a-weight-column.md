# 14. Weighted votes via a weight column, not duplicate rows

Date: 2026-08-13

## Status

Accepted. Reverses the vote-uniqueness half of technical-design section 6.

## Context

Voting has always meant "pick up to N different songs." That rule was enforced
at three layers, deliberately and consistently:

- **DB** — `UNIQUE(voter_id, submission_id)` on `votes`, commented in
  `app/models/vote.py` as "a voter may vote for a given submission at most once."
- **API** — `cast_votes` returns 409 `duplicate votes are not allowed` when
  `submission_ids` contains a repeat.
- **Spec** — `docs/technical/technical-design.md` section 6 lists the constraint
  in the `votes` table definition.

Dawn asked for the opposite on 2026-08-11: a player should be able to put more
than one of their votes on a single song, up to the whole allowance. The point
is expressiveness. Under the old rule a player with three votes and one song
they truly love has no way to say so; they have to spend two votes on songs they
are lukewarm about, which flattens the signal the game exists to capture.

That reverses a documented decision, so it gets a record.

The question this ADR settles is not *whether* to allow it — that is Dawn's
product call — but **how to represent it**, because production is live and
carries real votes.

## Decision

**Add a `weight` integer column to `votes`, and keep
`UNIQUE(voter_id, submission_id)`.**

One row per (voter, submission) pair, as before. A player who spends three votes
on one song produces one row with `weight = 3`, not three rows. Weight is
`NOT NULL DEFAULT 1`, `CHECK (weight >= 1)`.

The wire format does not change shape. `submission_ids` stays a flat list of
ids, and **repeats in that list are now meaningful**: `[A, A, A, B]` means three
votes on A and one on B. The server collapses the list into weights on write and
expands it back into repeats on read, so `POST` and `GET /votes/mine` still
round-trip exactly. `count` remains the total number of votes cast.

Validation changes from "N distinct ids" to "the list is 1..N long", which is
the same bound with the distinctness check deleted.

Every aggregate that meant `COUNT(votes)` now means
`COALESCE(SUM(votes.weight), 0)`: the running tally, the per-mix results, the
club leaderboard, and the admin stats. Aggregates over *voters* rather than
votes — the voting quorum, "X of Y voted", the distinct-voter counts — are
untouched, because who has voted is a separate question from how hard they
voted.

## Alternatives considered

**Drop the unique constraint and insert duplicate rows.** The obvious reading of
"vote more than once," and it needs no new column: three votes on a song is
three rows. Rejected on reversibility. Dropping a unique constraint is trivial;
putting it back is not, because by then the table holds duplicate rows that
violate it, and re-adding it means deciding what to do with live production data
under a lock. The weight column is additive in both directions — every existing
row is a valid weighted vote at `weight = 1`, the migration backfills nothing,
and the down migration is a `DROP COLUMN` that loses only the stacking. Given
the permanent no-breaking-changes rule for prod, the reversible option wins even
though it is slightly more code.

It is also cheaper at read time. Vote counts are read on every results page and
every leaderboard; `SUM` over one row per voter beats `COUNT` over a table that
grows with the allowance.

**A new wire shape, `votes: [{submission_id, weight}]`.** More explicit than
repeats in a list, and self-documenting in a way `[A, A, A, B]` is not.
Rejected because it breaks the contract in both directions at once: an old
client's `submission_ids` stops being understood, and a new client's payload
means nothing to an un-deployed server. The repeated-list form is backward
compatible by construction — a client that never repeats an id behaves exactly
as it does today, which also means the existing frontend keeps working
unmodified while the new voting UI is built.

**Capping how many votes may land on one song** (at N-1, or at half the
allowance) to stop a player dumping everything on one track. Rejected: Dawn's
framing was "up to as many votes as they have," and a cap is a rule players
would have to be taught for a problem nobody has reported. Easy to add later if
dumping turns out to hurt the game; hard to remove once players expect it.

## Consequences

- `vote_count` keeps its name everywhere but changes meaning, from "how many
  people voted for this" to "how many votes this got." Anything that inferred
  voter headcount from it is now wrong. The one caller that did — the frontend's
  `topVoteWinners()` tie detection — still works, because it compares totals for
  equality and does not care what the totals count.
- The results reveal shows a multiplier: `Dawn ×3`, with the suffix rendered
  only when weight is above 1. `ResultVoter` gains a `weight` field. Repeating
  the name three times was considered and rejected as looking like a bug.
- The vote-selection affordance shipped in the redesign assumes a binary
  selected/unselected marker. It becomes a quantity stepper, so that work is
  revisited rather than extended — anticipated when it shipped.
- The GDPR export gains weight per vote, since a weighted vote is a different
  fact about a person than an unweighted one.
- Voting stays anonymous until close. Weight is revealed with the voter's name
  at the same moment the name is, and never before.
