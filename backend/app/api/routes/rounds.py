"""Round flow endpoints (MYS-18).

Round lifecycle and the create/read/update surface for a league's rounds:

* ``POST  /api/v1/leagues/:id/rounds``       — organizer (or co-organizer) creates the next round
* ``GET   /api/v1/leagues/:id/rounds``       — members list a league's rounds
* ``GET   /api/v1/rounds/:id``               — members read a round
* ``PATCH /api/v1/rounds/:id``               — organizer (or co-organizer) edits fields / advances state
* ``GET   /api/v1/rounds/:id/playlist``      — members get the anonymous voting playlist

State machine is forward-only: ``pending -> open_submission -> open_voting ->
closed``. Rounds are auto-generated as ``pending`` at league creation; only one
round per league may be active (open_submission/open_voting) at a time, enforced
when a round opens. The
playlist surfaces each submission resolved to the viewer's preferred service (it
reads the stored ``platform_links``). Membership/organizer checks reuse the helpers
in :mod:`app.api.routes.leagues` — "organizer" there also admits a promoted
co-organizer (``league_members.role == "admin"``, MYS-99).
"""

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member, _load_league_as_organizer
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.apple_round_playlist import AppleRoundPlaylist
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.spotify_client import SpotifyClient, get_spotify_client
from app.services.spotify_playlist_generation import try_auto_generate_playlist
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
    # Submission progress (MYS-101): how many songs are in, out of the league's
    # active members. The client shows "X of Y submitted" while submissions are
    # open. member_count is a league fact denormalized onto the round so the
    # round-detail screen needn't also fetch the member list.
    submission_count: int
    member_count: int
    # Viewer participation flags: whether the current user has submitted / voted
    # in this round. Used on the league-home tile to show confirmation indicators.
    viewer_submitted: bool = False
    viewer_voted: bool = False
    # Voting progress (MYS-110): how many playing submitters have cast a vote,
    # out of the total playing submitters. The client shows "X of Y voted" while
    # voting is open. voting_eligible_count = distinct playing submitters;
    # voted_count = distinct voters.
    voted_count: int = 0
    voting_eligible_count: int = 0


def _to_response(
    r: Round,
    submission_count: int,
    member_count: int,
    voted_count: int = 0,
    voting_eligible_count: int = 0,
    *,
    viewer_submitted: bool = False,
    viewer_voted: bool = False,
) -> RoundResponse:
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
        submission_count=submission_count,
        member_count=member_count,
        voted_count=voted_count,
        voting_eligible_count=voting_eligible_count,
        viewer_submitted=viewer_submitted,
        viewer_voted=viewer_voted,
    )


async def _submission_count(round_id: uuid.UUID, db: AsyncSession) -> int:
    # Distinct players who have submitted (a player may hold several songs now —
    # MYS-116), so "X of Y submitted" counts people, not songs.
    return (
        await db.scalar(
            select(func.count(func.distinct(Submission.user_id))).where(
                Submission.round_id == round_id
            )
        )
    ) or 0


