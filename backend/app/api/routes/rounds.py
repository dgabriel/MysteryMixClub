"""Round flow endpoints (MYS-18).

Round lifecycle and the create/read/update surface for a league's rounds:

* ``POST  /api/v1/leagues/:id/rounds`` — organizer creates the next round
* ``GET   /api/v1/leagues/:id/rounds`` — members list a league's rounds
* ``GET   /api/v1/rounds/:id``         — members read a round
* ``PATCH /api/v1/rounds/:id``         — organizer edits fields / advances state
* ``GET   /api/v1/rounds/:id/playlist``— members get the anonymous voting playlist

State machine is forward-only: ``open_submission -> open_voting -> closed``. The
playlist surfaces each submission resolved to the viewer's preferred service (it
reads the stored ``odesli_data``). Membership/organizer checks reuse the helpers
in :mod:`app.api.routes.leagues`.
"""

import random
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member, _load_league_as_organizer
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.most_noted import compute_most_noted

router = APIRouter(tags=["rounds"])

RoundTheme = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

# Forward-only lifecycle: each state's single permitted successor.
_NEXT_STATE = {"open_submission": "open_voting", "open_voting": "closed"}


class RoundCreate(BaseModel):
    theme: RoundTheme
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    # Defaults to the league's votes_per_player when omitted.
    votes_per_player: int | None = Field(default=None, ge=1)


class RoundUpdate(BaseModel):
    # All optional: only provided fields are applied. `state` advances the machine.
    theme: RoundTheme | None = None
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    state: Literal["open_submission", "open_voting", "closed"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null_theme(cls, data):
        # theme maps to a NOT NULL column: allow omission, reject explicit null.
        if isinstance(data, dict) and "theme" in data and data["theme"] is None:
            raise ValueError("theme may not be null")
        return data


class RoundResponse(BaseModel):
    id: str
    league_id: str
    round_number: int
    theme: str
    state: str
    submission_deadline: datetime | None
    voting_deadline: datetime | None
    votes_per_player: int
    created_at: datetime
    closed_at: datetime | None


def _to_response(r: Round) -> RoundResponse:
    return RoundResponse(
        id=str(r.id),
        league_id=str(r.league_id),
        round_number=r.round_number,
        theme=r.theme,
        state=r.state,
        submission_deadline=r.submission_deadline,
        voting_deadline=r.voting_deadline,
        votes_per_player=r.votes_per_player,
        created_at=r.created_at,
        closed_at=r.closed_at,
    )


async def _load_round(round_id: uuid.UUID, db: AsyncSession) -> Round:
    round_ = await db.scalar(select(Round).where(Round.id == round_id))
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="round not found")
    return round_


@router.post("/leagues/{league_id}/rounds", status_code=201, response_model=RoundResponse)
async def create_round(
    league_id: uuid.UUID,
    payload: RoundCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundResponse:
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only the organizer can create rounds"
    )
    if league.state == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="league is complete")

    # Rounds are strictly sequential: the current one must close first.
    open_round = await db.scalar(
        select(Round).where(Round.league_id == league_id, Round.state != "closed").limit(1)
    )
    if open_round is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the current round must be closed before starting a new one",
        )

    existing = await db.scalar(
        select(func.count()).select_from(Round).where(Round.league_id == league_id)
    )
    next_number = (existing or 0) + 1
    if next_number > league.total_rounds:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="all rounds for this league have already been created",
        )

    round_ = Round(
        league_id=league_id,
        round_number=next_number,
        theme=payload.theme,
        submission_deadline=payload.submission_deadline,
        voting_deadline=payload.voting_deadline,
        votes_per_player=(
            payload.votes_per_player
            if payload.votes_per_player is not None
            else league.votes_per_player
        ),
    )
    db.add(round_)
    # The newly opened round becomes the league's active round. The
    # (league_id, round_number) unique constraint guards integrity if two
    # creates ever race.
    league.current_round = next_number
    await db.commit()
    await db.refresh(round_)
    return _to_response(round_)


