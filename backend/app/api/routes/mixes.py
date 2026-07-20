"""Mix flow endpoints (MYS-18).

Mix lifecycle and the create/read/update surface for a club's mixes:

* ``POST  /api/v1/clubs/:id/mixes``       — organizer (or co-organizer) creates the next mix
* ``GET   /api/v1/clubs/:id/mixes``       — members list a club's mixes
* ``GET   /api/v1/mixes/:id``               — members read a mix
* ``PATCH /api/v1/mixes/:id``               — organizer (or co-organizer) edits fields / advances state
* ``GET   /api/v1/mixes/:id/playlist``      — members get the anonymous voting playlist

State machine is forward-only: ``pending -> open_submission -> open_voting ->
closed``. Mixes are auto-generated as ``pending`` at club creation; only one
mix per club may be active (open_submission/open_voting) at a time, enforced
when a mix opens. The
playlist surfaces each submission resolved to the viewer's preferred service (it
reads the stored ``platform_links``). Membership/organizer checks reuse the helpers
in :mod:`app.api.routes.clubs` — "organizer" there also admits a promoted
co-organizer (``club_members.role == "admin"``, MYS-99).
"""

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import Field, StringConstraints

from app.api.wire import WireModel
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import _load_club_as_member, _load_club_as_organizer
from app.auth.deps import get_current_user
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.apple_mix_playlist import AppleMixPlaylist
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User
from app.services.source_tracks import source_fields
from app.services.spotify_client import SpotifyClient, get_spotify_client
from app.services.spotify_playlist_generation import try_auto_generate_playlist
from app.models.vote import Vote
from app.services.email import EmailSender, get_email_sender
from app.services.most_noted import compute_most_noted
from app.services.notifications import (
    MixEvent,
    gather_recipients,
    organizer_recipient,
    queue_mix_event,
)
from app.services.youtube_playlist import build_watch_videos_url, normalize_video_ids
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

router = APIRouter(tags=["mixes"])

MixTheme = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Free-text mix blurb. Capped + stripped to match the other text fields
# (theme/note/album) and the §9 input-sanitization contract.
MixDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

# Forward-only lifecycle: each state's single permitted successor.
_NEXT_STATE = {
    "pending": "open_submission",
    "open_submission": "open_voting",
    "open_voting": "closed",
}

# States in which a mix is the club's live mix (exactly one at a time).
_ACTIVE_STATES = ("open_submission", "open_voting")


class MixCreate(WireModel):
    # Optional: mixes may be created without a theme (filled in while pending).
    theme: MixTheme | None = None
    description: MixDescription | None = None
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    # Defaults to the club's votes_per_player when omitted.
    votes_per_player: int | None = Field(default=None, ge=1)


class MixUpdate(WireModel):
    # All optional: only provided fields are applied. `state` advances the machine.
    # theme is nullable and may be cleared (it maps to a nullable column now).
    theme: MixTheme | None = None
    description: MixDescription | None = None
    submission_deadline: datetime | None = None
    voting_deadline: datetime | None = None
    state: Literal["pending", "open_submission", "open_voting", "closed"] | None = None


class MixResponse(WireModel):
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
    # Submission progress (MYS-101): how many songs are in, out of the club's
    # active members. The client shows "X of Y submitted" while submissions are
    # open. member_count is a club fact denormalized onto the mix so the
    # mix-detail screen needn't also fetch the member list.
    submission_count: int
    member_count: int
    # Viewer participation flags: whether the current user has submitted / voted
    # in this mix. Used on the club-home tile to show confirmation indicators.
    viewer_submitted: bool = False
    viewer_voted: bool = False
    # Voting progress (MYS-110): how many playing submitters have cast a vote,
    # out of the total playing submitters. The client shows "X of Y voted" while
    # voting is open. voting_eligible_count = distinct playing submitters;
    # voted_count = distinct voters.
    voted_count: int = 0
    voting_eligible_count: int = 0


def _to_response(
    m: Mix,
    submission_count: int,
    member_count: int,
    voted_count: int = 0,
    voting_eligible_count: int = 0,
    *,
    viewer_submitted: bool = False,
    viewer_voted: bool = False,
) -> MixResponse:
    return MixResponse(
        id=str(m.id),
        league_id=str(m.club_id),
        round_number=m.mix_number,
        theme=m.theme,
        description=m.description,
        state=m.state,
        submission_deadline=m.submission_deadline,
        voting_deadline=m.voting_deadline,
        votes_per_player=m.votes_per_player,
        created_at=m.created_at,
        closed_at=m.closed_at,
        submission_count=submission_count,
        member_count=member_count,
        voted_count=voted_count,
        voting_eligible_count=voting_eligible_count,
        viewer_submitted=viewer_submitted,
        viewer_voted=viewer_voted,
    )


