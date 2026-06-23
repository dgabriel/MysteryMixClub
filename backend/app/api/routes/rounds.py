"""Round flow endpoints (MYS-18).

Round lifecycle and the create/read/update surface for a league's rounds:

* ``POST  /api/v1/leagues/:id/rounds``       — organizer creates the next round
* ``GET   /api/v1/leagues/:id/rounds``       — members list a league's rounds
* ``GET   /api/v1/rounds/:id``               — members read a round
* ``PATCH /api/v1/rounds/:id``               — organizer edits fields / advances state
* ``GET   /api/v1/rounds/:id/playlist``      — members get the anonymous voting playlist

State machine is forward-only: ``pending -> open_submission -> open_voting ->
closed``. Rounds are auto-generated as ``pending`` at league creation; only one
round per league may be active (open_submission/open_voting) at a time, enforced
when a round opens. The
playlist surfaces each submission resolved to the viewer's preferred service (it
reads the stored ``platform_links``). Membership/organizer checks reuse the helpers
in :mod:`app.api.routes.leagues`.
"""

import random
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member, _load_league_as_organizer
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.email import EmailSender, get_email_sender
from app.services.most_noted import compute_most_noted
from app.services.notifications import RoundEvent, gather_recipients, queue_round_event
from app.services.youtube_playlist import build_watch_videos_url, normalize_video_ids
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

router = APIRouter(tags=["rounds"])

RoundTheme = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Free-text round blurb. Capped + stripped to match the other text fields
# (theme/note/album) and the §9 input-sanitization contract.
RoundDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

# Forward-only lifecycle: each state's single permitted successor.
_NEXT_STATE = {
    "pending": "open_submission",
    "open_submission": "open_voting",
    "open_voting": "closed",
}

# States in which a round is the league's live round (exactly one at a time).
_ACTIVE_STATES = ("open_submission", "open_voting")


class RoundCreate(BaseModel):
    # Optional: rounds may be created without a theme (filled in while pending).
    theme: RoundTheme | None = None
    description: RoundDescription | None = None
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    # Defaults to the league's votes_per_player when omitted.
    votes_per_player: int | None = Field(default=None, ge=1)


class RoundUpdate(BaseModel):
    # All optional: only provided fields are applied. `state` advances the machine.
    # theme is nullable and may be cleared (it maps to a nullable column now).
    theme: RoundTheme | None = None
    description: RoundDescription | None = None
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    state: Literal["pending", "open_submission", "open_voting", "closed"] | None = None