@router.get("/leagues/{league_id}/rounds", response_model=list[RoundResponse])
async def list_rounds(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoundResponse]:
    await _load_league_as_member(league_id, current_user, db)
    rounds = await db.scalars(
        select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
    )
    return [_to_response(r) for r in rounds]


@router.get("/rounds/{round_id}", response_model=RoundResponse)
async def get_round(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    return _to_response(round_)


@router.patch("/rounds/{round_id}", response_model=RoundResponse)
async def update_round(
    round_id: uuid.UUID,
    payload: RoundUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundResponse:
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_organizer(
        round_.league_id, current_user, db, "only the organizer can update rounds"
    )

    updates = payload.model_dump(exclude_unset=True)
    new_state = updates.pop("state", None)

    # Field edits (theme, deadlines) are frozen once the round is closed.
    if updates and round_.state == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="round is closed")
    for field, value in updates.items():
        setattr(round_, field, value)

    if new_state is not None and new_state != round_.state:
        if new_state != _NEXT_STATE.get(round_.state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot move round from {round_.state} to {new_state}",
            )
        round_.state = new_state
        if new_state == "closed":
            round_.closed_at = func.now()
            # Closing the final round completes the league.
            if round_.round_number >= league.total_rounds:
                league.state = "complete"
                league.completed_at = func.now()

    await db.commit()
    await db.refresh(round_)
    return _to_response(round_)


# --------------------------------------------------------------------------- #
# Playlist (MYS-18 slice B)
# --------------------------------------------------------------------------- #


class PlaylistEntry(BaseModel):
    submission_id: str
    isrc: str
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    participation_mode: str
    # Platform links resolved from the stored Odesli payload (may be empty if
    # the upstream lookup failed at submission time).
    platforms: dict[str, str]
    # The single link to surface by default: the viewer's preferred service,
    # else YouTube as the universal fallback, else any available platform.
    preferred_url: str | None


class PlaylistResponse(BaseModel):
    round_id: str
    round_number: int
    theme: str
    state: str
    entries: list[PlaylistEntry]


def _preferred_url(platforms: dict[str, str], preferred_service: str | None) -> str | None:
    if preferred_service and preferred_service in platforms:
        return platforms[preferred_service]
    if "youtube" in platforms:  # universal fallback (technical-design §8)
        return platforms["youtube"]
    return next(iter(platforms.values()), None)


@router.get("/rounds/{round_id}/playlist", response_model=PlaylistResponse)
async def get_round_playlist(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlaylistResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    # The playlist is the voting surface; it opens once submissions are locked.
    if round_.state == "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the playlist is available once voting opens",
        )

    submissions = list(await db.scalars(select(Submission).where(Submission.round_id == round_id)))
    # Anonymous + shuffled (technical-design §8). Seed the shuffle on the round id
    # so the order is stable per round but hides submission/creation order.
    random.Random(round_id.int).shuffle(submissions)

    entries = []
    for s in submissions:
        platforms = s.platform_links or {}
        entries.append(
            PlaylistEntry(
                submission_id=str(s.id),
                isrc=s.isrc,
                title=s.title,
                artist=s.artist,
                album=s.album,
                album_art_url=s.album_art_url,
                participation_mode=s.participation_mode,
                platforms=platforms,
                preferred_url=_preferred_url(platforms, current_user.preferred_service),
            )
        )
    return PlaylistResponse(
        round_id=str(round_.id),
        round_number=round_.round_number,
        theme=round_.theme,
        state=round_.state,
        entries=entries,
    )


# --------------------------------------------------------------------------- #
# Results (MYS-23)
# --------------------------------------------------------------------------- #


class ResultNote(BaseModel):
    body: str
    author_display_name: str
    created_at: datetime


class ResultSubmission(BaseModel):
    submission_id: str
    user_id: str
    submitter_display_name: str
    isrc: str
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    participation_mode: str
    # The submitter's own optional note attached at submission time.
    submitter_note: str | None
    vote_count: int
    # Notes others left on this submission, oldest first.
    notes: list[ResultNote]


class LeaderboardEntry(BaseModel):
    user_id: str
    display_name: str
    vote_count: int
    rank: int


class MostNotedWinner(BaseModel):
    submission_id: str
    title: str
    artist: str
    note_count: int
    notes: list[ResultNote]


class MostNotedResult(BaseModel):
    note_count: int
    winners: list[MostNotedWinner]


class ResultsResponse(BaseModel):
    round_id: str
    round_number: int
    theme: str
    state: str
    submissions: list[ResultSubmission]
    leaderboard: list[LeaderboardEntry]
    most_noted: MostNotedResult


@router.get("/rounds/{round_id}/results", response_model=ResultsResponse)
async def get_round_results(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResultsResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    # Results are the reveal: submitters and vote tallies stay hidden until close.
    if round_.state != "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="results are available once the round closes",
        )

    # Submissions joined to their submitter (revealed now the round is closed).
    submission_rows = (
        await db.execute(
            select(Submission, User.display_name)
            .join(User, User.id == Submission.user_id)
            .where(Submission.round_id == round_id)
        )
    ).all()

    # Vote tallies in one pass; submissions with no votes are simply absent here
    # and default to 0 below.
    vote_count_rows = (
        await db.execute(
            select(Vote.submission_id, func.count())
            .where(Vote.round_id == round_id)
            .group_by(Vote.submission_id)
        )
    ).all()
    votes_by_submission: dict[uuid.UUID, int] = {sid: count for sid, count in vote_count_rows}

    # All notes for the round, joined to author display names, grouped in Python.
    note_rows = (
        await db.execute(
            select(Note, User.display_name)
            .join(User, User.id == Note.author_id)
            .where(Note.round_id == round_id)
            .order_by(Note.created_at.asc())
        )
    ).all()
    notes_by_submission: dict[uuid.UUID, list[ResultNote]] = {}
    for note, display_name in note_rows:
        notes_by_submission.setdefault(note.submission_id, []).append(
            ResultNote(
                body=note.body,
                author_display_name=display_name,
                created_at=note.created_at,
            )
        )

    submissions = [
        ResultSubmission(
            submission_id=str(s.id),
            user_id=str(s.user_id),
            submitter_display_name=display_name,
            isrc=s.isrc,
            title=s.title,
            artist=s.artist,
            album=s.album,
            album_art_url=s.album_art_url,
            participation_mode=s.participation_mode,
            submitter_note=s.note,
            vote_count=votes_by_submission.get(s.id, 0),
            notes=notes_by_submission.get(s.id, []),
        )
        for s, display_name in submission_rows
    ]
    # Deterministic order: most-voted first, then title A->Z as a stable tiebreak.
    submissions.sort(key=lambda s: (-s.vote_count, s.title))

    # Leaderboard: playing submitters only (vibing are excluded). Ranked by votes
    # received desc, display_name asc as the tiebreak. Rank is 1-based position
    # (ties take sequential positions, not shared rank). Zero-vote players still
    # appear, ranked last.
    playing = [s for s in submissions if s.participation_mode == "playing"]
    playing.sort(key=lambda s: (-s.vote_count, s.submitter_display_name))
    leaderboard = [
        LeaderboardEntry(
            user_id=s.user_id,
            display_name=s.submitter_display_name,
            vote_count=s.vote_count,
            rank=i + 1,
        )
        for i, s in enumerate(playing)
    ]

    most_noted = await compute_most_noted(round_id, db)
    most_noted_result = MostNotedResult(
        note_count=most_noted.note_count,
        winners=[
            MostNotedWinner(
                submission_id=str(w.submission_id),
                title=w.title,
                artist=w.artist,
                note_count=w.note_count,
                notes=[
                    ResultNote(
                        body=n.body,
                        author_display_name=n.author_display_name,
                        created_at=n.created_at,
                    )
                    for n in w.notes
                ],
            )
            for w in most_noted.winners
        ],
    )

    return ResultsResponse(
        round_id=str(round_.id),
        round_number=round_.round_number,
        theme=round_.theme,
        state=round_.state,
        submissions=submissions,
        leaderboard=leaderboard,
        most_noted=most_noted_result,
    )
