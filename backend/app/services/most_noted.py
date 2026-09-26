"""Most Noted calculation (MYS-21).

Reusable, endpoint-free service that computes a mix's "Most Noted" — the
submission(s) that received the highest raw count of notes. This is a library
function only: it is NOT wired to any route here. MYS-23 will call it from the
mix results endpoint (``GET /mixes/:id/results``).

Semantics (product decisions for MYS-21):
- Notes are counted raw, per submission, across the whole mix.
- Most Noted is the submission(s) at the maximum note count.
- Ties recognize ALL submissions at the max (no tiebreaker) — every winner is
  returned.
- Eligibility is participation-mode-agnostic: playing and vibing submissions
  alike can be Most Noted.
- A mix with zero notes has no Most Noted: ``winners`` is empty and
  ``note_count`` is ``0``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Collection

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User


@dataclass(frozen=True)
class MostNotedNote:
    """A single note on a winning submission, ready for display."""

    # id/author_id (MysteryMixClub-4vii.39): needed to report the note and to
    # hide that action on the viewer's own -- the wire-level ResultNote this
    # feeds carried neither until Guideline 1.2 review found the reveal had
    # no report action at all.
    id: uuid.UUID
    author_id: uuid.UUID
    body: str
    author_display_name: str
    created_at: datetime


@dataclass(frozen=True)
class MostNotedSubmission:
    """A submission tied for the most notes, with its notes attached."""

    submission_id: uuid.UUID
    title: str
    artist: str
    note_count: int
    notes: list[MostNotedNote] = field(default_factory=list)


@dataclass(frozen=True)
class MostNoted:
    """Result of a Most Noted calculation for one mix.

    ``note_count`` is the shared maximum across all winners (``0`` when the
    mix has no notes). ``winners`` holds every submission at that maximum,
    ordered by submission ``created_at`` for a stable presentation.
    """

    mix_id: uuid.UUID
    note_count: int
    winners: list[MostNotedSubmission] = field(default_factory=list)


async def compute_most_noted(
    round_id: uuid.UUID,
    db: AsyncSession,
    *,
    exclude_author_ids: Collection[uuid.UUID] = (),
) -> MostNoted:
    """Compute the Most Noted submission(s) for a mix.

    Returns all submissions tied at the highest note count, each with the notes
    that earned it. An empty ``winners`` list means the mix has no notes.

    ``exclude_author_ids`` drops those authors' notes from both the count and
    the winner selection: Most Noted is per-viewer once a member has blocked
    someone, because the blocker must not see the blocked member's notes
    anywhere (MysteryMixClub-4vii.42, ADR 0035). Callers pass their own empty
    set (the default) when no one is blocked.
    """
    counts_query = (
        select(Note.submission_id, func.count())
        .where(Note.mix_id == round_id)
        .group_by(Note.submission_id)
    )
    if exclude_author_ids:
        counts_query = counts_query.where(Note.author_id.notin_(exclude_author_ids))
    counts = (await db.execute(counts_query)).all()
    if not counts:
        return MostNoted(mix_id=round_id, note_count=0, winners=[])

    max_count = max(count for _, count in counts)
    winning_ids = [submission_id for submission_id, count in counts if count == max_count]

    submissions = {
        s.id: s for s in await db.scalars(select(Submission).where(Submission.id.in_(winning_ids)))
    }

    notes_query = (
        select(Note, User.display_name)
        .join(User, User.id == Note.author_id)
        .where(Note.submission_id.in_(winning_ids))
        .order_by(Note.created_at.asc())
    )
    if exclude_author_ids:
        notes_query = notes_query.where(Note.author_id.notin_(exclude_author_ids))
    note_rows = (await db.execute(notes_query)).all()
    notes_by_submission: dict[uuid.UUID, list[MostNotedNote]] = {sid: [] for sid in winning_ids}
    for note, display_name in note_rows:
        notes_by_submission[note.submission_id].append(
            MostNotedNote(
                id=note.id,
                author_id=note.author_id,
                body=note.body,
                author_display_name=display_name,
                created_at=note.created_at,
            )
        )

    winners = [
        MostNotedSubmission(
            submission_id=submission.id,
            title=submission.title,
            artist=submission.artist,
            note_count=max_count,
            notes=notes_by_submission[submission.id],
        )
        for submission in sorted(submissions.values(), key=lambda s: s.created_at)
    ]
    return MostNoted(mix_id=round_id, note_count=max_count, winners=winners)