async def _member_count(league_id: uuid.UUID, db: AsyncSession) -> int:
    """Count of a league's active (not-removed) members — the "Y" in X of Y."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(LeagueMember)
            .where(
                LeagueMember.league_id == league_id,
                LeagueMember.removed_at.is_(None),
            )
        )
    ) or 0


async def _viewer_submitted(round_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            select(exists().where(Submission.round_id == round_id, Submission.user_id == user_id))
        )
    )


async def _viewer_voted(round_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
    return bool(
        await db.scalar(select(exists().where(Vote.round_id == round_id, Vote.voter_id == user_id)))
    )


async def _voted_count(round_id: uuid.UUID, db: AsyncSession) -> int:
    """Distinct voters in a round — the "X" in X of Y voted."""
    return (
        await db.scalar(
            select(func.count(func.distinct(Vote.voter_id))).where(Vote.round_id == round_id)
        )
    ) or 0


async def _voting_eligible_count(round_id: uuid.UUID, db: AsyncSession) -> int:
    """Distinct playing submitters in a round — the "Y" in X of Y voted."""
    return (
        await db.scalar(
            select(func.count(func.distinct(Submission.user_id))).where(
                Submission.round_id == round_id,
                Submission.participation_mode == "playing",
            )
        )
    ) or 0


async def _load_round(round_id: uuid.UUID, db: AsyncSession) -> Round:
    round_ = await db.scalar(select(Round).where(Round.id == round_id))
    if round_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="round not found")
    return round_


async def advance_round_state(
    round_: Round, league: League, new_state: str, db: AsyncSession
) -> list[tuple[Round, RoundEvent]]:
    """Apply an ALREADY-VALIDATED forward transition of ``round_`` to ``new_state``.

    The caller guarantees ``new_state == _NEXT_STATE[round_.state]`` and owns any
    higher-level guards (e.g. the "another round is already active" check for the
    organizer's manual pending->open_submission step). This helper only performs
    the transition and its side effects:

    * entering ``open_submission`` — stamp ``submission_opened_at`` and make the
      round the league's ``current_round``;
    * ``closed`` — stamp ``closed_at``, then either complete the league (final
      round) or auto-open the next pending round (stamping *its*
      ``submission_opened_at`` + ``current_round``).

    Returns the ``(round, event)`` notification tuples to dispatch (including the
    auto-opened next round's ``submission_open``). It does NOT commit.
    """
    events: list[tuple[Round, RoundEvent]] = []
    round_.state = new_state
    if new_state == "open_submission":
        round_.submission_opened_at = func.now()
        # Stamp the submission deadline from the league window (MYS-159), unless the
        # organizer already set one explicitly at round creation — don't clobber it.
        if round_.submission_deadline is None:
            round_.submission_deadline = datetime.now(timezone.utc) + timedelta(
                hours=league.submission_window_hours
            )
        league.current_round = round_.round_number
        events.append((round_, "submission_open"))
    elif new_state == "open_voting":
        # Stamp the voting deadline from the league window (MYS-159), unless the
        # organizer already set one explicitly — don't clobber a manual value.
        if round_.voting_deadline is None:
            round_.voting_deadline = datetime.now(timezone.utc) + timedelta(
                hours=league.voting_window_hours
            )
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
                next_round.submission_opened_at = func.now()
                # Same league window as the manual open (MYS-159): stamp the next
                # round's submission deadline unless it was set explicitly.
                if next_round.submission_deadline is None:
                    next_round.submission_deadline = datetime.now(timezone.utc) + timedelta(
                        hours=league.submission_window_hours
                    )
                league.current_round = next_round.round_number
                events.append((next_round, "submission_open"))
    return events


async def rollback_round_to_submission(round_: Round, league: League, db: AsyncSession) -> None:
    """Organizer-only reverse transition, ``open_voting -> open_submission``
    (MYS-168) — the single sanctioned backward step in an otherwise forward-only
    lifecycle. Born from a live incident where a round advanced to voting by
    accident and had to be rolled back by hand-run SQL; this reproduces exactly
    that fix as a supported action.

    Unlike ``advance_round_state``, every stamp here is an unconditional
    overwrite, not a no-clobber guard — the round already has a stale
    ``submission_deadline`` from its first pass through ``open_submission``, and
    a rollback must replace it with a fresh full window, not preserve it.

    Caller must already hold the row lock (``with_for_update``) and have
    re-verified ``round_.state == "open_voting"`` under that lock — this
    function only applies the transition, it does not itself guard concurrency.
    """
    round_.state = "open_submission"
    round_.submission_opened_at = func.now()
    round_.submission_deadline = datetime.now(timezone.utc) + timedelta(
        hours=league.submission_window_hours
    )
    # Re-stamped when voting genuinely reopens; the no-clobber guard in
    # advance_round_state requires this to be NULL.
    round_.voting_deadline = None
    # Warnings re-arm for the new window/phase.
    round_.submission_warning_sent_at = None
    round_.voting_warning_sent_at = None
    round_.empty_round_notice_sent_at = None
    # The ballot set may change under a reopened submission phase; stale votes
    # would poison results and could insta-satisfy the voting quorum on the
    # next pass. Notes are kept — they're appreciation, remain state-gated, and
    # resurface at close.
    await db.execute(delete(Vote).where(Vote.round_id == round_.id))

    # Apple playlists are marked superseded so members can rebuild against the
    # new submissions (MYS-108). Marked, not deleted: Apple has no
    # replace-tracks for library playlists, so a rebuild necessarily creates a
    # second one, and keeping the row is what lets that rebuild know it's a
    # revision and name itself distinctly. The playlist already in the member's
    # library is untouched — we can't reach into it.
    #
    # Spotify is deliberately NOT cleared: its generation reuses the stored id
    # via replace_tracks, so the existing playlist refreshes in place and the
    # link members already hold stays correct. Clearing it would orphan a public
    # playlist on the shared account and mint a duplicate. YouTube needs nothing
    # — it's computed from submissions at read time.
    await db.execute(
        update(AppleRoundPlaylist)
        .where(
            AppleRoundPlaylist.round_id == round_.id,
            AppleRoundPlaylist.superseded_at.is_(None),
        )
        .values(superseded_at=func.now())
    )


async def submission_quorum_met(round_: Round, db: AsyncSession) -> bool:
    """True iff every member active when submissions opened has at least one song
    in the round (MYS-69 auto-advance).

    Active-at-open set = league members with ``joined_at <= submission_opened_at``
    and ``removed_at IS NULL``. Met when that set is a subset of the round's
    distinct submitters. A NULL ``submission_opened_at`` (shouldn't happen for an
    open round) is guarded as not met; an empty active-at-open set is treated as
    NOT met so an empty round is never advanced.
    """
    if round_.submission_opened_at is None:
        return False
    active_ids = set(
        await db.scalars(
            select(LeagueMember.user_id).where(
                LeagueMember.league_id == round_.league_id,
                LeagueMember.joined_at <= round_.submission_opened_at,
                LeagueMember.removed_at.is_(None),
            )
        )
    )
    if not active_ids:
        return False
    submitter_ids = set(
        await db.scalars(
            select(Submission.user_id).where(Submission.round_id == round_.id).distinct()
        )
    )
    return active_ids <= submitter_ids


async def voting_quorum_met(round_: Round, db: AsyncSession) -> bool:
    """True iff every playing submitter in the round has cast a vote.

    Playing submitter set = distinct submitters whose ``participation_mode`` is
    ``playing`` (vibers are excluded — they can't vote). Met when that set is a
    subset of the round's distinct voters. An empty playing set is treated as met
    only when there is at least one submission (i.e. everyone submitted as vibing);
    a round with no submissions at all returns False so an empty round is never
    auto-closed.
    """
    playing_ids = set(
        await db.scalars(
            select(Submission.user_id)
            .where(
                Submission.round_id == round_.id,
                Submission.participation_mode == "playing",
            )
            .distinct()
        )
    )
    if not playing_ids:
        # Guard: only treat all-vibing as quorum-met when there are actual submissions.
        total = await db.scalar(
            select(func.count()).select_from(Submission).where(Submission.round_id == round_.id)
        )
        return (total or 0) > 0
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.round_id == round_.id).distinct())
    )
    return playing_ids <= voter_ids


@router.post("/leagues/{league_id}/rounds", status_code=201, response_model=RoundResponse)
async def create_round(
    league_id: uuid.UUID,
    payload: RoundCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundResponse:
    league = await _load_league_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can create rounds"
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
    # A freshly created round opens for submissions immediately (the model's
    # default state), so stamp when that window opened — auto-advance (MYS-69)
    # scopes its quorum to the members present at this moment.
    round_.submission_opened_at = func.now()
    db.add(round_)
    # The newly opened round becomes the league's active round. The
    # (league_id, round_number) unique constraint guards integrity if two
    # creates ever race.
    league.current_round = next_number
    await db.commit()
    await db.refresh(round_)
    # A freshly created round has no submissions or votes yet.
    return _to_response(round_, 0, await _member_count(league_id, db))


@router.get("/leagues/{league_id}/rounds", response_model=list[RoundResponse])
async def list_rounds(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoundResponse]:
    await _load_league_as_member(league_id, current_user, db)
    rounds = list(
        await db.scalars(
            select(Round).where(Round.league_id == league_id).order_by(Round.round_number.asc())
        )
    )
    member_count = await _member_count(league_id, db)
    round_ids = [r.id for r in rounds]
    # One grouped count per field for the whole slate rather than a query per round.
    # Distinct submitters (people, not songs — MYS-116).
    count_rows = await db.execute(
        select(Submission.round_id, func.count(func.distinct(Submission.user_id)))
        .where(Submission.round_id.in_(round_ids))
        .group_by(Submission.round_id)
    )
    counts = {round_id: count for round_id, count in count_rows.all()}
    # Viewer participation: one query each for submitted/voted round IDs.
    sub_rows = await db.execute(
        select(Submission.round_id)
        .where(Submission.round_id.in_(round_ids), Submission.user_id == current_user.id)
        .distinct()
    )
    viewer_submitted_ids = {row[0] for row in sub_rows.all()}
    vote_rows = await db.execute(
        select(Vote.round_id)
        .where(Vote.round_id.in_(round_ids), Vote.voter_id == current_user.id)
        .distinct()
    )
    viewer_voted_ids = {row[0] for row in vote_rows.all()}
    # Distinct voters per round (MYS-110).
    voted_rows = await db.execute(
        select(Vote.round_id, func.count(func.distinct(Vote.voter_id)))
        .where(Vote.round_id.in_(round_ids))
        .group_by(Vote.round_id)
    )
    voted_counts = {round_id: count for round_id, count in voted_rows.all()}
    # Distinct playing submitters per round — the voting denominator (MYS-110).
    eligible_rows = await db.execute(
        select(Submission.round_id, func.count(func.distinct(Submission.user_id)))
        .where(
            Submission.round_id.in_(round_ids),
            Submission.participation_mode == "playing",
        )
        .group_by(Submission.round_id)
    )
    eligible_counts = {round_id: count for round_id, count in eligible_rows.all()}
    return [
        _to_response(
            r,
            counts.get(r.id, 0),
            member_count,
            voted_counts.get(r.id, 0),
            eligible_counts.get(r.id, 0),
            viewer_submitted=r.id in viewer_submitted_ids,
            viewer_voted=r.id in viewer_voted_ids,
        )
        for r in rounds
    ]


@router.get("/rounds/{round_id}", response_model=RoundResponse)
async def get_round(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoundResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    return _to_response(
        round_,
        await _submission_count(round_id, db),
        await _member_count(round_.league_id, db),
        await _voted_count(round_id, db),
        await _voting_eligible_count(round_id, db),
        viewer_submitted=await _viewer_submitted(round_id, current_user.id, db),
        viewer_voted=await _viewer_voted(round_id, current_user.id, db),
    )


@router.patch("/rounds/{round_id}", response_model=RoundResponse)
async def update_round(
    round_id: uuid.UUID,
    payload: RoundUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
    spotify_client: SpotifyClient = Depends(get_spotify_client),
) -> RoundResponse:
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_organizer(
        round_.league_id, current_user, db, "only an organizer or co-organizer can update rounds"
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
        # The single sanctioned backward step (MYS-168): open_voting ->
        # open_submission. Everything else stays forward-only.
        is_rollback = round_.state == "open_voting" and new_state == "open_submission"
        if not is_rollback and new_state != _NEXT_STATE.get(round_.state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot move round from {round_.state} to {new_state}",
            )
        # Opening a pending round: only one round may be active per league. This
        # guard is the organizer's manual step only; auto-advance never makes the
        # pending->open_submission move, so it lives here, not in the helper. A
        # rollback is exempt — the round is already the league's active round,
        # so there is by definition no *other* active round to conflict with.
        if new_state == "open_submission" and not is_rollback:
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
        if is_rollback:
            # Serialize with the deadline force-advance job and the vote-cast
            # auto-close (MYS-145/MYS-69) under the same FOR UPDATE discipline,
            # then re-verify under the lock — the round may have just been
            # force-closed or auto-closed concurrently.
            locked = await db.scalar(
                select(Round)
                .where(Round.id == round_.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked is None or locked.state != "open_voting":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="round is no longer open for voting",
                )
            await rollback_round_to_submission(round_, league, db)
            # Silent (product decision 2026-07-04): the organizer tells the
            # league directly, matching the incident's actual behavior — no
            # "submissions reopened" email. `events` stays empty.
        else:
            events = await advance_round_state(round_, league, new_state, db)
            # All-vibing edge: if voting just opened but every participant is vibing,
            # nobody will ever call cast_votes, so voting quorum is immediately met.
            # Close in the same transaction and suppress the voting_open notification
            # (nobody could vote in a round that closes in the same breath).
            if round_.state == "open_voting" and await voting_quorum_met(round_, db):
                events = [e for e in events if e != (round_, "voting_open")]
                events += await advance_round_state(round_, league, "closed", db)

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

    # Auto-generate the shared-account Spotify playlist the moment voting opens
    # (MYS-176) — no admin click needed. Best-effort: never raises, so a Spotify
    # hiccup can't block this transition (see try_auto_generate_playlist).
    if any(event == "voting_open" for _, event in events):
        await try_auto_generate_playlist(round_id, round_, league, db, spotify_client, settings)

    await db.commit()
    await db.refresh(round_)
    return _to_response(
        round_,
        await _submission_count(round_.id, db),
        await _member_count(round_.league_id, db),
        await _voted_count(round_.id, db),
        await _voting_eligible_count(round_.id, db),
        viewer_submitted=await _viewer_submitted(round_.id, current_user.id, db),
        viewer_voted=await _viewer_voted(round_.id, current_user.id, db),
    )


# Upper bound on how far a single extension may push the deadline out,
# measured from the *current* deadline (MYS-180) — the organizer picks any
# point in this window, not a fixed increment.
_MAX_VOTING_EXTENSION = timedelta(hours=48)


class ExtendVotingRequest(BaseModel):
    voting_deadline: datetime


@router.post("/rounds/{round_id}/extend-voting", response_model=RoundResponse)
async def extend_voting_deadline(
    round_id: uuid.UUID,
    payload: ExtendVotingRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> RoundResponse:
    """Push a round's voting deadline to an organizer-chosen time, up to 48h past
    the current deadline (MYS-180).

    Same permission level as every other round-management action (organizer or
    co-organizer). Only valid while the round is still ``open_voting`` — locked
    under ``FOR UPDATE`` and re-verified, the same discipline as the MYS-168
    rollback path, since this races the deadline job and vote-cast auto-close."""
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_organizer(
        round_.league_id, current_user, db, "only an organizer or co-organizer can extend voting"
    )

    locked = await db.scalar(
        select(Round)
        .where(Round.id == round_.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="round is not open for voting",
        )

    current_deadline = locked.voting_deadline or datetime.now(timezone.utc)
    new_deadline = payload.voting_deadline
    if new_deadline.tzinfo is None:
        new_deadline = new_deadline.replace(tzinfo=timezone.utc)
    if new_deadline <= current_deadline:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="the new deadline must be after the current one",
        )
    if new_deadline > current_deadline + _MAX_VOTING_EXTENSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="can't extend more than 48 hours past the current deadline",
        )

    locked.voting_deadline = new_deadline
    # Let the deadline job send a fresh "12h left" warning against the new
    # deadline — the old marker refers to a deadline that no longer applies.
    locked.voting_warning_sent_at = None

    recipients = await gather_recipients(db, league.id)
    queue_round_event(
        background_tasks, sender, settings, recipients, league, locked, "voting_extended"
    )

    await db.commit()
    await db.refresh(locked)
    return _to_response(
        locked,
        await _submission_count(locked.id, db),
        await _member_count(locked.league_id, db),
        await _voted_count(locked.id, db),
        await _voting_eligible_count(locked.id, db),
        viewer_submitted=await _viewer_submitted(locked.id, current_user.id, db),
        viewer_voted=await _viewer_voted(locked.id, current_user.id, db),
    )


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
    # participation_mode is intentionally NOT exposed (MYS-112): vibing is private,
    # so the voting playlist must not reveal which songs are vibers'.
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
    # The submitter's optional context note. Shown to all voters; never includes
    # the submitter's identity (anonymity is preserved through the voting phase).
    submitter_note: str | None


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
    # Voting progress (MYS-102): "X of Y voted or noted · Z just vibing".
    #  - voting_eligible (Y): playing participants — the ones who can vote.
    #  - voting_acted    (X): playing participants who have cast a vote OR left a
    #    note this round.
    #  - vibing_count    (Z): vibing participants, along for the ride (they sit
    #    voting out, so they're reported separately, not inside X/Y).
    voting_eligible: int
    voting_acted: int
    vibing_count: int


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
    # Anonymous + shuffled (technical-design §8). Sort by id first so Postgres heap
    # order doesn't affect the result, then seed the shuffle on the round id for a
    # stable per-round order that's consistent across all playlist platforms (MYS-151).
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    # Voting progress (MYS-102). Playing participants are the eligible voters;
    # vibing participants sit voting out (reported separately). A playing player
    # counts as having "acted" once they've cast a vote or left a note.
    playing_user_ids = {s.user_id for s in submissions if s.participation_mode == "playing"}
    vibing_count = sum(1 for s in submissions if s.participation_mode == "vibing")
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.round_id == round_id).distinct())
    )
    note_author_ids = set(
        await db.scalars(select(Note.author_id).where(Note.round_id == round_id).distinct())
    )
    acted_user_ids = playing_user_ids & (voter_ids | note_author_ids)

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
                platforms=platforms,
                preferred_url=_preferred_url(platforms, current_user.preferred_service),
                is_own=s.user_id == current_user.id,
                submitter_note=s.note,
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
        voting_eligible=len(playing_user_ids),
        voting_acted=len(acted_user_ids),
        vibing_count=vibing_count,
    )


# --------------------------------------------------------------------------- #
# Results (MYS-23)
# --------------------------------------------------------------------------- #


class ResultNote(BaseModel):
    body: str
    author_display_name: str
    created_at: datetime


class ResultVoter(BaseModel):
    user_id: str
    display_name: str


class ResultSubmission(BaseModel):
    submission_id: str
    user_id: str
    submitter_display_name: str
    isrc: str
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    # participation_mode is intentionally NOT exposed (MYS-112): vibing stays
    # private — the reveal never shows who vibed.
    # Cross-service playback links so the reveal tiles are playable (MYS-134
    # follow-up); may be empty if the submit-time lookup failed.
    platforms: dict[str, str]
    # The submitter's own optional note attached at submission time.
    submitter_note: str | None
    vote_count: int
    # Notes others left on this submission, oldest first.
    notes: list[ResultNote]
    # Who voted for this song (MYS-173). Voting itself stays anonymous through
    # open_voting; this is only ever populated on the closed-round reveal, and
    # only on ResultSubmission — the vibe-safe RevealPick/WinnerReveal shapes
    # below intentionally omit it so a vibing viewer never sees voter identity,
    # matching the existing no-vote-count rule (MYS-112).
    voters: list[ResultVoter]


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


class WinnerReveal(BaseModel):
    # The vibe-safe winner shape (MYS-112): the song(s) with the most votes,
    # named but WITHOUT a vote count. Sent to a vibing viewer, who sees who won
    # but no rankings/tallies.
    submission_id: str
    title: str
    artist: str
    submitter_display_name: str


class RevealPick(BaseModel):
    # The vibe-safe pick shape (MYS-134): a submitted song with its submitter and
    # notes, but NO vote count — so a vibing viewer can see the tracklist without
    # any scores/rankings leaking.
    submission_id: str
    submitter_display_name: str
    title: str
    artist: str
    # Playback links so the tiles are playable, same as the player reveal.
    platforms: dict[str, str]
    submitter_note: str | None
    notes: list[ResultNote]


class ResultsResponse(BaseModel):
    round_id: str
    round_number: int
    # Nullable: a round may not have a theme yet (clients fall back to "Round N").
    theme: str | None
    state: str
    # Reveal is gated by the viewer's participation mode for the round (MYS-112).
    # A player sees the full reveal below; a viber sees only `winners`, `picks`,
    # and `most_noted` — `submissions` and `leaderboard` are empty for them so no
    # vote counts/rankings leak. A non-submitter is treated as a player.
    viewer_is_vibing: bool
    submissions: list[ResultSubmission]
    leaderboard: list[LeaderboardEntry]
    most_noted: MostNotedResult
    # Vibing-viewer-only fields (empty for players). `winners` names the top-voted
    # song(s) without counts; `picks` is the full tracklist without scores
    # (MYS-134).
    winners: list[WinnerReveal] = []
    picks: list[RevealPick] = []


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

    # Voter identity per submission (MYS-173) — who cast each vote, revealed only
    # now that the round is closed (voting itself stays anonymous throughout
    # open_voting; this endpoint is already gated to state == "closed" above).
    voter_rows = (
        await db.execute(
            select(Vote.submission_id, Vote.voter_id, User.display_name)
            .join(User, User.id == Vote.voter_id)
            .where(Vote.round_id == round_id)
        )
    ).all()
    voters_by_submission: dict[uuid.UUID, list[ResultVoter]] = {}
    for submission_id, voter_id, display_name in voter_rows:
        voters_by_submission.setdefault(submission_id, []).append(
            ResultVoter(user_id=str(voter_id), display_name=display_name)
        )
    for voters in voters_by_submission.values():
        voters.sort(key=lambda v: v.display_name)

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
            platforms=s.platform_links or {},
            submitter_note=s.note,
            vote_count=votes_by_submission.get(s.id, 0),
            notes=notes_by_submission.get(s.id, []),
            voters=voters_by_submission.get(s.id, []),
        )
        for s, display_name in submission_rows
    ]
    # Deterministic order: most-voted first, then title A->Z as a stable tiebreak.
    submissions.sort(key=lambda s: (-s.vote_count, s.title))

    # Leaderboard: per-player totals, summing a player's votes across all their
    # songs (MYS-116), so a multi-song player is one standing. Every submitter
    # competes, including vibers (MYS-112). Ranked by total votes desc,
    # display_name asc as the tiebreak; rank is 1-based position (ties take
    # sequential positions). Zero-vote players still appear, ranked last.
    player_totals: dict[str, int] = {}
    player_names: dict[str, str] = {}
    for s in submissions:
        player_totals[s.user_id] = player_totals.get(s.user_id, 0) + s.vote_count
        player_names[s.user_id] = s.submitter_display_name
    ranked_players = sorted(player_totals.items(), key=lambda kv: (-kv[1], player_names[kv[0]]))
    leaderboard = [
        LeaderboardEntry(
            user_id=uid,
            display_name=player_names[uid],
            vote_count=total,
            rank=i + 1,
        )
        for i, (uid, total) in enumerate(ranked_players)
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

    # Reveal gating (MYS-112). The viewer's mode for this round comes from their
    # own submission (read from the ORM rows — it's not exposed on the response);
    # a non-submitter is treated as a player (full reveal).
    own_sub = next((s for s, _ in submission_rows if s.user_id == current_user.id), None)
    viewer_is_vibing = own_sub is not None and own_sub.participation_mode == "vibing"

    if not viewer_is_vibing:
        return ResultsResponse(
            round_id=str(round_.id),
            round_number=round_.round_number,
            theme=round_.theme,
            state=round_.state,
            viewer_is_vibing=False,
            submissions=submissions,
            leaderboard=leaderboard,
            most_noted=most_noted_result,
        )

    # Vibing viewer (MYS-134): winner(s) + Most Noted + the full tracklist, but no
    # leaderboard and no vote counts. The winner is the top-scoring *player* by
    # total votes (MYS-116), matching the leaderboard; we surface that player's
    # song(s). A top of zero means nobody was voted for — no winner. picks is the
    # same song set as the player reveal, stripped of scores and ordered by title.
    top_total = max(player_totals.values(), default=0)
    winning_user_ids = (
        {uid for uid, total in player_totals.items() if total == top_total}
        if top_total > 0
        else set()
    )
    winners = [
        WinnerReveal(
            submission_id=s.submission_id,
            title=s.title,
            artist=s.artist,
            submitter_display_name=s.submitter_display_name,
        )
        for s in submissions
        if s.user_id in winning_user_ids
    ]
    picks = [
        RevealPick(
            submission_id=s.submission_id,
            submitter_display_name=s.submitter_display_name,
            title=s.title,
            artist=s.artist,
            platforms=s.platforms,
            submitter_note=s.submitter_note,
            notes=s.notes,
        )
        for s in sorted(submissions, key=lambda s: s.title)
    ]
    return ResultsResponse(
        round_id=str(round_.id),
        round_number=round_.round_number,
        theme=round_.theme,
        state=round_.state,
        viewer_is_vibing=True,
        submissions=[],
        leaderboard=[],
        most_noted=most_noted_result,
        winners=winners,
        picks=picks,
    )
