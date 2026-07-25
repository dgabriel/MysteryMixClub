"""Notes endpoints (MYS-21).

Leaving, editing, and reading free-form appreciation notes on a submission:

* ``POST  /api/v1/submissions/:id/notes`` — leave a note on a submission
* ``PATCH /api/v1/submissions/:id/notes`` — edit the caller's own note
* ``GET   /api/v1/submissions/:id/notes`` — read the notes on a submission

Notes may be left or edited while the mix is in ``open_voting`` — this covers
editing right up until the mix closes, including after the editing player has
cast their own votes (MYS-257 follow-up: votes are per-player and don't close
the mix for anyone else) — or, once the mix is ``closed``, if the author was
vibing (participation_mode == "vibing" on their own submission in this mix,
same definition ``GET /mixes/:id/results`` uses for ``viewer_is_vibing``).
There's no real competition left to protect once a casual/vibing player's
mystery mix is revealed, so their conversation about it can keep going; a
non-vibing (playing) author still can't touch notes after close (MYS-256
follow-up). Reading is gated by mix state: while voting is open a member sees
only their own notes (others' stay hidden so notes can't sway votes, MYS-67);
the full set is revealed once the mix is closed, with no further restriction
on GET.
Self-notes are allowed, and every submission is eligible regardless of its
``participation_mode`` (playing or vibing) — a vibing player who can't vote
leaves notes instead. Each author may leave at most one note per submission
(MYS-257) — a second POST is rejected with 409; PATCH is how they revise it
instead. The 280-char limit is enforced here (Pydantic), mirroring how
``submissions.note`` is handled.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import StringConstraints

from app.api.wire import WireModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import _load_club_as_member
from app.api.routes.mixes import _load_mix
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User

router = APIRouter(tags=["notes"])

NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=280)]


class NoteCreate(WireModel):
    body: NoteBody


class NoteUpdate(WireModel):
    body: NoteBody


class NoteResponse(WireModel):
    id: str
    submission_id: str
    round_id: str
    author_id: str
    author_display_name: str
    body: str
    created_at: datetime


def _to_response(note: Note, author_display_name: str) -> NoteResponse:
    return NoteResponse(
        id=str(note.id),
        submission_id=str(note.submission_id),
        round_id=str(note.mix_id),
        author_id=str(note.author_id),
        author_display_name=author_display_name,
        body=note.body,
        created_at=note.created_at,
    )


async def _load_submission(submission_id: uuid.UUID, db: AsyncSession) -> Submission:
    submission = await db.scalar(select(Submission).where(Submission.id == submission_id))
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="submission not found")
    return submission


async def _author_was_vibing(mix_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
    """Same definition as ``viewer_is_vibing`` on ``GET /mixes/:id/results``:
    the author's own submission in this mix (if any) was vibing, not playing.
    A non-submitter is treated as not vibing, same as the results endpoint."""
    own_sub = await db.scalar(
        select(Submission).where(Submission.mix_id == mix_id, Submission.user_id == user_id)
    )
    return own_sub is not None and own_sub.participation_mode == "vibing"


async def _notes_open(mix_: Mix, author_id: uuid.UUID, db: AsyncSession) -> bool:
    if mix_.state == "open_voting":
        return True
    return mix_.state == "closed" and await _author_was_vibing(mix_.id, author_id, db)


@router.post("/submissions/{submission_id}/notes", status_code=201, response_model=NoteResponse)
async def leave_note(
    submission_id: uuid.UUID,
    payload: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    submission = await _load_submission(submission_id, db)
    mix_ = await _load_mix(submission.mix_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    if not await _notes_open(mix_, current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notes can be left while voting is open (or after the reveal, in casual mode)",
        )

    existing = await db.scalar(
        select(Note).where(Note.submission_id == submission.id, Note.author_id == current_user.id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you've already left a note on this song",
        )

    note = Note(
        mix_id=submission.mix_id,
        author_id=current_user.id,
        submission_id=submission.id,
        body=payload.body,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _to_response(note, current_user.display_name)


@router.patch("/submissions/{submission_id}/notes", response_model=NoteResponse)
async def edit_note(
    submission_id: uuid.UUID,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    submission = await _load_submission(submission_id, db)
    mix_ = await _load_mix(submission.mix_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    if not await _notes_open(mix_, current_user.id, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="notes can be edited while voting is open (or after the reveal, in casual mode)",
        )

    note = await db.scalar(
        select(Note).where(Note.submission_id == submission.id, Note.author_id == current_user.id)
    )
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="note not found")

    note.body = payload.body
    await db.commit()
    await db.refresh(note)
    return _to_response(note, current_user.display_name)


@router.get("/submissions/{submission_id}/notes", response_model=list[NoteResponse])
async def list_notes(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NoteResponse]:
    submission = await _load_submission(submission_id, db)
    mix_ = await _load_mix(submission.mix_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    stmt = (
        select(Note, User.display_name)
        .join(User, User.id == Note.author_id)
        .where(Note.submission_id == submission_id)
        .order_by(Note.created_at.asc())
    )
    # Until the mix closes, a member sees only their own notes — everyone
    # else's stay hidden during voting so notes can't sway votes (MYS-67). The
    # full set is revealed once the mix is closed (the reveal).
    if mix_.state != "closed":
        stmt = stmt.where(Note.author_id == current_user.id)

    rows = await db.execute(stmt)
    return [_to_response(note, display_name) for note, display_name in rows.all()]
