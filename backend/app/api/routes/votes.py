"""Voting endpoints (MYS-20).

Casting and reading a player's votes for a round:

* ``POST /api/v1/rounds/:id/votes``      — cast (replace) your votes for the round
* ``GET  /api/v1/rounds/:id/votes/mine`` — your current votes for the round
* ``GET  /api/v1/rounds/:id/vote-counts`` — vote counts per song (no notes yet)

Voting is open only while the round is in ``open_voting``. Only a Playing
participant may vote: the caller must have a submission in the round, and a
``vibing`` submitter cannot vote — they leave a note instead (MYS-21). A player
cannot vote for their own song. Every other song is votable, including vibing
submissions — vibing is private (the voter can't tell which songs are vibers'),
and a viber's song competes like any other (MYS-112). Casting replaces the
caller's prior votes for the round wholesale (delete-then-insert), so a re-cast
is idempotent — mirroring the submission replace-in-place pattern.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member
from app.api.routes.rounds import _load_round, advance_round_state, voting_quorum_met
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.league import League
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import gather_recipients, queue_round_event

router = APIRouter(tags=["votes"])


class VotesCast(BaseModel):
    submission_ids: list[uuid.UUID]


class VotesResponse(BaseModel):
    round_id: str
    submission_ids: list[str]
    count: int
    votes_per_player: int


@router.post("/rounds/{round_id}/votes", response_model=VotesResponse)
async def cast_votes(
    round_id: uuid.UUID,
    payload: VotesCast,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> VotesResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)

    if round_.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="voting is not open for this round"
        )

    # Decision (MYS-20): only players who are themselves Playing may vote. A
    # member with no submission for the round cannot vote, and a member whose
    # own submission is `vibing` cannot vote — they leave a note instead. A
    # player may have several songs now (MYS-116) but their stance is uniform,
    # so any one of their submissions answers both questions.
    own_submission = await db.scalar(
        select(Submission)
        .where(Submission.round_id == round_id, Submission.user_id == current_user.id)
        .limit(1)
    )
    if own_submission is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="submit a song before voting"
        )
    if own_submission.participation_mode == "vibing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="just vibing players don't cast votes — leave a note instead",
        )

    target_ids = payload.submission_ids
    if len(target_ids) < 1 or len(target_ids) > round_.votes_per_player:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"you may cast up to {round_.votes_per_player} votes",
        )
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="duplicate votes are not allowed"
        )

    # Resolve targets in one query; every id must belong to this round.
    targets = list(
        await db.scalars(
            select(Submission).where(Submission.round_id == round_id, Submission.id.in_(target_ids))
        )
    )
    targets_by_id = {s.id: s for s in targets}
    for sid in target_ids:
        target = targets_by_id.get(sid)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="submission not found in this round"
            )
        if target.user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="you can't vote for your own song"
            )
        # Vibing songs are votable (MYS-112): a viber's song competes like any
        # other, and the voter can't tell which songs are vibers'.

    # All validation passed: replace the caller's votes for this round wholesale.
    existing = list(
        await db.scalars(
            select(Vote).where(Vote.round_id == round_id, Vote.voter_id == current_user.id)
        )
    )
    for vote in existing:
        await db.delete(vote)
    # Flush the deletes before inserting so the UNIQUE(voter_id, submission_id)
    # backstop never trips on a re-cast of an overlapping submission set.
    await db.flush()
    for sid in target_ids:
        db.add(Vote(round_id=round_id, voter_id=current_user.id, submission_id=sid))
    # Flush the inserts so the just-cast votes count toward the voting quorum.
    await db.flush()

    # Auto-advance (MYS-69): once every playing submitter has voted, the round
    # closes itself — auto-opening the next round or completing the league. Lock
    # the round row FIRST, then evaluate the quorum UNDER the lock. Two concurrent
    # final votes each only see their own uncommitted votes before locking (READ
    # COMMITTED hides the other's), so checking before the lock would have both see
    # N-1 and neither advance — the round would stall. Serialized on the lock, the
    # last committer re-reads the now-committed votes and closes the round.
    if round_.state == "open_voting":
        locked = await db.scalar(
            select(Round)
            .where(Round.id == round_.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            locked is not None
            and locked.state == "open_voting"
            and await voting_quorum_met(round_, db)
        ):
            league = await db.scalar(select(League).where(League.id == round_.league_id))
            if league is not None:
                events = await advance_round_state(round_, league, "closed", db)
                recipients = await gather_recipients(db, round_.league_id)
                for event_round, event in events:
                    queue_round_event(
                        background_tasks, sender, settings, recipients, league, event_round, event
                    )

    await db.commit()

    return VotesResponse(
        round_id=str(round_id),
        submission_ids=[str(sid) for sid in target_ids],
        count=len(target_ids),
        votes_per_player=round_.votes_per_player,
    )


@router.get("/rounds/{round_id}/votes/mine", response_model=VotesResponse)
async def get_my_votes(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VotesResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)

    votes = list(
        await db.scalars(
            select(Vote)
            .where(Vote.round_id == round_id, Vote.voter_id == current_user.id)
            .order_by(Vote.created_at.asc())
        )
    )
    return VotesResponse(
        round_id=str(round_id),
        submission_ids=[str(v.submission_id) for v in votes],
        count=len(votes),
        votes_per_player=round_.votes_per_player,
    )


class VoteCountEntry(BaseModel):
    submission_id: str
    title: str
    artist: str
    vote_count: int


class VoteCountsResponse(BaseModel):
    round_id: str
    entries: list[VoteCountEntry]


@router.get("/rounds/{round_id}/vote-counts", response_model=VoteCountsResponse)
async def get_vote_counts(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoteCountsResponse:
    """Vote counts per song for the round (no notes yet — notes revealed only at close).

    Available while the round is in ``open_voting``. Shows how many votes each song
    has received so far, without revealing any notes or the submitter identity.
    This is the "running tally" that players see after they've cast their votes.
    """
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)

    if round_.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="vote counts are available while voting is open",
        )

    # Get all submissions in this round with their vote counts.
    # The vote count is 0 for songs with no votes.
    submission_rows = (
        await db.execute(
            select(Submission, func.count(Vote.id).label("vote_count"))
            .outerjoin(Vote, Vote.submission_id == Submission.id)
            .where(Submission.round_id == round_id)
            .group_by(Submission.id)
            .order_by(Submission.created_at.asc())
        )
    ).all()

    entries = [
        VoteCountEntry(
            submission_id=str(s.id),
            title=s.title,
            artist=s.artist,
            vote_count=vote_count,
        )
        for s, vote_count in submission_rows
    ]

    return VoteCountsResponse(round_id=str(round_id), entries=entries)