async def _submission_count(mix_id: uuid.UUID, db: AsyncSession) -> int:
    # Distinct players who have submitted (a player may hold several songs now —
    # MYS-116), so "X of Y submitted" counts people, not songs.
    return (
        await db.scalar(
            select(func.count(func.distinct(Submission.user_id))).where(Submission.mix_id == mix_id)
        )
    ) or 0


async def _member_count(league_id: uuid.UUID, db: AsyncSession) -> int:
    """Count of a club's active (not-removed) members — the "Y" in X of Y."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(ClubMember)
            .where(
                ClubMember.club_id == league_id,
                ClubMember.removed_at.is_(None),
            )
        )
    ) or 0


async def _viewer_submitted(mix_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            select(exists().where(Submission.mix_id == mix_id, Submission.user_id == user_id))
        )
    )


async def _viewer_voted(mix_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> bool:
    return bool(
        await db.scalar(select(exists().where(Vote.mix_id == mix_id, Vote.voter_id == user_id)))
    )


async def _voted_count(mix_id: uuid.UUID, db: AsyncSession) -> int:
    """Distinct voters in a mix — the "X" in X of Y voted."""
    return (
        await db.scalar(
            select(func.count(func.distinct(Vote.voter_id))).where(Vote.mix_id == mix_id)
        )
    ) or 0


async def _voting_eligible_count(mix_id: uuid.UUID, db: AsyncSession) -> int:
    """Distinct playing submitters in a mix — the "Y" in X of Y voted."""
    return (
        await db.scalar(
            select(func.count(func.distinct(Submission.user_id))).where(
                Submission.mix_id == mix_id,
                Submission.participation_mode == "playing",
            )
        )
    ) or 0


async def _load_mix(mix_id: uuid.UUID, db: AsyncSession) -> Mix:
    mix_ = await db.scalar(select(Mix).where(Mix.id == mix_id))
    if mix_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mystery mix not found")
    return mix_


async def advance_mix_state(
    mix_: Mix, club: Club, new_state: str, db: AsyncSession
) -> list[tuple[Mix, MixEvent]]:
    """Apply an ALREADY-VALIDATED forward transition of ``mix_`` to ``new_state``.

    The caller guarantees ``new_state == _NEXT_STATE[mix_.state]`` and owns any
    higher-level guards (e.g. the "another mix is already active" check for the
    organizer's manual pending->open_submission step). This helper only performs
    the transition and its side effects:

    * entering ``open_submission`` — stamp ``submission_opened_at`` and make the
      mix the club's ``current_mix``;
    * ``closed`` — stamp ``closed_at``, then either complete the club (final
      mix) or auto-open the next pending mix (stamping *its*
      ``submission_opened_at`` + ``current_mix``) — unless that next mix has
      no theme yet (MYS-211), in which case it's left ``pending`` and a
      ``needs_theme`` event fires instead of ``submission_open``.

    Returns the ``(mix, event)`` notification tuples to dispatch (including the
    auto-opened next mix's ``submission_open``, or its ``needs_theme`` if it
    couldn't open). It does NOT commit.
    """
    events: list[tuple[Mix, MixEvent]] = []
    mix_.state = new_state
    if new_state == "open_submission":
        mix_.submission_opened_at = func.now()
        # Stamp the submission deadline from the club window (MYS-159), unless the
        # organizer already set one explicitly at mix creation — don't clobber it.
        if mix_.submission_deadline is None:
            mix_.submission_deadline = datetime.now(timezone.utc) + timedelta(
                hours=club.submission_window_hours
            )
        club.current_mix = mix_.mix_number
        events.append((mix_, "submission_open"))
    elif new_state == "open_voting":
        # Stamp the voting deadline from the club window (MYS-159), unless the
        # organizer already set one explicitly — don't clobber a manual value.
        if mix_.voting_deadline is None:
            mix_.voting_deadline = datetime.now(timezone.utc) + timedelta(
                hours=club.voting_window_hours
            )
        events.append((mix_, "voting_open"))
    elif new_state == "closed":
        mix_.closed_at = func.now()
        events.append((mix_, "mix_closed"))
        if mix_.mix_number >= club.total_mixes:
            # Closing the final mix completes the club.
            club.state = "complete"
            club.completed_at = func.now()
            events.append((mix_, "club_complete"))
        else:
            # Auto-open the next pending mix in sequence, if any.
            next_mix = await db.scalar(
                select(Mix).where(
                    Mix.club_id == mix_.club_id,
                    Mix.mix_number == mix_.mix_number + 1,
                    Mix.state == "pending",
                )
            )
            if next_mix is not None and not next_mix.theme:
                # No theme yet (MYS-211) — mixes can't open without one, and
                # there's no admin present in an auto-advance to set it. Leave
                # the club with no active mix (current_mix stays put) and nudge
                # the organizer instead of silently opening a themeless mix.
                events.append((next_mix, "needs_theme"))
            elif next_mix is not None:
                next_mix.state = "open_submission"
                next_mix.submission_opened_at = func.now()
                # Same club window as the manual open (MYS-159): stamp the next
                # mix's submission deadline unless it was set explicitly.
                if next_mix.submission_deadline is None:
                    next_mix.submission_deadline = datetime.now(timezone.utc) + timedelta(
                        hours=club.submission_window_hours
                    )
                club.current_mix = next_mix.mix_number
                events.append((next_mix, "submission_open"))
    return events


async def rollback_mix_to_submission(mix_: Mix, club: Club, db: AsyncSession) -> None:
    """Organizer-only reverse transition, ``open_voting -> open_submission``
    (MYS-168) — the single sanctioned backward step in an otherwise forward-only
    lifecycle. Born from a live incident where a mix advanced to voting by
    accident and had to be rolled back by hand-run SQL; this reproduces exactly
    that fix as a supported action.

    Unlike ``advance_mix_state``, every stamp here is an unconditional
    overwrite, not a no-clobber guard — the mix already has a stale
    ``submission_deadline`` from its first pass through ``open_submission``, and
    a rollback must replace it with a fresh full window, not preserve it.

    Caller must already hold the row lock (``with_for_update``) and have
    re-verified ``mix_.state == "open_voting"`` under that lock — this
    function only applies the transition, it does not itself guard concurrency.
    """
    mix_.state = "open_submission"
    mix_.submission_opened_at = func.now()
    mix_.submission_deadline = datetime.now(timezone.utc) + timedelta(
        hours=club.submission_window_hours
    )
    # Re-stamped when voting genuinely reopens; the no-clobber guard in
    # advance_mix_state requires this to be NULL.
    mix_.voting_deadline = None
    # Warnings re-arm for the new window/phase.
    mix_.submission_warning_sent_at = None
    mix_.voting_warning_sent_at = None
    mix_.empty_round_notice_sent_at = None
    # The ballot set may change under a reopened submission phase; stale votes
    # would poison results and could insta-satisfy the voting quorum on the
    # next pass. Notes are kept — they're appreciation, remain state-gated, and
    # resurface at close.
    await db.execute(delete(Vote).where(Vote.mix_id == mix_.id))

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
        update(AppleMixPlaylist)
        .where(
            AppleMixPlaylist.mix_id == mix_.id,
            AppleMixPlaylist.superseded_at.is_(None),
        )
        .values(superseded_at=func.now())
    )


async def submission_quorum_met(mix_: Mix, db: AsyncSession) -> bool:
    """True iff every member active when submissions opened has at least one song
    in the mix (MYS-69 auto-advance).

    Active-at-open set = club members with ``joined_at <= submission_opened_at``
    and ``removed_at IS NULL``. Met when that set is a subset of the mix's
    distinct submitters. A NULL ``submission_opened_at`` (shouldn't happen for an
    open mix) is guarded as not met; an empty active-at-open set is treated as
    NOT met so an empty mix is never advanced.
    """
    if mix_.submission_opened_at is None:
        return False
    active_ids = set(
        await db.scalars(
            select(ClubMember.user_id).where(
                ClubMember.club_id == mix_.club_id,
                ClubMember.joined_at <= mix_.submission_opened_at,
                ClubMember.removed_at.is_(None),
            )
        )
    )
    if not active_ids:
        return False
    submitter_ids = set(
        await db.scalars(select(Submission.user_id).where(Submission.mix_id == mix_.id).distinct())
    )
    return active_ids <= submitter_ids


async def voting_quorum_met(mix_: Mix, db: AsyncSession) -> bool:
    """True iff every playing submitter in the mix has cast a vote.

    Playing submitter set = distinct submitters whose ``participation_mode`` is
    ``playing`` (vibers are excluded — they can't vote). Met when that set is a
    subset of the mix's distinct voters. An empty playing set is treated as met
    only when there is at least one submission (i.e. everyone submitted as vibing);
    a mix with no submissions at all returns False so an empty mix is never
    auto-closed.
    """
    playing_ids = set(
        await db.scalars(
            select(Submission.user_id)
            .where(
                Submission.mix_id == mix_.id,
                Submission.participation_mode == "playing",
            )
            .distinct()
        )
    )
    if not playing_ids:
        # Guard: only treat all-vibing as quorum-met when there are actual submissions.
        total = await db.scalar(
            select(func.count()).select_from(Submission).where(Submission.mix_id == mix_.id)
        )
        return (total or 0) > 0
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.mix_id == mix_.id).distinct())
    )
    return playing_ids <= voter_ids


@router.post("/clubs/{league_id}/mixes", status_code=201, response_model=MixResponse)
async def create_mix(
    league_id: uuid.UUID,
    payload: MixCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MixResponse:
    club = await _load_club_as_organizer(
        league_id, current_user, db, "only an organizer or co-organizer can create mixes"
    )
    if club.state == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="the club has wrapped")

    # Mixes are strictly sequential: the current one must close first.
    open_mix = await db.scalar(
        select(Mix).where(Mix.club_id == league_id, Mix.state != "closed").limit(1)
    )
    if open_mix is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the current mystery mix must be closed before starting a new one",
        )

    existing = await db.scalar(
        select(func.count()).select_from(Mix).where(Mix.club_id == league_id)
    )
    next_number = (existing or 0) + 1
    if next_number > club.total_mixes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="all mixes for this club have already been created",
        )

    mix_ = Mix(
        club_id=league_id,
        mix_number=next_number,
        theme=payload.theme,
        description=payload.description,
        submission_deadline=payload.submission_deadline,
        voting_deadline=payload.voting_deadline,
        votes_per_player=(
            payload.votes_per_player
            if payload.votes_per_player is not None
            else club.votes_per_player
        ),
    )
    # A freshly created mix opens for submissions immediately (the model's
    # default state), so stamp when that window opened — auto-advance (MYS-69)
    # scopes its quorum to the members present at this moment.
    mix_.submission_opened_at = func.now()
    db.add(mix_)
    # The newly opened mix becomes the club's active mix. The
    # (club_id, mix_number) unique constraint guards integrity if two
    # creates ever race.
    club.current_mix = next_number
    await db.commit()
    await db.refresh(mix_)
    # A freshly created mix has no submissions or votes yet.
    return _to_response(mix_, 0, await _member_count(league_id, db))


@router.get("/clubs/{league_id}/mixes", response_model=list[MixResponse])
async def list_mixes(
    league_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MixResponse]:
    await _load_club_as_member(league_id, current_user, db)
    mixes = list(
        await db.scalars(select(Mix).where(Mix.club_id == league_id).order_by(Mix.mix_number.asc()))
    )
    member_count = await _member_count(league_id, db)
    mix_ids = [m.id for m in mixes]
    # One grouped count per field for the whole slate rather than a query per mix.
    # Distinct submitters (people, not songs — MYS-116).
    count_rows = await db.execute(
        select(Submission.mix_id, func.count(func.distinct(Submission.user_id)))
        .where(Submission.mix_id.in_(mix_ids))
        .group_by(Submission.mix_id)
    )
    counts = {mix_id: count for mix_id, count in count_rows.all()}
    # Viewer participation: one query each for submitted/voted mix IDs.
    sub_rows = await db.execute(
        select(Submission.mix_id)
        .where(Submission.mix_id.in_(mix_ids), Submission.user_id == current_user.id)
        .distinct()
    )
    viewer_submitted_ids = {row[0] for row in sub_rows.all()}
    vote_rows = await db.execute(
        select(Vote.mix_id)
        .where(Vote.mix_id.in_(mix_ids), Vote.voter_id == current_user.id)
        .distinct()
    )
    viewer_voted_ids = {row[0] for row in vote_rows.all()}
    # Distinct voters per mix (MYS-110).
    voted_rows = await db.execute(
        select(Vote.mix_id, func.count(func.distinct(Vote.voter_id)))
        .where(Vote.mix_id.in_(mix_ids))
        .group_by(Vote.mix_id)
    )
    voted_counts = {mix_id: count for mix_id, count in voted_rows.all()}
    # Distinct playing submitters per mix — the voting denominator (MYS-110).
    eligible_rows = await db.execute(
        select(Submission.mix_id, func.count(func.distinct(Submission.user_id)))
        .where(
            Submission.mix_id.in_(mix_ids),
            Submission.participation_mode == "playing",
        )
        .group_by(Submission.mix_id)
    )
    eligible_counts = {mix_id: count for mix_id, count in eligible_rows.all()}
    return [
        _to_response(
            m,
            counts.get(m.id, 0),
            member_count,
            voted_counts.get(m.id, 0),
            eligible_counts.get(m.id, 0),
            viewer_submitted=m.id in viewer_submitted_ids,
            viewer_voted=m.id in viewer_voted_ids,
        )
        for m in mixes
    ]


@router.get("/mixes/{round_id}", response_model=MixResponse)
async def get_mix(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MixResponse:
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)
    return _to_response(
        mix_,
        await _submission_count(round_id, db),
        await _member_count(mix_.club_id, db),
        await _voted_count(round_id, db),
        await _voting_eligible_count(round_id, db),
        viewer_submitted=await _viewer_submitted(round_id, current_user.id, db),
        viewer_voted=await _viewer_voted(round_id, current_user.id, db),
    )


@router.patch("/mixes/{round_id}", response_model=MixResponse)
async def update_mix(
    round_id: uuid.UUID,
    payload: MixUpdate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
    spotify_client: SpotifyClient = Depends(get_spotify_client),
) -> MixResponse:
    mix_ = await _load_mix(round_id, db)
    club = await _load_club_as_organizer(
        mix_.club_id, current_user, db, "only an organizer or co-organizer can update mixes"
    )

    updates = payload.model_dump(exclude_unset=True)
    new_state = updates.pop("state", None)
    # Lifecycle emails to fire once the transition commits (MYS-109). Collected as
    # (mix, event) so an auto-opened next mix notifies for *its* opening.
    events: list[tuple[Mix, MixEvent]] = []
    voting_opened = False

    # Field edits (theme, deadlines) are frozen once the mix is closed.
    if updates and mix_.state == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="mystery mix is closed")
    # theme/description are the mix's identity: editable only while pending.
    # Once the mix opens, they are locked even though deadlines stay editable.
    if mix_.state != "pending" and ("theme" in updates or "description" in updates):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="theme and description are locked once the mystery mix opens",
        )
    for field, value in updates.items():
        setattr(mix_, field, value)

    if new_state is not None and new_state != mix_.state:
        # The single sanctioned backward step (MYS-168): open_voting ->
        # open_submission. Everything else stays forward-only.
        is_rollback = mix_.state == "open_voting" and new_state == "open_submission"
        if not is_rollback and new_state != _NEXT_STATE.get(mix_.state):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"cannot move mystery mix from {mix_.state} to {new_state}",
            )
        # A mix can't open without a theme (MYS-211) — checked after the field
        # updates above have already applied, so setting the theme and opening
        # in the same request works. A rollback is exempt: the mix already
        # opened once before (theme is locked once non-pending), so it's
        # guaranteed to have one.
        if new_state == "open_submission" and not is_rollback and not mix_.theme:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="set a theme before opening this mystery mix",
            )
        # Opening a pending mix: only one mix may be active per club. This
        # guard is the organizer's manual step only; auto-advance never makes the
        # pending->open_submission move, so it lives here, not in the helper. A
        # rollback is exempt — the mix is already the club's active mix,
        # so there is by definition no *other* active mix to conflict with.
        if new_state == "open_submission" and not is_rollback:
            active = await db.scalar(
                select(Mix)
                .where(
                    Mix.club_id == mix_.club_id,
                    Mix.id != mix_.id,
                    Mix.state.in_(_ACTIVE_STATES),
                )
                .limit(1)
            )
            if active is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="another mix is already active",
                )
        if is_rollback:
            # Serialize with the deadline force-advance job and the vote-cast
            # auto-close (MYS-145/MYS-69) under the same FOR UPDATE discipline,
            # then re-verify under the lock — the mix may have just been
            # force-closed or auto-closed concurrently.
            locked = await db.scalar(
                select(Mix)
                .where(Mix.id == mix_.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked is None or locked.state != "open_voting":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="this mystery mix is no longer open for voting",
                )
            await rollback_mix_to_submission(mix_, club, db)
            # Silent (product decision 2026-07-04): the organizer tells the
            # club directly, matching the incident's actual behavior — no
            # "submissions reopened" email. `events` stays empty.
        else:
            events = await advance_mix_state(mix_, club, new_state, db)
            voting_opened = any(event == "voting_open" for _, event in events)
            # All-vibing edge: if voting just opened but every participant is vibing,
            # nobody will ever call cast_votes, so voting quorum is immediately met.
            # Close in the same transaction and suppress the voting_open notification
            # (nobody could vote in a mix that closes in the same breath) — but
            # `voting_opened` stays true so the playlist still generates below; vibers
            # still get a listen-along playlist even though the mix never really
            # waits for votes.
            if mix_.state == "open_voting" and await voting_quorum_met(mix_, db):
                events = [e for e in events if e != (mix_, "voting_open")]
                events += await advance_mix_state(mix_, club, "closed", db)

    # Build + schedule notifications before commit, while the ORM objects are
    # loaded (avoids post-commit lazy-loads in async — the expire_on_commit
    # MissingGreenlet trap). Background tasks only run on a successful response,
    # so a failed commit below means no emails go out.
    if events:
        recipients = await gather_recipients(db, mix_.club_id)
        # needs_theme (MYS-211) is organizer-only, never the whole club.
        theme_notice_recipients = (
            await organizer_recipient(db, club)
            if any(event == "needs_theme" for _, event in events)
            else []
        )
        for event_mix, event in events:
            event_recipients = theme_notice_recipients if event == "needs_theme" else recipients
            queue_mix_event(
                background_tasks, sender, settings, event_recipients, club, event_mix, event
            )

    # Auto-generate the shared-account Spotify playlist the moment voting opens
    # (MYS-176) — no admin click needed. Best-effort: never raises, so a Spotify
    # hiccup can't block this transition (see try_auto_generate_playlist). Uses
    # `voting_opened` (captured before the all-vibing rollup above may have
    # stripped the voting_open event from `events`), not the events list itself.
    if voting_opened:
        await try_auto_generate_playlist(round_id, mix_, club, db, spotify_client, settings)

    await db.commit()
    await db.refresh(mix_)
    return _to_response(
        mix_,
        await _submission_count(mix_.id, db),
        await _member_count(mix_.club_id, db),
        await _voted_count(mix_.id, db),
        await _voting_eligible_count(mix_.id, db),
        viewer_submitted=await _viewer_submitted(mix_.id, current_user.id, db),
        viewer_voted=await _viewer_voted(mix_.id, current_user.id, db),
    )


# Upper bound on how far a single extension may push the deadline out,
# measured from the *current* deadline (MYS-180) — the organizer picks any
# point in this window, not a fixed increment.
_MAX_VOTING_EXTENSION = timedelta(hours=48)


class ExtendVotingRequest(WireModel):
    voting_deadline: datetime


@router.post("/mixes/{round_id}/extend-voting", response_model=MixResponse)
async def extend_voting_deadline(
    round_id: uuid.UUID,
    payload: ExtendVotingRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
    settings: Settings = Depends(get_settings),
) -> MixResponse:
    """Push a mix's voting deadline to an organizer-chosen time, up to 48h past
    the current deadline (MYS-180).

    Same permission level as every other mix-management action (organizer or
    co-organizer). Only valid while the mix is still ``open_voting`` — locked
    under ``FOR UPDATE`` and re-verified, the same discipline as the MYS-168
    rollback path, since this races the deadline job and vote-cast auto-close."""
    mix_ = await _load_mix(round_id, db)
    club = await _load_club_as_organizer(
        mix_.club_id, current_user, db, "only an organizer or co-organizer can extend voting"
    )

    locked = await db.scalar(
        select(Mix)
        .where(Mix.id == mix_.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None or locked.state != "open_voting":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="mystery mix is not open for voting",
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

    recipients = await gather_recipients(db, club.id)
    queue_mix_event(background_tasks, sender, settings, recipients, club, locked, "voting_extended")

    await db.commit()
    await db.refresh(locked)
    return _to_response(
        locked,
        await _submission_count(locked.id, db),
        await _member_count(locked.club_id, db),
        await _voted_count(locked.id, db),
        await _voting_eligible_count(locked.id, db),
        viewer_submitted=await _viewer_submitted(locked.id, current_user.id, db),
        viewer_voted=await _viewer_voted(locked.id, current_user.id, db),
    )


# --------------------------------------------------------------------------- #
# Playlist (MYS-18 slice B)
# --------------------------------------------------------------------------- #


class PlaylistEntry(WireModel):
    submission_id: str
    # None for a source-only track (Bandcamp/YouTube, no catalog ISRC — MYS-201).
    isrc: str | None
    # source/source_url identify a source-only track and let the voting playlist
    # badge it "YouTube only"/"Bandcamp only" (MYS-201); both None for a normal
    # ISRC-backed catalog submission. Mirrors ResultSubmission/RevealPick.
    source: Literal["youtube", "bandcamp"] | None = None
    source_url: str | None = None
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


class PlaylistResponse(WireModel):
    round_id: str
    round_number: int
    # Nullable: a mix may not have a theme yet (clients fall back to "Mix N").
    theme: str | None
    state: str
    entries: list[PlaylistEntry]
    # A single ad-hoc YouTube link that plays the whole mix in playlist order
    # (watch_videos?video_ids=...), or None if no track resolved to a YouTube id.
    youtube_playlist_url: str | None
    # How many of the mix's tracks made it into the YouTube link, so the UI can
    # show "N of M on YouTube". 0 when youtube_playlist_url is None.
    youtube_track_count: int
    # Voting progress (MYS-102): "X of Y voted or noted · Z just vibing".
    #  - voting_eligible (Y): playing participants — the ones who can vote.
    #  - voting_acted    (X): playing participants who have cast a vote OR left a
    #    note this mix.
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


@router.get("/mixes/{round_id}/playlist", response_model=PlaylistResponse)
async def get_mix_playlist(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    youtube: YouTubeResolver = Depends(get_youtube_resolver),
) -> PlaylistResponse:
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)
    # The playlist is the voting surface; it opens once submissions are locked.
    if mix_.state == "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the playlist is available once voting opens",
        )

    submissions = list(await db.scalars(select(Submission).where(Submission.mix_id == round_id)))
    # Anonymous + shuffled (technical-design §8). Sort by id first so Postgres heap
    # order doesn't affect the result, then seed the shuffle on the mix id for a
    # stable per-mix order that's consistent across all playlist platforms (MYS-151).
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    # Voting progress (MYS-102). Playing participants are the eligible voters;
    # vibing participants sit voting out (reported separately). A playing player
    # counts as having "acted" once they've cast a vote or left a note.
    playing_user_ids = {s.user_id for s in submissions if s.participation_mode == "playing"}
    vibing_count = sum(1 for s in submissions if s.participation_mode == "vibing")
    voter_ids = set(
        await db.scalars(select(Vote.voter_id).where(Vote.mix_id == round_id).distinct())
    )
    note_author_ids = set(
        await db.scalars(select(Note.author_id).where(Note.mix_id == round_id).distinct())
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
                source=source_fields(s.source_key)[0],
                source_url=source_fields(s.source_key)[1],
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
        # mixes light up; cache it back so it's a one-time cost per submission.
        # Source-only tracks (MYS-201) are never fuzzy-resolved: a youtube: row
        # already carries its exact id from submit time, and a bandcamp: row must
        # never be linked to a *guessed* video, so it simply sits out the playlist.
        video_id = s.youtube_video_id
        if not video_id and not s.source_key:
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
        round_id=str(mix_.id),
        round_number=mix_.mix_number,
        theme=mix_.theme,
        state=mix_.state,
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


class ResultNote(WireModel):
    body: str
    author_display_name: str
    created_at: datetime


class ResultVoter(WireModel):
    user_id: str
    display_name: str


class ResultSubmission(WireModel):
    submission_id: str
    user_id: str
    submitter_display_name: str
    # None for a source-only track; source/source_url identify it instead, and
    # let the reveal render a "Bandcamp"/"YouTube only" badge (MYS-201).
    isrc: str | None
    source: Literal["youtube", "bandcamp"] | None = None
    source_url: str | None = None
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
    # open_voting; this is only ever populated on the closed-mix reveal, and
    # only on ResultSubmission — the vibe-safe RevealPick/WinnerReveal shapes
    # below intentionally omit it so a vibing viewer never sees voter identity,
    # matching the existing no-vote-count rule (MYS-112).
    voters: list[ResultVoter]


class LeaderboardEntry(WireModel):
    user_id: str
    display_name: str
    vote_count: int
    rank: int


class MostNotedWinner(WireModel):
    submission_id: str
    title: str
    artist: str
    note_count: int
    notes: list[ResultNote]


class MostNotedResult(WireModel):
    note_count: int
    winners: list[MostNotedWinner]


class WinnerReveal(WireModel):
    # The vibe-safe winner shape (MYS-112): the song(s) with the most votes,
    # named but WITHOUT a vote count. Sent to a vibing viewer, who sees who won
    # but no rankings/tallies.
    submission_id: str
    title: str
    artist: str
    submitter_display_name: str


class RevealPick(WireModel):
    # The vibe-safe pick shape (MYS-134): a submitted song with its submitter and
    # notes, but NO vote count — so a vibing viewer can see the tracklist without
    # any scores/rankings leaking.
    submission_id: str
    submitter_display_name: str
    title: str
    artist: str
    # Track identity, mirroring ResultSubmission — None isrc + source/source_url
    # for a source-only track (MYS-201). No vote data, so it stays vibe-safe.
    isrc: str | None = None
    source: Literal["youtube", "bandcamp"] | None = None
    source_url: str | None = None
    # Playback links so the tiles are playable, same as the player reveal.
    platforms: dict[str, str]
    submitter_note: str | None
    notes: list[ResultNote]


class ResultsResponse(WireModel):
    round_id: str
    round_number: int
    # Nullable: a mix may not have a theme yet (clients fall back to "Mix N").
    theme: str | None
    state: str
    # Reveal is gated by the viewer's participation mode for the mix (MYS-112).
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


@router.get("/mixes/{round_id}/results", response_model=ResultsResponse)
async def get_mix_results(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResultsResponse:
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)
    # Results are the reveal: submitters and vote tallies stay hidden until close.
    if mix_.state != "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="results are available once the mystery mix closes",
        )

    # Submissions joined to their submitter (revealed now the mix is closed).
    submission_rows = (
        await db.execute(
            select(Submission, User.display_name)
            .join(User, User.id == Submission.user_id)
            .where(Submission.mix_id == round_id)
        )
    ).all()

    # Vote tallies in one pass; submissions with no votes are simply absent here
    # and default to 0 below.
    vote_count_rows = (
        await db.execute(
            select(Vote.submission_id, func.count())
            .where(Vote.mix_id == round_id)
            .group_by(Vote.submission_id)
        )
    ).all()
    votes_by_submission: dict[uuid.UUID, int] = {sid: count for sid, count in vote_count_rows}

    # Voter identity per submission (MYS-173) — who cast each vote, revealed only
    # now that the mix is closed (voting itself stays anonymous throughout
    # open_voting; this endpoint is already gated to state == "closed" above).
    voter_rows = (
        await db.execute(
            select(Vote.submission_id, Vote.voter_id, User.display_name)
            .join(User, User.id == Vote.voter_id)
            .where(Vote.mix_id == round_id)
        )
    ).all()
    voters_by_submission: dict[uuid.UUID, list[ResultVoter]] = {}
    for submission_id, voter_id, display_name in voter_rows:
        voters_by_submission.setdefault(submission_id, []).append(
            ResultVoter(user_id=str(voter_id), display_name=display_name)
        )
    for voters in voters_by_submission.values():
        voters.sort(key=lambda v: v.display_name)

    # All notes for the mix, joined to author display names, grouped in Python.
    note_rows = (
        await db.execute(
            select(Note, User.display_name)
            .join(User, User.id == Note.author_id)
            .where(Note.mix_id == round_id)
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
            source=source_fields(s.source_key)[0],
            source_url=source_fields(s.source_key)[1],
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

    # Reveal gating (MYS-112). The viewer's mode for this mix comes from their
    # own submission (read from the ORM rows — it's not exposed on the response);
    # a non-submitter is treated as a player (full reveal).
    own_sub = next((s for s, _ in submission_rows if s.user_id == current_user.id), None)
    viewer_is_vibing = own_sub is not None and own_sub.participation_mode == "vibing"

    if not viewer_is_vibing:
        return ResultsResponse(
            round_id=str(mix_.id),
            round_number=mix_.mix_number,
            theme=mix_.theme,
            state=mix_.state,
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
            isrc=s.isrc,
            source=s.source,
            source_url=s.source_url,
            platforms=s.platforms,
            submitter_note=s.submitter_note,
            notes=s.notes,
        )
        for s in sorted(submissions, key=lambda s: s.title)
    ]
    return ResultsResponse(
        round_id=str(mix_.id),
        round_number=mix_.mix_number,
        theme=mix_.theme,
        state=mix_.state,
        viewer_is_vibing=True,
        submissions=[],
        leaderboard=[],
        most_noted=most_noted_result,
        winners=winners,
        picks=picks,
    )