class RoundResponse(BaseModel):
    id: str
    league_id: str
    round_number: int
    theme: str | None
    description: str | None
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
        description=r.description,
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
        description=payload.description,
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
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> RoundResponse:
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_organizer(
        round_.league_id, current_user, db, "only the organizer can update rounds"
    )

    updates = payload.model_dump(exclude_unset=True)
    new_state = updates.pop("state", None)
    # Lifecycle emails to fire once the transition commits (MYS-109). Collected as
    # (round, event) so an auto-opened next round notifies for *its* opening.
    events: list[tuple[Round, RoundEvent]] = []

    # Field edits (theme, deadlines) are frozen once the round is closed.
    if updates and round_.state == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="round is closed")
    # theme/description are the round's identity: editable only while pending.
    # Once the round opens, they are locked even though deadlines stay editable.
    if round_.state != "pending" and ("theme" in updates or "description" in updates):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="theme and description are locked once the round opens",
        )
    for field, value in updates.items():
        setattr(round_, field, value)

    if new_state is not None and new_state != round_.state:
        if new_state != _NEXT_STATE.get(round_.state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot move round from {round_.state} to {new_state}",
            )
        # Opening a pending round: only one round may be active per league.
        if new_state == "open_submission":
            active = await db.scalar(
                select(Round)
                .where(
                    Round.league_id == round_.league_id,
                    Round.id != round_.id,
                    Round.state.in_(_ACTIVE_STATES),
                )
                .limit(1)
            )
            if active is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="another round is already active",
                )
            league.current_round = round_.round_number
        round_.state = new_state
        if new_state == "open_submission":
            events.append((round_, "submission_open"))
        elif new_state == "open_voting":
            events.append((round_, "voting_open"))
        elif new_state == "closed":
            round_.closed_at = func.now()
            events.append((round_, "round_closed"))
            if round_.round_number >= league.total_rounds:
                # Closing the final round completes the league.
                league.state = "complete"
                league.completed_at = func.now()
                events.append((round_, "league_complete"))
            else:
                # Auto-open the next pending round in sequence, if any.
                next_round = await db.scalar(
                    select(Round).where(
                        Round.league_id == round_.league_id,
                        Round.round_number == round_.round_number + 1,
                        Round.state == "pending",
                    )
                )
                if next_round is not None:
                    next_round.state = "open_submission"
                    league.current_round = next_round.round_number
                    events.append((next_round, "submission_open"))

    # Build + schedule notifications before commit, while the ORM objects are
    # loaded (avoids post-commit lazy-loads in async — the expire_on_commit
    # MissingGreenlet trap). Background tasks only run on a successful response,
    # so a failed commit below means no emails go out.
    if events:
        recipients = await gather_recipients(db, round_.league_id)
        for event_round, event in events:
            queue_round_event(
                background_tasks, sender, settings, recipients, league, event_round, event
            )

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
    # Platform links assembled keyless at submission time and stored per
    # submission (may be empty if the upstream lookup failed then).
    platforms: dict[str, str]
    # The single link to surface by default: the viewer's preferred service,
    # else YouTube as the universal fallback, else any available platform.
    preferred_url: str | None
    # True for the caller's own submission. The playlist stays anonymous for
    # everyone else — this only lets the UI mark/lock the viewer's own pick
    # (they can't vote for it) without revealing any other submitter.
    is_own: bool


class PlaylistResponse(BaseModel):
    round_id: str
    round_number: int
    # Nullable: a round may not have a theme yet (clients fall back to "Round N").
    theme: str | None
    state: str
    entries: list[PlaylistEntry]
    # A single ad-hoc YouTube link that plays the whole mix in playlist order
    # (watch_videos?video_ids=...), or None if no track resolved to a YouTube id.
    youtube_playlist_url: str | None
    # How many of the round's tracks made it into the YouTube link, so the UI can
    # show "N of M on YouTube". 0 when youtube_playlist_url is None.
    youtube_track_count: int


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
    youtube: YouTubeResolver = Depends(get_youtube_resolver),
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
    video_ids: list[str] = []
    backfilled = False
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
                is_own=s.user_id == current_user.id,
            )
        )
        # YouTube ids are resolved at submit time. Lazily backfill any submission
        # that predates that (or whose submit-time resolve failed) so existing
        # rounds light up; cache it back so it's a one-time cost per submission.
        video_id = s.youtube_video_id
        if not video_id:
            video_id = await youtube.video_id_for(s.title, s.artist)
            if video_id:
                s.youtube_video_id = video_id
                backfilled = True
        if video_id:
            video_ids.append(video_id)

    # Best-effort: persist any backfilled ids, but never let a write failure break
    # the read — the link is still returned from the in-memory ids.
    if backfilled:
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    # Normalize once so the count and the URL can never disagree: the URL is
    # built from exactly these de-duped/capped ids, and the count is their length.
    playlist_ids = normalize_video_ids(video_ids)
    youtube_playlist_url = build_watch_videos_url(playlist_ids)
    return PlaylistResponse(
        round_id=str(round_.id),
        round_number=round_.round_number,
        theme=round_.theme,
        state=round_.state,
        entries=entries,
        youtube_playlist_url=youtube_playlist_url,
        youtube_track_count=len(playlist_ids),
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
    # Nullable: a round may not have a theme yet (clients fall back to "Round N").
    theme: str | None
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
