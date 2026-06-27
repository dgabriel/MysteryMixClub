"""Song submission endpoints (MYS-51).

Puts songs — picked via the search/resolve flow — into a round. A player may hold
up to the league's ``songs_per_submission`` cap (MYS-116); at cap 1 this is the
classic one-song-per-round behavior.

* ``POST   /api/v1/rounds/:id/submissions``       — add a song (up to the cap)
* ``PATCH  /api/v1/rounds/:id/submissions/:sid``  — replace one of your songs
* ``DELETE /api/v1/rounds/:id/submissions/:sid``  — remove one of your songs
* ``GET    /api/v1/rounds/:id/submissions/mine``  — your songs for the round
* ``GET    /api/v1/rounds/:id/submissions``       — all submissions (after close only)

The canonical track fields (isrc/title/artist/album/art) come from the client's
prior search/resolve call; the server additionally assembles cross-service
platform links (keyless) and persists them as ``submissions.platform_links`` for
playlist/playback. The assembler always returns at least open-on-service deep
links, so a transient upstream hiccup never blocks the submission.

``participation_mode`` (just-vibing) is a per-player stance for the round, not a
per-song one: it is kept uniform across all of a player's songs (MYS-112/116).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member
from app.api.routes.rounds import _load_round
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.league_member import LeagueMember
from app.models.submission import Submission
from app.models.user import User
from app.services.song_links import SongLinkAssembler, get_link_assembler
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

router = APIRouter(tags=["submissions"])

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Isrc = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)]
Album = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
AlbumArtUrl = Annotated[str, StringConstraints(max_length=2048)]


class SubmissionCreate(BaseModel):
    # Canonical identity + display fields from the search/resolve result. The
    # cross-service links are assembled server-side from title/artist/isrc. Used
    # for both adding a song (POST) and replacing one wholesale (PATCH).
    isrc: Isrc
    title: ShortText
    artist: ShortText
    album: Album | None = None
    album_art_url: AlbumArtUrl | None = None
    note: Note | None = None
    participation_mode: Literal["playing", "vibing"] | None = None


class SubmissionResponse(BaseModel):
    id: str
    round_id: str
    user_id: str
    isrc: str
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    note: str | None
    participation_mode: str
    created_at: datetime


def _to_response(s: Submission) -> SubmissionResponse:
    return SubmissionResponse(
        id=str(s.id),
        round_id=str(s.round_id),
        user_id=str(s.user_id),
        isrc=s.isrc,
        title=s.title,
        artist=s.artist,
        album=s.album,
        album_art_url=s.album_art_url,
        note=s.note,
        participation_mode=s.participation_mode,
        created_at=s.created_at,
    )


async def _assemble_track(
    payload: SubmissionCreate,
    assembler: SongLinkAssembler,
    youtube: YouTubeResolver,
) -> tuple[dict[str, str], str | None]:
    """Resolve the keyless cross-service links + a YouTube video id for a track.

    Best-effort: the assembler always returns at least deep links, and the
    YouTube resolve is None on any failure, so neither blocks a submission.
    """
    platform_links = await assembler.assemble(payload.title, payload.artist, payload.isrc)
    youtube_video_id = await youtube.video_id_for(payload.title, payload.artist)
    return platform_links, youtube_video_id


def _apply_track(
    s: Submission, payload: SubmissionCreate, links: dict[str, str], yt: str | None
) -> None:
    """Write a resolved track onto a submission row (shared by add + replace)."""
    s.isrc = payload.isrc
    s.title = payload.title
    s.artist = payload.artist
    s.album = payload.album
    s.album_art_url = payload.album_art_url
    s.platform_links = links
    s.youtube_video_id = yt
    s.note = payload.note


async def _own_round_submissions(
    round_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> list[Submission]:
    return list(
        await db.scalars(
            select(Submission)
            .where(Submission.round_id == round_id, Submission.user_id == user_id)
            .order_by(Submission.created_at.asc())
        )
    )


async def _resolve_mode(
    payload_mode: str | None,
    existing: list[Submission],
    league_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """The player's vibe stance for the round: explicit override → their current
    stance (from any existing song) → their per-league default (MYS-112)."""
    if payload_mode is not None:
        return payload_mode
    if existing:
        return existing[0].participation_mode
    member = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id,
            LeagueMember.user_id == user_id,
            LeagueMember.removed_at.is_(None),
        )
    )
    return "vibing" if (member is not None and member.vibe_mode) else "playing"


@router.post(
    "/rounds/{round_id}/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_song(
    round_id: uuid.UUID,
    payload: SubmissionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    assembler: SongLinkAssembler = Depends(get_link_assembler),
    youtube: YouTubeResolver = Depends(get_youtube_resolver),
) -> SubmissionResponse:
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_member(round_.league_id, current_user, db)
    if round_.state != "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this round is not accepting submissions"
        )

    existing = await _own_round_submissions(round_id, current_user.id, db)
    if len(existing) >= league.songs_per_submission:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"you've submitted the maximum of {league.songs_per_submission} song(s)",
        )

    platform_links, youtube_video_id = await _assemble_track(payload, assembler, youtube)
    mode = await _resolve_mode(
        payload.participation_mode, existing, round_.league_id, current_user.id, db
    )
    # Keep the player's vibe stance uniform across all their songs this round.
    for s in existing:
        s.participation_mode = mode

    submission = Submission(round_id=round_id, user_id=current_user.id, participation_mode=mode)
    _apply_track(submission, payload, platform_links, youtube_video_id)
    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return _to_response(submission)


@router.patch("/rounds/{round_id}/submissions/{submission_id}", response_model=SubmissionResponse)
async def edit_song(
    round_id: uuid.UUID,
    submission_id: uuid.UUID,
    payload: SubmissionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    assembler: SongLinkAssembler = Depends(get_link_assembler),
    youtube: YouTubeResolver = Depends(get_youtube_resolver),
) -> SubmissionResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    if round_.state != "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this round is not accepting submissions"
        )

    submission = await db.scalar(
        select(Submission).where(Submission.id == submission_id, Submission.round_id == round_id)
    )
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission not found in this round"
        )
    if submission.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="that submission isn't yours"
        )

    platform_links, youtube_video_id = await _assemble_track(payload, assembler, youtube)
    _apply_track(submission, payload, platform_links, youtube_video_id)
    # An explicit mode change applies to all the player's songs (uniform stance).
    if payload.participation_mode is not None:
        for s in await _own_round_submissions(round_id, current_user.id, db):
            s.participation_mode = payload.participation_mode

    await db.commit()
    await db.refresh(submission)
    return _to_response(submission)


@router.delete(
    "/rounds/{round_id}/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_song(
    round_id: uuid.UUID,
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    if round_.state != "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this round is not accepting submissions"
        )

    submission = await db.scalar(
        select(Submission).where(Submission.id == submission_id, Submission.round_id == round_id)
    )
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="submission not found in this round"
        )
    if submission.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="that submission isn't yours"
        )

    await db.delete(submission)
    await db.commit()


@router.get("/rounds/{round_id}/submissions/mine", response_model=list[SubmissionResponse])
async def get_my_submissions(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionResponse]:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    submissions = await _own_round_submissions(round_id, current_user.id, db)
    return [_to_response(s) for s in submissions]


@router.get("/rounds/{round_id}/submissions", response_model=list[SubmissionResponse])
async def list_submissions(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionResponse]:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    # Submissions stay private until the round closes (anonymity during voting).
    if round_.state != "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="submissions are revealed after the round closes",
        )
    submissions = await db.scalars(
        select(Submission)
        .where(Submission.round_id == round_id)
        .order_by(Submission.created_at.asc())
    )
    return [_to_response(s) for s in submissions]
