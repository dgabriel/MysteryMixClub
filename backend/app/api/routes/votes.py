"""Voting endpoints (MYS-20).

Casting and reading a player's votes for a mix:

* ``POST /api/v1/mixes/:id/votes``      — cast (replace) your votes for the mix
* ``GET  /api/v1/mixes/:id/votes/mine`` — your current votes for the mix
* ``GET  /api/v1/mixes/:id/vote-counts`` — vote counts per song (no notes yet)

Voting is open only while the mix is in ``open_voting``. Any active club
member may vote whether or not they submitted a song (MYS-167) — but a vibing
member sits voting out and leaves a note instead. The caller's vibing stance is
their submission's ``participation_mode`` if they submitted, else their club
membership's ``vibe_mode``. A player cannot vote for their own song. Every other
song is votable, including vibing submissions — vibing is private (the voter
can't tell which songs are vibers'), and a viber's song competes like any other
(MYS-112). Casting replaces the caller's prior votes for the mix wholesale
(delete-then-insert), so a re-cast is idempotent — mirroring the submission
replace-in-place pattern.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.wire import WireModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import _load_club_as_member
from app.api.routes.mixes import _load_mix, advance_mix_state, voting_quorum_met
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import gather_recipients, queue_mix_event

router = APIRouter(tags=["votes"])


class VotesCast(WireModel):
    submission_ids: list[uuid.UUID]


class VotesResponse(WireModel):
    round_id: str
    submission_ids: list[str]
    count: int
    votes_per_player: int


@router.post("/mixes/{round_id}/votes", response_model=VotesResponse)
async def cast_votes(
    round_id: uuid.UUID,
    payload: VotesCast,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> VotesResponse:
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    if mix_.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="voting is not open for this mystery mix"
        )

    # Decision (MYS-167): any active member may vote, whether or not they
    # submitted a song — only vibing members sit voting out. Stance resolves from
    # the caller's own submission if they have one (a player may hold several songs
    # now — MYS-116 — but their stance is uniform, so any one answers it), else
    # from their club membership's vibe_mode. Vibing -> 409, leave a note instead.
    own_submission = await db.scalar(
        select(Submission)
        .where(Submission.mix_id == round_id, Submission.user_id == current_user.id)
        .limit(1)
    )
    if own_submission is not None:
        is_vibing = own_submission.participation_mode == "vibing"
    else:
        membership = await db.scalar(
            select(ClubMember).where(
                ClubMember.club_id == mix_.club_id,
                ClubMember.user_id == current_user.id,
                ClubMember.removed_at.is_(None),
            )
        )
        # _load_club_as_member above already proved an active membership exists.
        is_vibing = membership is not None and membership.vibe_mode
    if is_vibing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="casual mode players don't cast votes (leave a note instead)",
        )

    target_ids = payload.submission_ids
    if len(target_ids) < 1 or len(target_ids) > mix_.votes_per_player:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"you may cast up to {mix_.votes_per_player} votes",
        )
    if len(set(target_ids)) != len(target_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="duplicate votes are not allowed"
        )

    # Resolve targets in one query; every id must belong to this mix.
    targets = list(
        await db.scalars(
            select(Submission).where(Submission.mix_id == round_id, Submission.id.in_(target_ids))
        )
    )
    targets_by_id = {s.id: s for s in targets}
    for sid in target_ids:
        target = targets_by_id.get(sid)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="submission not found in this mystery mix",
            )
        if target.user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="you can't vote for your own song"
            )
        # Vibing songs are votable (MYS-112): a viber's song competes like any
        # other, and the voter can't tell which songs are vibers'.

    # Lock the mix row before mutating votes (MYS-168): a concurrent organizer
    # rollback, deadline force-advance, or manual close could otherwise land
    # between the open_voting check above and the vote writes below, leaving a
    # stray vote attached to a mix that's no longer accepting them. Re-verify
    # state under the lock, then hold it through the rest of this request — the
    # same lock also serializes the auto-advance quorum check further down, so
    # there is only one lock acquisition for the whole endpoint.
    locked = await db.scalar(
        select(Mix)
        .where(Mix.id == mix_.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="voting is not open for this mystery mix"
        )

    # Replace the caller's votes for this mix wholesale.
    existing = list(
        await db.scalars(
            select(Vote).where(Vote.mix_id == round_id, Vote.voter_id == current_user.id)
        )
    )
    for vote in existing:
        await db.delete(vote)
    # Flush the deletes before inserting so the UNIQUE(voter_id, submission_id)
    # backstop never trips on a re-cast of an overlapping submission set.
    await db.flush()
    for sid in target_ids:
        db.add(Vote(mix_id=round_id, voter_id=current_user.id, submission_id=sid))
    # Flush the inserts so the just-cast votes count toward the voting quorum.
    await db.flush()

    # Auto-advance (MYS-69): once every playing submitter has voted, the mix
    # closes itself — auto-opening the next mix or completing the club. The
    # mix has been locked since before the vote mutation above, so two
    # concurrent final votes still serialize correctly: whichever request's
    # quorum check runs second sees the other's now-committed vote plus its own
    # just-flushed one, and is the one that closes the mix.
    if mix_.state == "open_voting" and await voting_quorum_met(mix_, db):
        club = await db.scalar(select(Club).where(Club.id == mix_.club_id))
        if club is not None:
            events = await advance_mix_state(mix_, club, "closed", db)
            recipients = await gather_recipients(db, mix_.club_id)
            for event_mix, event in events:
                queue_mix_event(
                    background_tasks, sender, settings, recipients, club, event_mix, event
                )

    await db.commit()

    return VotesResponse(
        round_id=str(round_id),
        submission_ids=[str(sid) for sid in target_ids],
        count=len(target_ids),
        votes_per_player=mix_.votes_per_player,
    )


@router.get("/mixes/{round_id}/votes/mine", response_model=VotesResponse)
async def get_my_votes(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VotesResponse:
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    votes = list(
        await db.scalars(
            select(Vote)
            .where(Vote.mix_id == round_id, Vote.voter_id == current_user.id)
            .order_by(Vote.created_at.asc())
        )
    )
    return VotesResponse(
        round_id=str(round_id),
        submission_ids=[str(v.submission_id) for v in votes],
        count=len(votes),
        votes_per_player=mix_.votes_per_player,
    )


class VoteCountEntry(WireModel):
    submission_id: str
    title: str
    artist: str
    vote_count: int


class VoteCountsResponse(WireModel):
    round_id: str
    entries: list[VoteCountEntry]


@router.get("/mixes/{round_id}/vote-counts", response_model=VoteCountsResponse)
async def get_vote_counts(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VoteCountsResponse:
    """Vote counts per song for the mix (no notes yet — notes revealed only at close).

    Available while the mix is in ``open_voting``. Shows how many votes each song
    has received so far, without revealing any notes or the submitter identity.
    This is the "running tally" that players see after they've cast their votes.
    """
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    if mix_.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="vote counts are available while voting is open",
        )

    # Get all submissions in this mix with their vote counts.
    # The vote count is 0 for songs with no votes.
    submission_rows = (
        await db.execute(
            select(Submission, func.count(Vote.id).label("vote_count"))
            .outerjoin(Vote, Vote.submission_id == Submission.id)
            .where(Submission.mix_id == round_id)
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
